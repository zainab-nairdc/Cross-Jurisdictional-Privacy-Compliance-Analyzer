"""
concepts.py — Term Frequency / Semantic Overlay computation (Visual 8).

Maintains a curated CONCEPT_SEEDS dictionary of 11 privacy principles and
counts case-insensitive whole-word occurrences across document full texts.
"""
import re
import sqlite3
from pathlib import Path

# ── Concept seed dictionary ─────────────────────────────────────────────────────

CONCEPT_SEEDS: dict = {
    "data_controller": {
        "label": "data controller",
        "synonyms": [
            "data controller", "controller", "data fiduciary",
            "processor of record", "custodian",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#D1D5E0",
    },
    "consent": {
        "label": "consent",
        "synonyms": ["consent", "authorization", "permission"],
        "color_light": "#FFB800",
        "color_text":  "#002583",
        "color_dot":   "#FFB800",
    },
    "cross_border_transfer": {
        "label": "cross-border transfer",
        "synonyms": [
            "cross-border transfer", "data transfer", "international transfer",
            "transfer of data", "export of personal data",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#FFB800",
    },
    "supervisory_authority": {
        "label": "supervisory authority",
        "synonyms": [
            "supervisory authority", "data protection authority", "regulator",
            "commissioner", "supervisory body",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#002583",
    },
    "breach": {
        "label": "data breach",
        "synonyms": [
            "data breach", "personal data breach", "security breach",
            "breach notification", "incident report",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#002583",
    },
    "data_subject": {
        "label": "data subject",
        "synonyms": [
            "data subject", "individual", "person concerned",
            "natural person", "data principal",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#002583",
    },
    "processing_grounds": {
        "label": "processing grounds",
        "synonyms": [
            "lawful basis", "legal basis", "processing grounds",
            "grounds for processing", "legitimate interest",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#FFB800",
    },
    "retention": {
        "label": "retention",
        "synonyms": [
            "retention period", "storage period", "data retention",
            "retain", "deletion",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#FFB800",
    },
    "dpia": {
        "label": "DPIA",
        "synonyms": [
            "data protection impact assessment", "DPIA",
            "privacy impact assessment", "PIA", "impact assessment",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#002583",
    },
    "vendor_processor": {
        "label": "vendor / processor",
        "synonyms": [
            "data processor", "processor", "vendor", "service provider",
            "sub-processor", "third party processor",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#FFB800",
    },
    "adequacy": {
        "label": "adequacy",
        "synonyms": [
            "adequacy decision", "adequate protection", "adequacy",
            "equivalent level of protection",
        ],
        "color_light": "#E5E8EF",
        "color_text":  "#002583",
        "color_dot":   "#D1D5E0",
    },
}

MAX_CONCEPTS = 8
CHUNK_LIMIT   = 30  # max chunks fetched per document for display


# ── BM25 helpers ────────────────────────────────────────────────────────────────

def _bm25_db_path():
    try:
        from config import CHROMA_DIR
        return Path(str(CHROMA_DIR)) / "bm25.db"
    except Exception:
        return None


def _get_doc_text(doc) -> str:
    """Concatenated full text of all chunks for a Document. Looks up by
    file stem (chunk_doc_title), which matches what ingestion stored."""
    db_path = _bm25_db_path()
    if not db_path or not db_path.exists():
        return ""
    title = (
        getattr(doc, 'chunk_doc_title', '')
        or doc.full_name
        or doc.name
    )
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT content FROM bm25_index WHERE doc_title = ?", (title,)
        ).fetchall()
        conn.close()
        return " ".join(r[0] for r in rows if r[0])
    except sqlite3.OperationalError:
        return ""


def get_doc_chunks(doc, limit: int = CHUNK_LIMIT) -> list:
    """Return individual chunk texts for a Document, up to limit.

    Chunks are keyed in BM25 by ``doc_title`` = file stem (the value the
    ingestion pipeline writes), NOT by Document.name. So we have to look
    them up via ``doc.chunk_doc_title`` (Path(file.name).stem). Falling
    back to ``doc.full_name`` / ``doc.name`` when the file is missing
    keeps legacy rows working.
    """
    db_path = _bm25_db_path()
    if not db_path or not db_path.exists():
        return []
    title = (
        getattr(doc, 'chunk_doc_title', '')
        or doc.full_name
        or doc.name
    )
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT content FROM bm25_index WHERE doc_title = ? LIMIT ?",
            (title, limit),
        ).fetchall()
        conn.close()
        return [r[0] for r in rows if r[0]]
    except sqlite3.OperationalError:
        return []


def get_doc_chunks_with_ids(doc, limit: int = CHUNK_LIMIT) -> list[tuple]:
    """Same as ``get_doc_chunks`` but also returns each chunk's node_id.

    Returns list of ``(node_id, content, article_ref)`` tuples in document
    order. Used by the document viewer when we have the exact ``chunk_id`` to
    highlight — substring-matching the verbatim quote can fail for OCR space
    artifacts or when the LLM stored the chunk header instead of the body, but
    matching by ``node_id`` always works. ``article_ref`` is carried because
    the chunker strips headings out of the body, so it's the only place the
    "Article (N)" label survives.
    """
    db_path = _bm25_db_path()
    if not db_path or not db_path.exists():
        return []
    title = (
        getattr(doc, 'chunk_doc_title', '')
        or doc.full_name
        or doc.name
    )
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT node_id, content, article_ref FROM bm25_index WHERE doc_title = ? LIMIT ?",
            (title, limit),
        ).fetchall()
        conn.close()
        return [(r[0], r[1], r[2] or '') for r in rows if r[1]]
    except sqlite3.OperationalError:
        return []


# ── Concept pattern helpers ─────────────────────────────────────────────────────

def build_concept_pattern(concept_id: str) -> re.Pattern:
    """Whole-word case-insensitive OR pattern for all synonyms of a concept."""
    seed = CONCEPT_SEEDS[concept_id]
    parts = [r'\b' + re.escape(syn) + r'\b' for syn in seed["synonyms"]]
    return re.compile("|".join(parts), re.IGNORECASE)


def _count_occurrences(text: str, pattern: re.Pattern) -> int:
    return len(pattern.findall(text))


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_and_cache_doc_topics(doc, top_n: int = 5) -> list:
    """
    Compute which privacy concepts appear in a Document's full text,
    persist the result to doc.cached_topics, and return the list of concept IDs.

    Called by the ingestion pipeline after indexing so the library page can
    display topic badges without re-scanning BM25 on every page load.
    """
    text = _get_doc_text(doc)
    if not text:
        return []

    scored = []
    for concept_id in CONCEPT_SEEDS:
        pattern = build_concept_pattern(concept_id)
        count   = _count_occurrences(text, pattern)
        if count > 0:
            scored.append((concept_id, count))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = [cid for cid, _ in scored[:top_n]]

    doc.cached_topics = top
    doc.save(update_fields=["cached_topics"])
    return top


def extract_concepts(document_pks: list, top_n: int = MAX_CONCEPTS) -> list:
    """
    Return top N privacy concepts sorted by total_occurrences descending.

    document_pks: list of Document PKs; occurrences_a = first, occurrences_b = second.
    """
    from apps.library.models import Document

    docs = list(Document.objects.filter(pk__in=document_pks))
    # Preserve order matching document_pks
    pk_order = {pk: i for i, pk in enumerate(document_pks)}
    docs.sort(key=lambda d: pk_order.get(d.pk, 999))

    texts = [_get_doc_text(d) for d in docs]

    results = []
    for concept_id, seed in CONCEPT_SEEDS.items():
        pattern = build_concept_pattern(concept_id)
        counts  = [_count_occurrences(t, pattern) for t in texts]
        total   = sum(counts)
        results.append({
            "id":                concept_id,
            "label":             seed["label"],
            "color_light":       seed["color_light"],
            "color_text":        seed["color_text"],
            "color_dot":         seed["color_dot"],
            "synonyms":          seed["synonyms"],
            "total_occurrences": total,
            "occurrences_a":     counts[0] if len(counts) > 0 else 0,
            "occurrences_b":     counts[1] if len(counts) > 1 else 0,
        })

    results.sort(key=lambda c: c["total_occurrences"], reverse=True)
    return results[:top_n]
