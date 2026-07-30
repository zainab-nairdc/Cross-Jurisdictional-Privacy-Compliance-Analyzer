# retriever.py
# the read side of the system. hybrid retrieval built on llamaindex.
#
# pipeline when you call search() / hybrid_search():
#   1. embed the query with the bge query prefix (matches the doc-side
#      prefix that ingestion/embedder.py used)
#   2. vector search via llamaindex's ChromaVectorStore
#   3. keyword search via our own sqlite fts5 store, wrapped in a tiny
#      BaseRetriever so QueryFusionRetriever can call it
#   4. reciprocal rank fusion to merge the two ranked lists
#   5. cross-encoder rerank for a precision boost on the top candidates
#   6. (optional) attach parent body for context expansion
#
# why we keep a custom sqlite fts5 bm25 instead of using llamaindex's
# built-in BM25Retriever: persistence + per-query metadata filtering.
# llamaindex's bm25 is in-memory only (no filter pushdown) and would have
# to be rebuilt every process start, which made the pipeline slower and
# less accurate at filtered queries (jurisdiction-specific etc.). the eval
# in tests/eval_retrievers.py confirmed: hit_rate@5 went from 0.95 to 0.875
# when we tried swapping to the in-memory version.
#
# kept synchronous on purpose. the async api adds debugging friction and
# our queries finish in well under two seconds once warm.
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
import threading
from pathlib import Path

import chromadb
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import BaseRetriever, QueryFusionRetriever, VectorIndexRetriever
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.schema       import NodeWithScore, QueryBundle, TextNode
from llama_index.core.vector_stores import (
    FilterCondition, FilterOperator, MetadataFilter, MetadataFilters,
)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma   import ChromaVectorStore

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import (
    CHROMA_DIR, CHROMA_COLLECTION, EMBED_MODEL, EMBED_QUERY_PREFIX, JURISDICTION_NORM,
)
from retrieval.bm25_store import search_bm25, get_parent

# Term Dictionary expansion. Folds cross-jurisdiction synonyms onto the query
# (e.g. "permission" -> "permission consent authorisation"). Imported at module
# top so the failure surfaces at startup rather than per-query. If the module
# is missing on some checkout, fall back to identity so retrieval still works.
try:
    from reasoning.term_dictionary import expand_query
except ImportError:
    def expand_query(q: str) -> str:
        return q

# default cross-encoder reranker. small (~80MB) and fast on cpu — the eval
# in tests/eval_retrievers.py showed it actually beat bge-reranker-large on
# our corpus, so it's the production default.
_DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class _SQLiteBM25Retriever(BaseRetriever):
    """wraps our sqlite fts5 store so QueryFusionRetriever can treat it as
    just another retriever. this is the bridge between our lightweight bm25
    backend and llamaindex's fusion machinery."""

    def __init__(self, top_k: int = 20, filters: dict | None = None):
        super().__init__()
        self._top_k   = top_k
        self._filters = filters or {}

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        rows = search_bm25(query_bundle.query_str, top_k=self._top_k, **self._filters)
        return [
            NodeWithScore(
                node=TextNode(text=r["content"], metadata=r["metadata"], id_=r["id"]),
                score=r["bm25_score"],
            )
            for r in rows
        ]


class RetrievalService:
    """one instance per process. holds the chroma index, the embed model, and
    (lazily) the reranker. opening a second chroma client on the same db on
    windows can hit file lock issues, so reuse this singleton."""

    def __init__(
        self,
        chroma_dir:        Path | str = CHROMA_DIR,
        chroma_collection: str        = CHROMA_COLLECTION,
        embed_model:       str        = EMBED_MODEL,
        rerank_model:      str        = _DEFAULT_RERANK_MODEL,
        candidates:        int        = 20,
    ):
        self.cfg = dict(
            chroma_dir=str(chroma_dir),
            chroma_collection=chroma_collection,
            embed_model=embed_model,
            rerank_model=rerank_model,
            candidates=candidates,
        )

        # QueryFusionRetriever pulls an LLM dependency from Settings.llm even
        # when num_queries=1 (no rewrite step). We use a MockLLM so retrieval
        # doesn't bind the whole process to a real LLM. Only assign if Settings
        # hasn't been explicitly set elsewhere — avoid clobbering a real LLM if
        # another module already configured it.
        if not isinstance(getattr(Settings, '_llm', None), MockLLM):
            Settings.llm = MockLLM()

        # query_instruction is what makes bge-style asymmetric retrieval work.
        # without it, query vectors don't match doc vectors.
        self._embed = HuggingFaceEmbedding(
            model_name        = embed_model,
            query_instruction = EMBED_QUERY_PREFIX,
        )

        # open the same chroma collection ingestion wrote to. raw chromadb
        # client because llamaindex's ChromaVectorStore expects that shape.
        client = chromadb.PersistentClient(path=str(chroma_dir))
        col    = client.get_or_create_collection(
            chroma_collection, metadata={"hnsw:space": "cosine"},
        )
        vstore = ChromaVectorStore(chroma_collection=col)

        # llamaindex doesn't re-embed anything here — it just learns about
        # the existing vectors so its retriever can query them.
        self._index = VectorStoreIndex.from_vector_store(
            vector_store=vstore,
            embed_model=self._embed,
        )

        self._reranker = None    # loaded lazily on first use

    def _get_reranker(self) -> SentenceTransformerRerank:
        if self._reranker is None:
            self._reranker = SentenceTransformerRerank(
                model=self.cfg["rerank_model"],
                top_n=self.cfg["candidates"],
            )
        return self._reranker

    @staticmethod
    def _normalise_jurs(jurs: list[str]) -> list[str]:
        # callers might pass "bahrain"; data is stored as "Bahrain". use the
        # same lookup that ingestion uses so both sides agree.
        return [JURISDICTION_NORM.get(j.lower(), j) for j in jurs]

    def _build_chroma_filters(
        self,
        jurisdiction:  str | None,
        jurisdictions: list[str] | None,
        doc_type:      str | None,
        doc_title:     str | None,
        doc_titles:    list[str] | None = None,
        topic:         str | None = None,
        subcategory:   str | None = None,
    ):
        """build llamaindex's MetadataFilters from the simple kwargs that
        callers pass us. returns None if no filter is requested.
        doc_titles (list) takes priority over doc_title (str) — pass either."""
        clauses = []
        jur_list = jurisdictions or ([jurisdiction] if jurisdiction else None)
        if jur_list:
            normalised = self._normalise_jurs(jur_list)
            if len(normalised) == 1:
                clauses.append(MetadataFilter(key="jurisdiction", value=normalised[0]))
            else:
                clauses.append(MetadataFilter(
                    key="jurisdiction", value=normalised, operator=FilterOperator.IN,
                ))
        if doc_type:
            clauses.append(MetadataFilter(key="doc_type", value=doc_type))
        title_list = doc_titles or ([doc_title] if doc_title else None)
        if title_list:
            if len(title_list) == 1:
                clauses.append(MetadataFilter(key="doc_title", value=title_list[0]))
            else:
                clauses.append(MetadataFilter(
                    key="doc_title", value=title_list, operator=FilterOperator.IN,
                ))
        # Taxonomy filters. Backfill writes these onto chunk metadata in chroma.
        # Untagged chunks have no `topic`/`subcategory` keys, so a filter
        # request narrows the candidate set to tagged chunks only.
        if topic:
            clauses.append(MetadataFilter(key="topic", value=topic))
        if subcategory:
            clauses.append(MetadataFilter(key="subcategory", value=subcategory))
        if not clauses:
            return None
        return MetadataFilters(filters=clauses, condition=FilterCondition.AND)

    @staticmethod
    def _bm25_filters(
        jurisdiction:  str | None,
        jurisdictions: list[str] | None,
        doc_type:      str | None,
        doc_title:     str | None,
        doc_titles:    list[str] | None = None,
        topic:         str | None = None,
        subcategory:   str | None = None,
    ) -> dict:
        # search_bm25's keyword args. shape mirrors the public api 1:1.
        return {
            "jurisdiction":  jurisdiction,
            "jurisdictions": jurisdictions,
            "doc_type":      doc_type,
            "doc_title":     doc_title,
            "doc_titles":    doc_titles,
            "topic":         topic,
            "subcategory":   subcategory,
        }

    def search(
        self,
        query:           str,
        top_k:           int                = 5,
        jurisdiction:    str | None         = None,
        jurisdictions:   list[str] | None   = None,
        doc_type:        str | None         = None,
        doc_title:       str | None         = None,
        doc_titles:      list[str] | None   = None,
        topic:           str | None         = None,
        subcategory:     str | None         = None,
        rerank:          bool               = True,
        expand_parent:   bool               = True,
        expand_synonyms: bool               = True,
    ) -> list[NodeWithScore]:
        """run the full retrieval pipeline and return top_k results.
        pass `doc_titles=[...]` to scope retrieval to a specific set of
        documents — the filter pushes down into chromadb's WHERE clause and
        sqlite's WHERE clause, so the LLM physically cannot see anything
        outside the selected documents.

        ``expand_synonyms`` adds cross-jurisdictional vocabulary from the
        Term Dictionary onto the query (e.g., a user asking about
        "permission" also gets Bahrain's "consent" and India's "data
        principal" wired into the search). Disable for retrieval evals
        that need a controlled query."""
        # query expansion — folds in synonyms from the cross-jurisdiction
        # dictionary so retrieval is robust to terminology drift between
        # the user's wording and how each law phrases the same concept.
        # cheap (sub-ms substring scan over ~60 terms) and safe to leave on.
        effective_query = query
        if expand_synonyms:
            try:
                effective_query = expand_query(query)
            except Exception:
                # never let dictionary failures break a search
                effective_query = query

        candidates = self.cfg["candidates"]
        chroma_filters = self._build_chroma_filters(
            jurisdiction, jurisdictions, doc_type, doc_title, doc_titles,
            topic=topic, subcategory=subcategory,
        )
        bm25_filters = self._bm25_filters(
            jurisdiction, jurisdictions, doc_type, doc_title, doc_titles,
            topic=topic, subcategory=subcategory,
        )

        vector = VectorIndexRetriever(
            index             = self._index,
            similarity_top_k  = candidates,
            filters           = chroma_filters,
        )
        bm25 = _SQLiteBM25Retriever(top_k=candidates, filters=bm25_filters)

        # newer QueryFusionRetriever doesn't take rrf_k — it hardcodes k=60
        # internally for reciprocal_rerank mode. fine for our purposes.
        fusion = QueryFusionRetriever(
            [vector, bm25],
            similarity_top_k = candidates,
            num_queries      = 1,
            mode             = "reciprocal_rerank",
            use_async        = False,
        )

        nodes = fusion.retrieve(effective_query)

        if rerank and nodes:
            # rerank against the ORIGINAL query — the reranker measures
            # semantic relevance, and synonym noise hurts more than it
            # helps once we have candidate chunks in hand.
            try:
                reranker = self._get_reranker()
                qb = QueryBundle(query_str=query)
                nodes = reranker.postprocess_nodes(nodes, qb)
            except Exception as exc:
                # A reranker hiccup must not drop the whole result set — fall
                # back to the fusion order (still relevant, just not precision-
                # boosted) and log loudly, because losing the rerank silently
                # is exactly what makes e.g. penalty articles rank below scope
                # articles for a "penalties" query.
                import logging
                logging.getLogger(__name__).warning(
                    "reranker failed, falling back to fusion order: %r", exc
                )

        nodes = nodes[:top_k]

        if expand_parent:
            for n in nodes:
                pid = n.node.metadata.get("parent_chunk_id")
                if pid:
                    parent = get_parent(pid)
                    if parent:
                        n.node.metadata["_parent"] = parent

        return nodes


# module-level singleton + functional shim
# the django app and a few test scripts call hybrid_search() as a plain
# function with the same signature we used to expose. keeping that surface
# stable so upgrades don't ripple through the codebase.

_default_service: RetrievalService | None = None
_service_lock = threading.Lock()


def _get_service() -> RetrievalService:
    """Thread-safe lazy singleton. Double-checked locking so the fast path
    after init is lock-free, but two concurrent first-callers don't both
    build a service (which on Windows can race on ChromaDB's file lock and
    waste 5s + 500MB loading the embedder twice)."""
    global _default_service
    if _default_service is None:
        with _service_lock:
            if _default_service is None:
                _default_service = RetrievalService()
    return _default_service


def hybrid_search(
    query:           str,
    top_k:           int              = 5,
    jurisdiction:    str | None       = None,
    jurisdictions:   list[str] | None = None,
    doc_type:        str | None       = None,
    doc_title:       str | None       = None,
    doc_titles:      list[str] | None = None,
    topic:           str | None       = None,
    subcategory:     str | None       = None,
    rerank:          bool             = True,
    expand_parent:   bool             = True,
    expand_synonyms: bool             = True,
) -> list[NodeWithScore]:
    """convenience wrapper around the singleton RetrievalService. callers
    that just need a "give me chunks for this query" function can use this
    instead of building a service themselves.

    `doc_titles=[...]` scopes retrieval to a specific set of documents —
    push-down filter at the database layer.

    `expand_synonyms=True` (default) folds in cross-jurisdiction synonyms
    from reasoning.term_dictionary; pass False for controlled retrieval
    evals."""
    return _get_service().search(
        query=query,
        top_k=top_k,
        jurisdiction=jurisdiction,
        jurisdictions=jurisdictions,
        doc_type=doc_type,
        doc_title=doc_title,
        doc_titles=doc_titles,
        topic=topic,
        subcategory=subcategory,
        rerank=rerank,
        expand_parent=expand_parent,
        expand_synonyms=expand_synonyms,
    )


def search_comparative(
    query:        str,
    reg_a:        str,
    reg_b:        str,
    top_k:        int  = 6,
    rerank:       bool = True,
    doc_title_a:  str | None = None,
    doc_title_b:  str | None = None,
) -> dict:
    """fetch relevant chunks from two jurisdictions in parallel.
    use this when you want a side-by-side comparison view between two
    regulatory regimes for the same question."""
    svc = _get_service()
    return {
        "regulation_a": svc.search(query, top_k=top_k, jurisdiction=reg_a,
                                   doc_title=doc_title_a, rerank=rerank),
        "regulation_b": svc.search(query, top_k=top_k, jurisdiction=reg_b,
                                   doc_title=doc_title_b, rerank=rerank),
    }


# back-compat helpers
# tests/eval.py imports these from the old custom retriever to do its own
# cosine-similarity scoring. they're trivially small, so keep them available
# rather than asking that file to learn the new api.

def _get_st_model():
    """return the underlying SentenceTransformer instance.
    same singleton ingestion uses, so loading once warms it for everyone."""
    from ingestion.embedder import get_model
    return get_model()


def _embed_query(query: str) -> list[float]:
    """embed a query with the bge query prefix, normalized for cosine."""
    model = _get_st_model()
    vec = model.encode(
        _QUERY_PREFIX + query,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vec.tolist()
