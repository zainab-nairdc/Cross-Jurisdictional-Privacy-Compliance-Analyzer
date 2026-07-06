"""Generate NDA-safe code outline files for the most important production
modules. Mirrors the real project layout so the reader can navigate the
outlines as if browsing the source.

Output: thesis_docs/code_3_3_outlines/<module path>/<file>.py

Curated to 34 files — the algorithmic core, the security layer, the
audit layer, the workflow models, and the export layer. Trivial files
(apps.py, admin.py, urls.py, management plumbing, auxiliary helpers) are
deliberately omitted so the reader sees only the load-bearing logic.

After running this script, open each .py in VS Code and CodeSnap any
file that the docx generators reference. Save each PNG to
diagrams/code_3_3/<id>_<name>.png as listed in the capture brief.
"""

from pathlib import Path


OUTLINES: dict[str, str] = {}


# ════════════════════════════════════════════════════════════════════════
# INGESTION MODULE (5 files)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['ingestion/loaders.py'] = '''\
# ingestion/loaders.py
# Document loaders. Extracts text from PDF, DOCX, PPTX, XLSX, HTML, MD.


def load_document(path):
    """Read one document from disk and return a LoadedDocument.

    Returns a structure with: text (markdown), content_hash (SHA-256
    for dedup), page_count, mime type, and any extraction warnings.
    """
    # 1. Detect the MIME type from the file extension.
    # 2. Dispatch to the matching loader: Docling for PDF/DOCX/PPTX,
    #    BeautifulSoup for HTML, plain read for Markdown.
    # 3. Compute SHA-256 over the raw bytes for dedup.
    # 4. Convert the extracted content to Markdown so the chunker sees a
    #    uniform input regardless of the source format.
    # 5. Return the LoadedDocument record.
    pass
'''


OUTLINES['ingestion/chunker.py'] = '''\
# ingestion/chunker.py
# Two-level chunker: markdown headers define section boundaries,
# oversize sections fall through to a recursive token splitter.


def chunk_document(text, meta):
    """Split one Markdown document into a list of chunk dicts.

    Each chunk carries: node_id, text, section_title, hierarchy_path,
    obligation_tag, jurisdiction, doc_title, regulation_name, page hint.
    """
    # 1. Run MarkdownHeaderTextSplitter over h1..h4 to get sections.
    # 2. For each section, decide whether the body fits in a chunk
    #    (CHUNK_TOKENS, with CHUNK_OVERLAP_TOKENS overlap).
    # 3. If too large, fall through to RecursiveCharacterTextSplitter
    #    using a tiktoken cl100k_base encoder.
    # 4. Build chunk dicts via _make_chunk; classify each as obligation
    #    or background via _classify.
    # 5. Skip empty bodies via _has_real_body.
    # 6. Generate a deterministic node_id via _node_id (path slug + hash).
    # 7. Return the list of chunk dicts.
    pass


def _make_chunk(body, meta, hierarchy, section_title):
    """Assemble one chunk dict ready for embedding + indexing."""
    # 1. Build the hierarchy_path string from the parent header chain.
    # 2. Apply _classify(body, section_title) to set obligation_tag.
    # 3. Generate node_id via _node_id(meta, hierarchy_path).
    # 4. Return a flat dict with all the citation metadata.
    pass


def _classify(body, section_title):
    """Tag a chunk as 'obligation', 'background', or 'unknown'."""
    # 1. Check the section title for obligation cue words ("shall",
    #    "must", "required").
    # 2. Check the body for the same cues plus deontic verbs.
    # 3. Fall back to background when no cues fire; return unknown when
    #    the body is too short to decide.
    pass
'''


OUTLINES['ingestion/embedder.py'] = '''\
# ingestion/embedder.py
# Wraps the BGE-small SentenceTransformer with a citation-aware prefix.


def embed_chunks(chunks, st_model=None):
    """Embed a batch of chunks. Returns a list of 384-dim vectors."""
    # 1. Get or create the singleton SentenceTransformer model.
    # 2. For each chunk, build the prefixed text via embed_text(chunk).
    # 3. Pass the batched prefixed strings into model.encode().
    # 4. Return the vectors as plain Python lists (Chroma-friendly).
    pass


def embed_text(chunk):
    """Build the citation-aware prefix used at embed time."""
    # 1. Compose "Jurisdiction: <X>\\nCitation: <Y>\\n<body>" where X is
    #    the jurisdiction code (BH/IN/KW) and Y is the verbatim citation
    #    label (e.g., "PDPL Article 4").
    # 2. The prefix repeats at query time so the cosine space aligns.
    pass


def get_model():
    """Return the cached SentenceTransformer instance."""
    # 1. Lazy-load BGE-small from hf_cache/ on first call.
    # 2. Cache and return for subsequent calls.
    pass
'''


OUTLINES['ingestion/injection_scanner.py'] = '''\
# ingestion/injection_scanner.py
# Two-tier prompt-injection defence applied to every chunk before
# indexing. Tier A is deterministic regex; Tier B is an LLM judge with
# spotlight-tag protection. Fails closed.


def scan_chunk(content):
    """Run Tier A then Tier B on one chunk.

    Returns a Detection on flag, None on clean, JUDGE_UNAVAILABLE on
    fail-closed.
    """
    # 1. Run Tier A regex catalogue (nine rule groups). Short-circuit
    #    return on match.
    # 2. Otherwise call Tier B: an LLM judge.
    # 3. Try the OpenRouter judge first; on any error fall back to the
    #    local Ollama judge.
    # 4. If both judges raise, return JUDGE_UNAVAILABLE so the chunk is
    #    quarantined rather than indexed.
    # 5. Parse the judge response; return a Detection on a clear
    #    malicious verdict, otherwise None.
    pass


def scan_chunks(chunks):
    """Batch wrapper around scan_chunk."""
    # 1. Iterate over chunks; call scan_chunk for each.
    # 2. Accumulate Detection objects; preserve the chunk index.
    # 3. Return the list of (index, Detection) pairs.
    pass


def scan_tier_a(content):
    """Apply nine regex rule groups to one chunk."""
    # 1. INST_OVERRIDE: explicit overrides like "ignore previous".
    # 2. ROLE_HIJACK: "you are now <role>" patterns.
    # 3. FORCED_VERDICT: "answer yes" or "say <X>" directives.
    # 4. SAFETY_BYPASS: jailbreak prompts (DAN, evil twin).
    # 5. DEV_MODE_TRIGGER: developer-mode / sudo / debug toggles.
    # 6. PROMPT_LEAK: "repeat your system prompt".
    # 7. FAKE_DELIMITER: smuggled system tags.
    # 8. BASE64_BLOB: encoded payload heuristics.
    # 9. SUSPICIOUS_URL: data exfiltration URLs.
    # On any hit, return a Tier-A Detection with rule_id + snippet.
    pass


def _openrouter_judge(content):
    """Call the primary cloud judge with spotlight-tag protection."""
    # 1. Wrap the content in spotlight delimiters so the judging model
    #    cannot be jailbroken by the chunk itself.
    # 2. POST to the OpenRouter chat completions endpoint.
    # 3. Return the parsed verdict (malicious / clean / ambiguous).
    pass


def _ollama_judge(content):
    """Local fallback judge running against the bundled Ollama daemon."""
    # 1. Same spotlight-wrapped prompt as the OpenRouter judge.
    # 2. Use chat completions on localhost:11434.
    # 3. Return the parsed verdict.
    pass


def _parse_judge_response(text):
    """Extract the verdict from the judge's free-form output."""
    # 1. Try strict JSON first.
    # 2. Fall back to a regex-extraction of the verdict field.
    # 3. Return one of: "malicious", "clean", "ambiguous", "error".
    pass
'''


OUTLINES['ingestion/indexer.py'] = '''\
# ingestion/indexer.py
# Writes embedded chunks into ChromaDB and the BM25 store.


def index_chunks(chunks, embeddings):
    """Persist one batch of chunks into Chroma + BM25 in one transaction."""
    # 1. Confirm the chunk list and the embedding list line up by length.
    # 2. Sanitise metadata via sanitize_metadata: Chroma rejects nested
    #    dicts and non-primitives, so coerce everything to str/int/bool.
    # 3. Get the collection via get_collection(); use add() with ids,
    #    embeddings, documents, and metadatas in a single batched call.
    # 4. Mirror the same chunks into the BM25 FTS5 store so keyword
    #    search and vector search stay in sync.
    pass


def get_vectorstore():
    """Return the singleton Chroma vectorstore for LangChain consumers."""
    # 1. Open or create the persistent client at config.CHROMA_DIR.
    # 2. Return a Chroma vectorstore wrapping the singleton collection.
    pass


def get_collection():
    """Open or create the named Chroma collection (cosine metric)."""
    # 1. Build a PersistentClient pointed at CHROMA_DIR.
    # 2. Call get_or_create_collection with hnsw:space=cosine.
    pass


def sanitize_metadata(meta):
    """Coerce arbitrary metadata into Chroma-acceptable primitives."""
    # 1. For each key, drop None values.
    # 2. Stringify lists and dicts.
    # 3. Cast numbers to int or float.
    # 4. Return the cleaned dict.
    pass
'''


# ════════════════════════════════════════════════════════════════════════
# RETRIEVAL MODULE (2 files)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['retrieval/retriever.py'] = '''\
# retrieval/retriever.py
# Hybrid retrieval orchestrator. BM25 + Chroma + RRF + cross-encoder.


def hybrid_search(query, jurisdictions=None, doc_types=None, top_k=5):
    """Top entry point used by every reasoning workflow.

    Returns a ranked list of NodeWithScore objects.
    """
    # 1. Expand the query via term_dictionary.synonyms_for_query.
    # 2. Embed the expanded query with the BGE query prefix.
    # 3. Construct two retrievers in parallel: a Chroma vector retriever
    #    and a _SQLiteBM25Retriever (filtered by jurisdiction + doc_type).
    # 4. Wrap them in QueryFusionRetriever (mode=reciprocal_rerank, k=60).
    # 5. Pull a candidate pool of size 20.
    # 6. Rerank against the ORIGINAL query with a cross-encoder; synonyms
    #    help recall but hurt rerank precision.
    # 7. Truncate to top_k and return.
    pass


def search_comparative(query_a, query_b, jurisdiction):
    """Two-query retrieval for comparison workflows."""
    # 1. Run hybrid_search twice — once per side of the comparison.
    # 2. Scope each side to its own jurisdiction.
    # 3. Return a tuple of (nodes_a, nodes_b).
    pass


class RetrievalService:
    """Stateful wrapper around the Chroma client, BM25 index, and
    cross-encoder so they load once per process."""

    def __init__(self, config):
        """Configure but do not load any heavy models."""
        # 1. Store paths, collection name, top-k caps.
        # 2. All heavy objects (client, index, reranker) are lazy.
        pass

    def _get_index(self):
        """Lazy-open the Chroma collection."""
        # 1. Build a PersistentClient on first call.
        # 2. Call get_or_create_collection (hnsw:space=cosine).
        # 3. Wrap the collection in a ChromaVectorStore.
        # 4. Cache and return a VectorStoreIndex.
        pass

    def _get_reranker(self):
        """Lazy-load the cross-encoder model singleton."""
        # 1. Load ms-marco MiniLM cross-encoder from hf_cache/.
        # 2. Cache the model on self.
        pass


class _SQLiteBM25Retriever:
    """LlamaIndex BaseRetriever wrapping the FTS5 store so it can
    participate in QueryFusionRetriever."""

    def _retrieve(self, query_bundle):
        """Run BM25 search and return NodeWithScore objects."""
        # 1. Build the FTS5 MATCH expression from query_bundle.query_str.
        # 2. Apply WHERE filters for jurisdiction and doc_type.
        # 3. Order by bm25() score; cap at top_k.
        # 4. Convert SQLite rows into NodeWithScore objects.
        pass
'''


OUTLINES['retrieval/bm25_store.py'] = '''\
# retrieval/bm25_store.py
# SQLite FTS5 keyword index + auxiliary parent and tag tables.


_CREATE_TABLE = """
    CREATE VIRTUAL TABLE IF NOT EXISTS bm25_index USING fts5(
        node_id          UNINDEXED,
        content,
        jurisdiction     UNINDEXED,
        doc_type         UNINDEXED,
        doc_title        UNINDEXED,
        regulation_name  UNINDEXED,
        article_ref      UNINDEXED,
        tokenize = 'unicode61'
    )
"""


def upsert_chunks(chunks):
    """Insert or replace one batch of chunks in the FTS5 index."""
    # 1. Open the SQLite connection via _connect().
    # 2. _init() to create the schema on first run.
    # 3. DELETE existing rows by node_id (FTS5 has no INSERT OR REPLACE).
    # 4. INSERT new rows with all unindexed metadata + indexed content.
    # 5. Commit.
    pass


def search_bm25(query, jurisdiction=None, doc_type=None, top_k=20):
    """Run a BM25 query with optional jurisdiction and doc_type filters."""
    # 1. Build the MATCH expression from the user query.
    # 2. Apply WHERE jurisdiction = ? when supplied.
    # 3. Apply WHERE doc_type = ? when supplied.
    # 4. ORDER BY bm25(bm25_index); LIMIT top_k.
    # 5. Return result rows as dicts.
    pass


def upsert_parents(parents):
    """Persist oversize parent chunks separately for context expansion."""
    # 1. Create parents table on first call.
    # 2. INSERT OR REPLACE by node_id; store full parent_text and token
    #    count.
    pass


def get_parent(node_id):
    """Retrieve a parent chunk by node_id when a child hit needs context."""
    # 1. SELECT parent_text from parents WHERE node_id = ?.
    pass


def upsert_chunk_tags(rows):
    """Store the obligation/background/unknown classifier output."""
    # 1. Create chunk_tags table on first call.
    # 2. INSERT OR REPLACE (node_id, obligation_type).
    pass
'''


# ════════════════════════════════════════════════════════════════════════
# REASONING MODULE (6 files — the core, no auxiliaries)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['reasoning/schemas.py'] = '''\
# reasoning/schemas.py
# Pydantic v2 schemas used at every module boundary.

from pydantic import BaseModel, Field
from typing import Optional


class Citation(BaseModel):
    """One verbatim citation tying a finding to a source chunk."""
    chunk_id:        str
    jurisdiction:    str
    regulation_name: str
    article_ref:     str
    exact_quote:     str
    page_hint:       Optional[int] = None


class ReasoningStep(BaseModel):
    """One node activation in the LangGraph trace."""
    action:      str
    description: str
    inputs:      dict = Field(default_factory=dict)
    outputs:     dict = Field(default_factory=dict)
    timestamp:   str


class ReasonedAnswer(BaseModel):
    """The top-level shape returned by the orchestrator."""
    summary:         str
    citations:       list[Citation] = Field(default_factory=list)
    confidence:      float = Field(ge=0.0, le=1.0)
    reasoning_trace: list[ReasoningStep] = Field(default_factory=list)
    route_used:      str = "general"
    warnings:        list[str] = Field(default_factory=list)


class ObligationComparison(BaseModel):
    """One row in a regulation-versus-regulation comparison report."""
    topic:                 str
    reg_a_citation:        str = ""
    reg_b_citation:        str = ""
    reg_a_chunk_id:        str = ""
    reg_b_chunk_id:        str = ""
    reg_a_evidence:        str = ""
    reg_b_evidence:        str = ""
    equivalence:           str = "Different"
    similarity_score:      int = Field(default=0, ge=0, le=100)
    confidence_score:      int = Field(default=70, ge=0, le=100)
    citation_verified:     bool = False
    hallucination_risk:    float = Field(default=0.0, ge=0.0, le=1.0)


class PolicyCoverageItem(BaseModel):
    """One mapped obligation in a policy-coverage report."""
    obligation:    str
    regulation:    str
    coverage:      str   # covered / partial / requires_review / none
    evidence:      list[Citation] = Field(default_factory=list)
    legal_basis:   str = ""


class GapItem(BaseModel):
    """One gap surfaced by gap-analysis."""
    regulation:              str
    gap_description:         str
    severity:                str   # High / Medium / Low
    remediation_suggestion:  str
'''


OUTLINES['reasoning/orchestrator.py'] = '''\
# reasoning/orchestrator.py
# General-purpose Q&A LangGraph. Routes, drafts, verifies, corrects,
# finalises, with a SafeFallback escape hatch.

from typing import TypedDict


class ReasoningState(TypedDict, total=False):
    """Mutable state object threaded through every graph node."""
    request:             "SearchRequest"
    route:               str
    retrieved_chunks:    list
    draft:               "ReasonedAnswer"
    verification_score:  float
    hallucination_risk:  float
    cite_issues:         list[str]
    reasoning_trace:     list["ReasoningStep"]
    retries:             int
    error:               str
    final_output:        "ReasonedAnswer"


def build_reasoning_graph():
    """Wire and compile the LangGraph state machine."""
    # 1. Create a StateGraph over ReasoningState.
    # 2. Register six nodes: route, draft, verify, correct, finalize,
    #    fallback.
    # 3. Entry point is route.
    # 4. route -> draft (deterministic).
    # 5. draft -> verify or END (conditional via _after_draft).
    # 6. verify -> correct or finalize or fallback
    #    (conditional via _should_correct).
    # 7. correct -> verify.
    # 8. finalize -> END.
    # 9. fallback -> END.
    # 10. Compile (no checkpointer; each call is one-shot).
    pass


async def route_node(state):
    """Classify the query into open / comparison / mapping / gap."""
    pass


async def draft_node(state):
    """Generate a structured answer via the generator module."""
    pass


async def verify_node(state):
    """Run citation verification and hallucination scoring."""
    pass


async def correct_node(state):
    """Re-prompt the LLM with the verifier's diagnosis."""
    pass


async def finalize_node(state):
    """Adjust confidence and emit the final ReasonedAnswer."""
    pass


async def fallback_node(state):
    """Emit a safe canned response when the loop exhausts retries."""
    pass
'''


OUTLINES['reasoning/workflows.py'] = '''\
# reasoning/workflows.py
# Three domain-specific LangGraph workflows: comparison, mapping, gap.
# Each wraps the same draft/verify/correct/finalize pattern.


async def compare_regulations(jurisdiction_a, jurisdiction_b):
    """Run the comparison workflow end to end."""
    # 1. Build the per-call ComparisonState (jurisdictions, topics).
    # 2. Multi-query retrieval per side via _multi_query_retrieve.
    # 3. Invoke the compiled comparison graph (_build_comparison_graph).
    # 4. Return a ComparisonReport instance.
    pass


async def map_policy_coverage(policy_text, jurisdictions):
    """Map one policy against multiple jurisdictions."""
    pass


async def generate_gap_analysis(mapping_result):
    """Derive a ranked gap list from a finished mapping report."""
    pass


def _build_comparison_graph():
    """Construct the comparison LangGraph."""
    # 1. StateGraph(ComparisonState).
    # 2. Nodes: draft, verify, correct, finalize.
    # 3. Conditional edge from verify (correct or finalize).
    # 4. Compile (no checkpointer).
    pass


async def _comparison_draft(state):
    """Draft node for comparison: produce one row per topic with
    verbatim citations from both jurisdictions."""
    pass


def _multi_query_retrieve(query, jurisdiction):
    """Expand the query into multiple phrasings and union the hits."""
    pass


def _run_async(coro):
    """Run an async coroutine from synchronous Django view code."""
    # 1. Get or create an event loop.
    # 2. Call loop.run_until_complete(coro).
    pass
'''


OUTLINES['reasoning/validators.py'] = '''\
# reasoning/validators.py
# Verifier: citation grounding and NLI-based hallucination scoring.


def verify_grounding(draft, retrieved_chunks):
    """Confirm every citation in draft is grounded in a retrieved chunk.

    Returns (ok: bool, issue: str).
    """
    # 1. Build {chunk_id -> chunk_text} lookup.
    # 2. For each citation in the draft (per workflow shape):
    #    a. Confirm chunk_id is in the lookup.
    #    b. Normalise the verbatim quote (whitespace, smart quotes,
    #       case) via _normalise_quote.
    #    c. Require the quote to be at least ten characters long.
    #    d. Require it to be a substring of the normalised chunk text.
    # 3. Return (True, "") on full pass; (False, "<first issue>") on
    #    first failure.
    pass


def score_hallucination(text, chunk_text):
    """Cross-encoder NLI score in [0.0, 1.0] for one (chunk, text) pair."""
    # 1. Guard short inputs; return 1.0 when either is under ten chars.
    # 2. Load the NLI model via _get_ce_model.
    # 3. Predict logits over [contradiction, neutral, entailment].
    # 4. Apply softmax.
    # 5. Return 1.0 minus the entailment probability, rounded to 3 dp.
    pass
'''


OUTLINES['reasoning/generator.py'] = '''\
# reasoning/generator.py
# Draft-time LLM invocation with provider abstraction and
# OutputFixingParser auto-correction.

from langchain.output_parsers import OutputFixingParser, PydanticOutputParser


async def generate_structured(request, route, chunks, response_model):
    """Call the LLM and return a parsed Pydantic instance."""
    # 1. Format the retrieved chunks via _format_chunks (truncated to
    #    ~6000 chars, citation labels preserved).
    # 2. Build the route-specific prompt; include the response schema.
    # 3. Build a PydanticOutputParser(pydantic_object=response_model).
    # 4. Invoke the LLM asynchronously; capture raw output.
    # 5. Try to parse with the base parser. On success, return.
    # 6. On failure and cfg.llm.retry_attempts > 0, wrap with
    #    OutputFixingParser(max_retries=cfg.llm.retry_attempts) and
    #    re-parse.
    # 7. Return the parsed Pydantic instance, or raise on exhaustion.
    pass


def _build_llm():
    """Return the configured LangChain LLM with optional fallback."""
    # 1. Build the primary LLM (provider switched by env var).
    # 2. If cfg.llm.fallback_enabled is False, return the primary.
    # 3. Otherwise try to build the local Ollama fallback; on any error
    #    return the primary only.
    # 4. Wrap primary.with_fallbacks([fallback]) so LangChain retries
    #    against the fallback on any Exception.
    pass


def _build_local_fallback():
    """Build the local Ollama fallback (llama3.2:1b by default)."""
    # 1. Pass model, base_url=localhost:11434, format="json",
    #    num_ctx, request_timeout, num_predict.
    pass
'''


OUTLINES['reasoning/fallback.py'] = '''\
# reasoning/fallback.py
# SafeFallback: returns a typed, low-confidence answer when reasoning
# exhausts retries. Never hallucinates a body.


async def safe_fallback_response(request):
    """Return a ReasonedAnswer with confidence 0.3 and clear warning."""
    # 1. Build a short refusal body explaining grounded answer was not
    #    possible with the available context.
    # 2. Optionally suggest authoritative sources by keyword: privacy
    #    laws (PDPL/DPDPA/DPPR), banking sources, cyber frameworks,
    #    BBK policies. These are static strings, not LLM calls.
    # 3. Return a ReasonedAnswer with: summary, no citations,
    #    confidence=0.3, and a warning that the answer is not fully
    #    grounded.
    pass
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO PROJECT — cjpca/cjpca/settings.py (the central wiring file)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/cjpca/settings.py'] = '''\
# cjpca/cjpca/settings.py
# Top-level Django settings. Order of MIDDLEWARE is load-bearing.

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party security stack
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
    'two_factor',
    'csp',
    'axes',

    # HTMX integration
    'django_htmx',

    # Project apps (10)
    'apps.accounts',
    'apps.analytics',
    'apps.comparison',
    'apps.core',
    'apps.history',
    'apps.home',
    'apps.ingestion',
    'apps.library',
    'apps.mapping',
    'apps.review',
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'apps.accounts.middleware.GeoFenceMiddleware',
    'csp.middleware.CSPMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'apps.accounts.middleware.IdleSessionTimeoutMiddleware',
    'apps.accounts.middleware.ForcePasswordChangeMiddleware',
    'apps.accounts.middleware.ForceMFAEnrollmentMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'axes.middleware.AxesMiddleware',
]


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
     'OPTIONS': {'max_similarity': 0.5}},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    {'NAME': 'apps.accounts.validators.ComplexityValidator'},
    {'NAME': 'apps.accounts.validators.NoUsernameValidator'},
]


AXES_FAILURE_LIMIT       = 5
AXES_COOLOFF_TIME        = 0.5
AXES_LOCKOUT_PARAMETERS  = ['username', 'ip_address']
AXES_RESET_ON_SUCCESS    = True

SESSION_COOKIE_AGE              = 28_800
SESSION_COOKIE_SECURE           = True
SESSION_COOKIE_HTTPONLY         = True
SESSION_COOKIE_SAMESITE         = 'Lax'
SESSION_SAVE_EVERY_REQUEST      = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_IDLE_TIMEOUT            = 1_800

CSRF_COOKIE_SECURE   = True
CSRF_COOKIE_HTTPONLY = False   # HTMX/Alpine need to read the token
CSRF_COOKIE_SAMESITE = 'Lax'

SECURE_HSTS_SECONDS               = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS    = True
SECURE_HSTS_PRELOAD               = True
SECURE_SSL_REDIRECT               = True
SECURE_CONTENT_TYPE_NOSNIFF       = True
SECURE_REFERRER_POLICY            = 'same-origin'
X_FRAME_OPTIONS                   = 'DENY'


CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src':      ("'self'",),
        'script-src':       ("'self'", 'unpkg.com', 'cdn.jsdelivr.net'),
        'style-src':        ("'self'", 'api.fontshare.com'),
        'img-src':          ("'self'", 'flagcdn.com', 'data:', 'blob:'),
        'connect-src':      ("'self'",),
        'frame-ancestors':  ("'none'",),
    },
}


REQUIRE_MFA                  = True
TWO_FACTOR_PATCH_ADMIN       = True
GEOFENCE_ENABLED             = False
GEOFENCE_ALLOWED_COUNTRIES   = ['BH', 'IN', 'KW', 'AE']
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO APP — accounts (auth, MFA, RBAC, middleware, validators)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/apps/accounts/models.py'] = '''\
# cjpca/apps/accounts/models.py
# Custom user profile. One row per auth.User; carries the role.

from django.db import models
from django.conf import settings


class UserProfile(models.Model):
    """Per-user role and forced-rotation flags."""
    ANALYST  = 'analyst'
    REVIEWER = 'reviewer'
    ADMIN    = 'admin'

    ROLE_CHOICES = [
        (ANALYST,  'Analyst'),
        (REVIEWER, 'Reviewer'),
        (ADMIN,    'Admin'),
    ]

    user                  = models.OneToOneField(settings.AUTH_USER_MODEL,
                                                  on_delete=models.CASCADE)
    role                  = models.CharField(max_length=20,
                                              choices=ROLE_CHOICES,
                                              default=ANALYST)
    must_change_password  = models.BooleanField(default=True)
    created_at            = models.DateTimeField(auto_now_add=True)
'''


OUTLINES['cjpca/apps/accounts/middleware.py'] = '''\
# cjpca/apps/accounts/middleware.py
# Four custom middlewares: GeoFence, IdleSessionTimeout,
# ForcePasswordChange, ForceMFAEnrollment.


class GeoFenceMiddleware:
    """Block requests from countries outside the configured allowlist.
    Fails open so a misconfiguration does not lock BBK staff out."""

    def __init__(self, get_response):
        # 1. Cache enabled flag and the allowlist (upper-cased ISO codes).
        pass

    def __call__(self, request):
        # 1. No-op when disabled or allowlist is empty.
        # 2. Allow static/media prefixes without IP lookup.
        # 3. Extract client IP (X-Forwarded-For first hop / REMOTE_ADDR).
        # 4. Allow private/loopback IPs unconditionally.
        # 5. Lazy-load GeoLite2 reader with double-checked locking.
        # 6. Fail open if reader is None or lookup raises.
        # 7. Return HttpResponseForbidden when country is not allowed.
        pass


class IdleSessionTimeoutMiddleware:
    """Sign users out after SESSION_IDLE_TIMEOUT seconds of inactivity."""

    def __init__(self, get_response):
        # 1. Cache timeout (default 1800 seconds).
        pass

    def __call__(self, request):
        # 1. Skip when user is anonymous.
        # 2. Read _last_activity timestamp from session.
        # 3. If gap exceeds timeout: audit, logout, redirect to LOGIN_URL
        #    with ?reason=idle.
        # 4. Otherwise update _last_activity and continue.
        pass


class ForcePasswordChangeMiddleware:
    """Redirect users whose must_change_password flag is True."""

    def __init__(self, get_response):
        pass

    def __call__(self, request):
        # 1. Skip anonymous users.
        # 2. Skip exempt paths (password_change itself, logout, admin).
        # 3. Skip when must_change_password is False.
        # 4. Otherwise redirect to /accounts/password_change/.
        pass


class ForceMFAEnrollmentMiddleware:
    """Redirect users without a confirmed TOTP device to setup."""

    def __init__(self, get_response):
        pass

    def __call__(self, request):
        # 1. No-op when REQUIRE_MFA is False.
        # 2. Skip anonymous users.
        # 3. Skip exempt path prefixes (setup itself, login, static).
        # 4. Skip users who already have a confirmed device.
        # 5. Skip exempt URL names (login, password change, etc.).
        # 6. Otherwise redirect to two_factor:setup.
        pass
'''


OUTLINES['cjpca/apps/accounts/decorators.py'] = '''\
# cjpca/apps/accounts/decorators.py
# Role-based access control decorator + class-based view mixin.


def get_user_role(user):
    """Return the role string for a user, or '' for anonymous."""
    # 1. Return '' when user is None or anonymous.
    # 2. Look up the UserProfile via user.userprofile (one-to-one).
    # 3. Return profile.role.
    pass


def role_required(*allowed_roles):
    """Decorator: allow the view only for users in allowed_roles."""
    # 1. Outer factory takes the allowed-roles list.
    # 2. Inner decorator wraps the view; uses @login_required to bounce
    #    anonymous users.
    # 3. The wrapper resolves the role; returns 403 on mismatch.
    pass


class RoleRequiredMixin:
    """Class-based view variant of role_required."""
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        # 1. Login required: redirect anonymous users.
        # 2. Resolve the role; return 403 on mismatch.
        # 3. Otherwise call super().dispatch.
        pass
'''


OUTLINES['cjpca/apps/accounts/validators.py'] = '''\
# cjpca/apps/accounts/validators.py
# Custom password validators registered in AUTH_PASSWORD_VALIDATORS.

import re
from django.core.exceptions import ValidationError


class ComplexityValidator:
    """Require uppercase + lowercase + digit + symbol."""

    def __init__(self, require_upper=True, require_lower=True,
                 require_digit=True, require_symbol=True):
        # 1. Store each flag.
        pass

    def validate(self, password, user=None):
        # 1. Collect missing character classes.
        # 2. Raise ValidationError("Password must contain ...") on miss.
        pass

    def get_help_text(self):
        # 1. Render help text from the active flags.
        pass


class NoUsernameValidator:
    """Reject passwords that contain the username or email substring."""

    def validate(self, password, user=None):
        # 1. Skip if user is None.
        # 2. Lower-case both password and identifying strings.
        # 3. Raise ValidationError if username or email is contained.
        pass
'''


OUTLINES['cjpca/apps/accounts/signals.py'] = '''\
# cjpca/apps/accounts/signals.py
# Create the UserProfile on user creation so role lookups never miss.

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, created, **kwargs):
    """Create a UserProfile with role=analyst on first save."""
    # 1. Skip when created is False.
    # 2. UserProfile.objects.create(user=instance, role=ANALYST).
    pass
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO APP — history (audit log + signals + audit helper)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/apps/history/models.py'] = '''\
# cjpca/apps/history/models.py
# Append-only audit row. One row per security-relevant action.

from django.db import models
from django.conf import settings


class AuditLog(models.Model):
    """Cross-cutting audit trail. Indexed by user and event_type."""

    event_type          = models.CharField(max_length=50, db_index=True)
    user                = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    user_role_at_time   = models.CharField(max_length=20, blank=True)
    ip_address          = models.GenericIPAddressField(null=True, blank=True)
    timestamp           = models.DateTimeField(auto_now_add=True, db_index=True)
    description         = models.CharField(max_length=500)
    related_object_type = models.CharField(max_length=50, blank=True)
    related_object_id   = models.PositiveIntegerField(null=True, blank=True)
    change_detail       = models.JSONField(default=dict)

    class Meta:
        ordering = ['-timestamp']
        indexes  = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['event_type', '-timestamp']),
        ]
'''


OUTLINES['cjpca/apps/history/audit.py'] = '''\
# cjpca/apps/history/audit.py
# Single entry point for every audit write. Best-effort.


class Actions:
    """Canonical action constants. 28 entries total."""
    LOGIN              = 'auth.login'
    LOGOUT             = 'auth.logout'
    LOGIN_FAILED       = 'auth.login_failed'
    IDLE_TIMEOUT       = 'auth.idle_timeout'
    MFA_ENROLLED       = 'auth.mfa_enrolled'
    PASSWORD_CHANGED   = 'user.password_changed'
    ROLE_CHANGED       = 'user.role_changed'
    USER_CREATED       = 'user.created'
    DOCUMENT_UPLOAD    = 'document.upload'
    DOCUMENT_DELETE    = 'document.delete'
    QUARANTINE_FLAGGED = 'quarantine.flagged'
    QUARANTINE_APPROVED = 'quarantine.approved'
    QUARANTINE_REJECTED = 'quarantine.rejected'
    COMPARISON_RUN     = 'comparison.run'
    COMPARISON_DONE    = 'comparison.done'
    MAPPING_RUN        = 'mapping.run'
    MAPPING_DONE       = 'mapping.done'
    REVIEW_APPROVED    = 'review.approved'
    REVIEW_REJECTED    = 'review.rejected'
    REVIEW_MODIFIED    = 'review.modified'
    REVIEW_GAP_SYNCED  = 'review.gap_synced'
    EXPORT_PDF         = 'export.pdf'
    EXPORT_XLSX        = 'export.xlsx'
    REASONING_ERROR    = 'reasoning.validation_error'


def log_event(user, action, *, request=None, target_type='',
              target_id=None, description='', metadata=None):
    """Write one AuditLog row. Returns the row or None on failure."""
    # 1. Resolve username (anonymous when user is None or unauthenticated).
    # 2. Coerce target_id to int; clamp to non-negative or set None.
    # 3. Snapshot the role at write time via _snapshot_role.
    # 4. Extract IP via _extract_ip (X-Forwarded-For first hop).
    # 5. Default description to "<action> by <username>".
    # 6. AuditLog.objects.create with all fields.
    # 7. Wrap the body in try/except so failures never propagate.
    pass


def _snapshot_role(user):
    """Return the user's role string at write time."""
    pass


def _extract_ip(request):
    """Pull the client IP from X-Forwarded-For or REMOTE_ADDR."""
    pass
'''


OUTLINES['cjpca/apps/history/signals.py'] = '''\
# cjpca/apps/history/signals.py
# Connect Django auth signals to log_event.

from django.dispatch import receiver
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed,
)


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    """Write an auth.login row."""
    # 1. log_event(user, Actions.LOGIN, request=request,
    #              description=f'{user.username} signed in').
    pass


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    """Write an auth.logout row."""
    # 1. Skip when user is None.
    # 2. log_event(user, Actions.LOGOUT, request=request, ...).
    pass


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    """Record a failed login attempt without revealing the password."""
    # 1. Pull attempted username from credentials dict.
    # 2. log_event(None, Actions.LOGIN_FAILED, request=request,
    #              metadata={'attempted_username': attempted[:100]}).
    pass


# TOTPDevice post_save receiver emits auth.mfa_enrolled on first
# confirmed save.
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO APP — ingestion (quarantine model, WebSocket, pipeline)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/apps/ingestion/models.py'] = '''\
# cjpca/apps/ingestion/models.py
# Quarantine table for prompt-injection-flagged chunks.

from django.db import models
from django.conf import settings


class QuarantinedChunk(models.Model):
    """One row per flagged chunk. Reviewed by an admin."""

    HIGH   = 'high'
    MEDIUM = 'medium'

    TIER_A = 'tier_a'
    TIER_B = 'tier_b'
    JUDGE_UNAVAILABLE = 'judge_unavailable'

    PENDING  = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'

    severity         = models.CharField(max_length=10)
    tier             = models.CharField(max_length=20)
    rule_id          = models.CharField(max_length=40, blank=True)
    matched_snippet  = models.CharField(max_length=500, blank=True)
    all_detections   = models.JSONField(default=dict)
    chunk_text       = models.TextField()
    chunk_metadata   = models.JSONField(default=dict)

    status           = models.CharField(max_length=10, default=PENDING)
    decided_by       = models.ForeignKey(settings.AUTH_USER_MODEL,
                                          null=True, blank=True,
                                          on_delete=models.SET_NULL)
    decided_at       = models.DateTimeField(null=True, blank=True)
    decision_note    = models.CharField(max_length=200, blank=True)

    created_at       = models.DateTimeField(auto_now_add=True)
'''


OUTLINES['cjpca/apps/ingestion/consumers.py'] = '''\
# cjpca/apps/ingestion/consumers.py
# Django Channels consumer for live ingestion progress.

import json
from channels.generic.websocket import AsyncWebsocketConsumer


class IngestionConsumer(AsyncWebsocketConsumer):
    """Stream progress events for one ingestion job."""

    async def connect(self):
        # 1. Read job_id from URL kwargs.
        # 2. Join group "ingestion_<job_id>".
        # 3. Accept the connection.
        pass

    async def disconnect(self, close_code):
        # 1. Leave the per-job group.
        pass

    async def ingestion_update(self, event):
        # 1. Serialise event["data"] to JSON.
        # 2. Send to the connected client.
        pass
'''


OUTLINES['cjpca/apps/ingestion/pipeline.py'] = '''\
# cjpca/apps/ingestion/pipeline.py
# Glue layer between the ingestion library and the Django app.


def run_full_ingest(job_id):
    """Run a full ingestion pass over data/regulations + data/policies."""
    # 1. Mark the IngestionJob as RUNNING.
    # 2. Iterate every file under data/regulations/{bahrain,india,kuwait}/.
    # 3. For each file: load -> chunk -> scan_chunks (injection).
    # 4. Quarantine flagged chunks via _scan_chunks_for_injection.
    # 5. Embed the surviving chunks and index in Chroma + BM25.
    # 6. Stream progress events through the Channels group.
    # 7. Audit document.upload per file; quarantine.flagged per quarantine.
    # 8. Mark the IngestionJob as DONE or FAILED.
    pass


def _scan_chunks_for_injection(chunks):
    """Apply Tier A + Tier B; return safe chunks and quarantine rows."""
    # 1. Call injection_scanner.scan_chunks(chunks).
    # 2. For each Detection, create a QuarantinedChunk row.
    # 3. Audit each quarantine.flagged.
    # 4. Return only the chunks that passed both tiers.
    pass
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO APP — library (document model)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/apps/library/models.py'] = '''\
# cjpca/apps/library/models.py
# Document and topic tagging.

from django.db import models


class Document(models.Model):
    """One uploaded source document."""

    title           = models.CharField(max_length=300)
    jurisdiction    = models.CharField(max_length=10)
    doc_type        = models.CharField(max_length=20)   # regulation / policy
    regulation_name = models.CharField(max_length=200, blank=True)
    content_hash    = models.CharField(max_length=64, db_index=True)
    file            = models.FileField(upload_to='documents/')
    chunk_count     = models.PositiveIntegerField(default=0)
    classified_topics = models.JSONField(default=list)
    uploaded_by     = models.ForeignKey('auth.User', null=True,
                                         on_delete=models.SET_NULL)
    uploaded_at     = models.DateTimeField(auto_now_add=True)
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO APP — comparison (workflow state machine)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/apps/comparison/models.py'] = '''\
# cjpca/apps/comparison/models.py
# Comparison run state machine + result rows.

from django.db import models


class ComparisonRun(models.Model):
    """One comparison job and its lifecycle status."""

    PENDING  = 'pending'
    RUNNING  = 'running'
    DONE     = 'done'
    FAILED   = 'failed'

    jurisdiction_a = models.CharField(max_length=10)
    jurisdiction_b = models.CharField(max_length=10)
    pair_key       = models.CharField(max_length=20, db_index=True)
    status         = models.CharField(max_length=10, default=PENDING)
    created_by     = models.ForeignKey('auth.User', null=True,
                                        on_delete=models.SET_NULL)
    started_at     = models.DateTimeField(auto_now_add=True)
    completed_at   = models.DateTimeField(null=True, blank=True)
    error_message  = models.TextField(blank=True)
    report_json    = models.JSONField(default=dict)
    analyst_note   = models.TextField(blank=True)


class ComparisonResult(models.Model):
    """One row of a finished ComparisonRun."""
    run                  = models.ForeignKey(ComparisonRun,
                                              on_delete=models.CASCADE,
                                              related_name='rows')
    topic                = models.CharField(max_length=80)
    reg_a_citation       = models.CharField(max_length=200, blank=True)
    reg_b_citation       = models.CharField(max_length=200, blank=True)
    reg_a_evidence       = models.TextField(blank=True)
    reg_b_evidence       = models.TextField(blank=True)
    equivalence          = models.CharField(max_length=20)
    similarity_score     = models.PositiveSmallIntegerField(default=0)
    confidence_score     = models.PositiveSmallIntegerField(default=0)
    citation_verified    = models.BooleanField(default=False)
    hallucination_risk   = models.FloatField(default=0.0)
'''


OUTLINES['cjpca/apps/comparison/views.py'] = '''\
# cjpca/apps/comparison/views.py
# Comparison index, scope picker, run page, progress endpoint, detail.


def comparison_index(request):
    """List recent ComparisonRuns scoped to the analyst."""
    # 1. @role_required('analyst', 'reviewer', 'admin').
    # 2. Apply per-row scope: created_by=request.user for analysts.
    # 3. Render the index with status chips and audit_hash prefixes.
    pass


def comparison_scope(request, pair_key):
    """Analyst-only article picker for a regulation pair."""
    # 1. @role_required('analyst').
    # 2. Render the article-list UI for the two jurisdictions in pair_key.
    # 3. POST builds a ComparisonRun and dispatches via subprocess.
    pass


def comparison_run(request, run_pk):
    """Live progress page for a running comparison."""
    # 1. @role_required('analyst', 'reviewer', 'admin').
    # 2. HTMX polls every 1-2s via comparison_progress.
    pass


def comparison_progress(request, run_pk):
    """HTMX endpoint that returns a progress HTML fragment."""
    # 1. Read ComparisonRun.status, rows_done, rows_total.
    # 2. Render the partial; set HX-Trigger=done when status == DONE.
    pass


def _run_comparison_background(run_pk, include_orphans, articles_a, articles_b):
    """Subprocess entry point launched from the management command."""
    # 1. Multi-query retrieval per side (term-dictionary expansion).
    # 2. Invoke compare_regulations from reasoning.workflows.
    # 3. Persist ComparisonResult rows.
    # 4. Update ComparisonRun.status=DONE, completed_at, report_json.
    # 5. Audit comparison.done.
    pass
'''


OUTLINES['cjpca/apps/comparison/management/commands/run_comparison_job.py'] = '''\
# cjpca/apps/comparison/management/commands/run_comparison_job.py
# Subprocess entry point that runs one comparison workflow in isolation.

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Run one ComparisonRun by primary key."""

    help = 'Run a ComparisonRun job by primary key.'

    def add_arguments(self, parser):
        # 1. run_pk (positional int).
        # 2. --include-orphans flag.
        # 3. --articles-a list.
        # 4. --articles-b list.
        pass

    def handle(self, *args, **options):
        # 1. Re-assert ComparisonRun.status = RUNNING.
        # 2. Call _run_comparison_background(run_pk, include_orphans,
        #    articles_a, articles_b).
        pass
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO APP — mapping (policy-vs-regulations workflow)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/apps/mapping/models.py'] = '''\
# cjpca/apps/mapping/models.py
# Mapping analysis, obligation rows, gap rows + signal cascade.

from django.db import models


class MappingAnalysis(models.Model):
    """One mapping run from a BBK policy to one or more regulations."""

    DRAFT     = 'draft'
    SUBMITTED = 'submitted'
    APPROVED  = 'approved'
    REJECTED  = 'rejected'

    policy           = models.ForeignKey('library.Document',
                                          on_delete=models.CASCADE)
    target_jurisdictions = models.JSONField(default=list)
    status           = models.CharField(max_length=10, default=DRAFT)
    created_by       = models.ForeignKey('auth.User', null=True,
                                          on_delete=models.SET_NULL)
    submitted_for_review_at = models.DateTimeField(null=True, blank=True)
    completed_at     = models.DateTimeField(null=True, blank=True)
    report_json      = models.JSONField(default=dict)
    analyst_note     = models.TextField(blank=True)


class ObligationMapping(models.Model):
    """One obligation-versus-regulation row inside a MappingAnalysis."""

    analysis      = models.ForeignKey(MappingAnalysis, on_delete=models.CASCADE)
    obligation    = models.CharField(max_length=300)
    regulation    = models.CharField(max_length=200)
    coverage      = models.CharField(max_length=20)   # covered / partial / none
    evidence_json = models.JSONField(default=list)
    review_status = models.CharField(max_length=20, default='pending')
    review_notes  = models.TextField(blank=True)


class Gap(models.Model):
    """One actionable gap derived from an approved mapping."""

    analysis              = models.ForeignKey(MappingAnalysis,
                                                on_delete=models.CASCADE)
    obligation            = models.CharField(max_length=300)
    severity              = models.CharField(max_length=10)
    remediation_suggestion = models.TextField()
    due_date              = models.DateField(null=True, blank=True)

    @classmethod
    def sync_gap_on_approval(cls, obligation_mapping):
        """Class method invoked by post_save signal on ObligationMapping."""
        # 1. Skip when status is not APPROVED.
        # 2. Skip when coverage is not in {partial, none}.
        # 3. Call update_or_create on (analysis, obligation).
        # 4. Audit review.gap_synced.
        pass
'''


OUTLINES['cjpca/apps/mapping/views.py'] = '''\
# cjpca/apps/mapping/views.py
# Mapping index, run page, progress endpoint, result detail.


def mapping_index(request):
    """List MappingAnalyses scoped by role."""
    # 1. @role_required('analyst', 'reviewer', 'admin').
    # 2. Analysts see only their own runs.
    pass


def mapping_run(request, analysis_pk):
    """Live progress + final result page for one MappingAnalysis."""
    # 1. @role_required('analyst', 'reviewer', 'admin').
    # 2. HTMX polls mapping_progress.
    pass


def _run_mapping_background(analysis_pk):
    """Subprocess entry point launched from the management command."""
    # 1. Load the policy document.
    # 2. Auto-detect or use the provided jurisdiction scope.
    # 3. Invoke map_policy_coverage from reasoning.workflows.
    # 4. Persist ObligationMapping rows.
    # 5. Update MappingAnalysis.status; audit mapping.done.
    pass
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO APP — review (lifecycle + exports)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/apps/review/models.py'] = '''\
# cjpca/apps/review/models.py
# Reviewer accept/reject/modify lifecycle.

from django.db import models


class ReviewItem(models.Model):
    """One reviewable row (mapping or comparison output)."""

    PENDING   = 'pending'
    APPROVED  = 'approved'
    REJECTED  = 'rejected'
    MODIFIED  = 'modified'

    obligation_mapping = models.ForeignKey('mapping.ObligationMapping',
                                            on_delete=models.CASCADE,
                                            null=True, blank=True)
    status             = models.CharField(max_length=10, default=PENDING)
    reviewer           = models.ForeignKey('auth.User', null=True,
                                            on_delete=models.SET_NULL)
    notes              = models.TextField(blank=True)
    decided_at         = models.DateTimeField(null=True, blank=True)
'''


OUTLINES['cjpca/apps/review/exports.py'] = '''\
# cjpca/apps/review/exports.py
# PDF/XLSX builders + SHA-256 audit hash.

import hashlib


def audit_hash(obj):
    """Return a 16-character SHA-256 prefix over the row's identity."""
    # 1. Assemble identity tuple: class name, pk, status,
    #    completed_at, submitted_for_review_at, created_by_id.
    # 2. Join with '|', encode UTF-8.
    # 3. hashlib.sha256(...).hexdigest()[:16].
    pass


def build_pdf(rows, output_path, header):
    """Render rows to a PDF with audit_hash on every row."""
    # 1. SimpleDocTemplate(output_path, pagesize=A4).
    # 2. Compose a story: header block, table of rows, hash column.
    # 3. Apply TableStyle: navy header, alternating shade.
    # 4. doc.build(story).
    pass


def build_xlsx(rows, output_path):
    """Render rows to an XLSX workbook with the hash column."""
    # 1. Create a Workbook.
    # 2. Write a header row including 'audit_hash'.
    # 3. Loop the rows; append each + its audit_hash.
    # 4. Save to output_path.
    pass
'''


# ════════════════════════════════════════════════════════════════════════
# DJANGO APP — core (Copilot chat interface)
# ════════════════════════════════════════════════════════════════════════

OUTLINES['cjpca/apps/core/views.py'] = '''\
# cjpca/apps/core/views.py
# Copilot chat endpoint. Wraps the general-purpose reasoning agent in
# a session-backed chat interface with two retrieval modes and a
# scope-picker dropdown. Reuses the same draft / verify / correct /
# finalize guard-rails as the structured workflows.

from django.views import View


class CopilotMessageView(View):
    """POST /copilot/message/ — accept one chat message, return an
    HTMX-swappable HTML fragment with the grounded answer."""

    def post(self, request):
        # 1. Read the user message; short-circuit on empty.
        # 2. Pull session state: copilot_include_drafts, copilot_history
        #    (rolling 20-turn window), and the chosen doc_title.
        # 3. Read the mode toggle ('approved' by default, 'document' for
        #    single-document Q&A).
        # 4. In 'document' mode without a doc_title, return a friendly
        #    nudge ("pick a doc from the Scope chip first").
        # 5. In 'document' mode with a doc_title, call _retrieve_regulatory
        #    scoped to that document.
        # 6. In 'approved' mode, call _approved_retrieve (trust-tier
        #    dispatcher) which prefers reviewed comparison and mapping
        #    rows, then falls back to raw regulatory text.
        # 7. Re-fetch the underlying chunks via hybrid_search so the
        #    verify node has node_id + content + jurisdiction for each.
        # 8. Build a SearchRequest and invoke reasoning_graph (the
        #    compiled general-Q&A LangGraph from §3.3.9).
        # 9. Append (user_message, ai_response) to copilot_history and
        #    truncate to the last 20 turns.
        # 10. Render partials/_copilot_fragment.html with the answer,
        #     confidence, citations, hallucination_risk, and the
        #     data_quality / data_label chips for the source mix.
        pass


def _approved_retrieve(message, *, include_drafts=False, doc_title=''):
    """Trust-tier dispatcher.

    Prefers reviewed comparison + mapping rows. Falls back to raw
    regulatory chunks when no approved artefacts cover the question.
    Returns a dict with context (formatted string), citations (list),
    layer ('approved' / 'mixed' / 'regulatory'), data_quality, label,
    and an optional fallback_msg.
    """
    # 1. Query ReviewItem rows with status=APPROVED matching the message.
    # 2. If hits exist and include_drafts is False, return them as the
    #    primary context with layer='approved'.
    # 3. If include_drafts is True, union with submitted-for-review rows.
    # 4. If approved hits are sparse, augment with regulatory chunks
    #    from hybrid_search; layer='mixed'.
    # 5. If no approved hits at all, fall back to pure regulatory text;
    #    layer='regulatory' with a fallback_msg explaining the demotion.
    pass


def _retrieve_regulatory(message, *, doc_title=''):
    """Pure regulatory Q&A. Filters retrieval by doc_title when given."""
    # 1. Call hybrid_search with doc_titles=[doc_title] when supplied.
    # 2. Format the top-k chunks into a context string with citation
    #    labels preserved.
    # 3. Return (context_string, citations_list).
    pass


class CopilotClearView(View):
    """POST /copilot/clear/ — wipe the conversation history."""

    def post(self, request):
        # 1. Pop copilot_history from session.
        # 2. Return the empty-state fragment.
        pass


class CopilotToggleDraftsView(View):
    """POST /copilot/toggle-drafts/ — flip the include-drafts flag."""

    def post(self, request):
        # 1. Read current include_drafts (default False) and invert.
        # 2. Persist on session.
        pass


class ScopeStateView(View):
    """GET /copilot/scope/ — render the readiness chip and dropdown."""

    def get(self, request):
        # 1. Compute the scope state via scope.classify_state.
        # 2. Render the partial with state badge and doc selector.
        pass
'''


OUTLINES['cjpca/apps/core/scope.py'] = '''\
# cjpca/apps/core/scope.py
# Copilot readiness classifier. Tells the analyst when the Copilot
# is ready to answer, partially ready, or not ready, with a sentence
# that names the missing pieces.

from dataclasses import dataclass


@dataclass
class CategoryState:
    """Per-source-category state: row count + usable flag."""
    count:  int
    usable: bool


STATE_LABELS = {
    'not_ready':       'Not ready',
    'partially_ready': 'Partially ready',
    'ready':           'Ready',
}


def classify_state(categories):
    """Return one of {not_ready, partially_ready, ready}.

    Inputs the four category states: regulations, internal_policies,
    approved_comparisons, approved_mappings.
    """
    # 1. If neither regulations nor policies are usable, return
    #    'not_ready' (Copilot has no grounded sources at all).
    # 2. If all four categories are usable, return 'ready'.
    # 3. Otherwise return 'partially_ready' and let the template
    #    builder name which sources are missing.
    pass


def render_scope_sentence(state, categories):
    """Build the human sentence that explains the current scope."""
    # 1. Map state to one of READY / NOT_READY / PARTIAL templates.
    # 2. For partial cases, name the ready and missing category lists
    #    via _humanize_list ("regulations and approved mappings" / etc.).
    # 3. Return the rendered HTML span structure for the chip.
    pass


def _humanize_list(items):
    """Convert a list into a comma-and-and joined string."""
    # 1. Empty -> '' / one -> single item / two -> 'a and b' /
    #    three or more -> 'a, b, and c'.
    pass
'''


# ════════════════════════════════════════════════════════════════════════
# ROOT — config.py
# ════════════════════════════════════════════════════════════════════════

OUTLINES['config.py'] = '''\
# config.py
# Root project config. Loaded by both the Django settings module and the
# pure-Python ingestion/retrieval/reasoning modules.

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


# Storage layout
DATA_DIR        = BASE_DIR / 'data'
CHROMA_DIR      = BASE_DIR / 'chroma_data'
HF_CACHE_DIR    = BASE_DIR / 'hf_cache'
BM25_DB         = BASE_DIR / 'cjpca' / 'db.sqlite3'


# Embedding / retrieval
EMBED_MODEL          = 'BAAI/bge-small-en-v1.5'
RERANKER_MODEL       = 'cross-encoder/ms-marco-MiniLM-L-6-v2'
NLI_MODEL            = 'cross-encoder/nli-deberta-base'
CHROMA_COLLECTION    = 'regulations'
CHUNK_TOKENS         = 500
CHUNK_OVERLAP_TOKENS = 60
FUSION_TOP_K         = 20
FINAL_TOP_K          = 5


# LLM (env-overridable)
LLM_PROVIDER     = 'ollama'
LLM_MODEL        = 'llama3.2:1b'
LLM_TEMPERATURE  = 0.1
LLM_MAX_TOKENS   = 8000
LLM_RETRY_ATTEMPTS = 2
LLM_TIMEOUT_SEC  = 180
OLLAMA_BASE_URL  = 'http://localhost:11434'
'''


# ─────────────────────────── DUMPER ENTRY ─────────────────────────────────

def main() -> None:
    base = Path(__file__).resolve().parents[2]
    root = base / 'thesis_docs' / 'code_3_3_outlines'
    root.mkdir(parents=True, exist_ok=True)

    for rel_path, content in OUTLINES.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    print(f'Wrote {len(OUTLINES)} outline files under {root}')


if __name__ == '__main__':
    main()
