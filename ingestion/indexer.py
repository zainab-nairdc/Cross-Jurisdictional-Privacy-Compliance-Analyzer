# indexer.py
# writes pre-built vectors into chromadb.
#
# we use langchain's chroma wrapper to handle the connection plumbing, but we
# do NOT let it embed anything for us. embedder.py is the one that adds the
# jurisdiction prefix to each chunk, so if langchain ever ran its own
# embedding it would skip our prefix and we'd get vectors that don't match
# what we already wrote. the _NoOpEmbeddings class below crashes loudly if
# that ever happens, so we'd notice immediately.

from __future__ import annotations

import sys
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import CHROMA_DIR, CHROMA_COLLECTION


_BATCH_SIZE = 100
_vectorstore: Chroma | None = None


class _NoOpEmbeddings(Embeddings):
    """a safety net.
    langchain wants an embedding function when you build the chroma wrapper.
    we don't want it to actually embed anything — embedder.py already did
    that, with the jurisdiction prefix. so we hand it this class instead.
    if anything ever calls these methods, that means something is bypassing
    our embedder, and we crash loudly so we catch it right away."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("[indexer] FAIL: LangChain tried to auto-embed. Always use embedder.py!")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("[indexer] FAIL: Query embedding belongs in retriever.py.")


def sanitize_metadata(meta: dict) -> dict:
    """chroma is picky — it only stores strings, numbers, and booleans on a
    chunk's metadata. anything else (lists, dicts, None) gets converted to
    a string before we save."""
    out: dict = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif v is None:
            out[k] = ""
        else:
            out[k] = str(v)
    return out


def get_vectorstore() -> Chroma:
    """open the chroma connection once and reuse it.
    on windows, opening the same chroma db twice in one process can cause
    file lock fights — so a singleton is safer."""
    global _vectorstore
    if _vectorstore is None:
        print(f"[indexer] Initializing vectorstore at {CHROMA_DIR}")
        _vectorstore = Chroma(
            collection_name=CHROMA_COLLECTION,
            embedding_function=_NoOpEmbeddings(),
            persist_directory=str(CHROMA_DIR),
            collection_metadata={"hnsw:space": "cosine"},
        )
    return _vectorstore


def index_chunks(chunks: list[dict], embeddings: list[list[float]]) -> None:
    """save chunks + their pre-built vectors into chromadb.

    we go straight to chroma's raw collection here (vectorstore._collection)
    instead of langchain's add_texts(). reason: add_texts() would try to
    re-embed everything, throwing away the work embedder.py already did and
    breaking the jurisdiction prefix. upsert() lets us pass embeddings in
    directly. it also overwrites existing rows by id, so re-running ingest
    is safe — same chunk just gets refreshed."""
    vectorstore = get_vectorstore()
    collection = vectorstore._collection

    ids       = [c["node_id"] for c in chunks]
    documents = [c["content"] for c in chunks]
    # everything except content + node_id rides along as searchable metadata
    metadatas = [sanitize_metadata({k: v for k, v in c.items() if k not in {"content", "node_id"}}) for c in chunks]

    # write in batches — chroma is happier with ~100 at a time than one giant call
    for start in range(0, len(ids), _BATCH_SIZE):
        collection.upsert(
            ids=ids[start : start + _BATCH_SIZE],
            embeddings=embeddings[start : start + _BATCH_SIZE],
            documents=documents[start : start + _BATCH_SIZE],
            metadatas=metadatas[start : start + _BATCH_SIZE],
        )


def get_collection() -> Chroma:
    """old name for get_vectorstore(). kept around so nothing breaks if older
    code still calls it."""
    return get_vectorstore()


def delete_doc_chunks(doc_title: str) -> None:
    """Delete every Chroma row for a document title. Best-effort — a missing
    collection or an unknown title is a harmless no-op. Used before deleting or
    re-ingesting a document so stale vectors don't linger alongside the new set."""
    if not doc_title:
        return
    try:
        get_vectorstore()._collection.delete(where={"doc_title": doc_title})
    except Exception as exc:
        print(f"[indexer] delete_doc_chunks failed for {doc_title!r}: {exc}")