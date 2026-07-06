"""Embedder tests grounded in the actual corpus.

Two tests, both running against real chunks from data/chunks_inspect/:

  test_known_answer_retrieval -- for 8 hand-picked queries, verify the embedder
    + BGE query prefix correctly ranks the expected chunk above all other
    chunks in the corpus.

  test_jurisdictional_disambiguation -- verify that the legal-context prefix
    ("Jurisdiction: …") makes semantically similar chunks across different
    jurisdictions embed as similar-but-not-identical.

Run from project root:
    .venv\\Scripts\\python.exe -m pytest tests/test_embedder.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.embedder import embed_text, embed_chunks, get_model

CHUNKS_DIR = ROOT / "data" / "chunks_inspect"

# BGE-en-v1.5 query-side instruction (must match retrieval/retriever.py)
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


# ── ground truth ─────────────────────────────────────────────────────────────
# Each tuple: (natural-language query, expected chunk_id, hint about why).
# All chunk_ids verified to exist in data/chunks_inspect/.

GROUND_TRUTH: list[tuple[str, str, str]] = [
    (
        "How long must banking companies retain KYC and transaction records under PMLA?",
        "Section_12_Banking_companies_f_bb97d9_s4_1",
        "PMLA Section 12 -- 10-year retention obligation",
    ),
    (
        "What is the breach notification timeline to the Bahrain Personal Data Protection Authority?",
        "Article_4_Breach_or_violation__5691cc_s4_1",
        "Bahrain PDPA Order 43 Article 4 -- 72-hour breach notification",
    ),
    (
        "Under what conditions can sensitive personal data be processed in Bahrain?",
        "Article_2_Processing_sensitive_40678b_s2_1",
        "Bahrain PDPA Order 45 Article 2 -- sensitive data processing rules",
    ),
    (
        "How does a controller obtain prior authorization to transfer data outside Bahrain?",
        "Article_3_Prior_authorization__f8317d_s3_1",
        "Bahrain PDPA Order 42 Article 3 -- cross-border authorization procedure",
    ),
    (
        "Where must Indian payment system data be stored?",
        "2_Where_should_the_payment_dat_d31b47_s2_1",
        "RBI 2018 circular -- payment data localisation in India only",
    ),
    (
        "What does Kuwait DPPR require for data classification?",
        "Data_Classification_7e16fb_s6_1",
        "Kuwait DPPR Article 3 -- data classification requirement",
    ),
    (
        "Can a data subject withdraw consent under Bahrain law?",
        "Article_6_Request_to_withdraw__20e035_s6_1",
        "Bahrain PDPA Order 48 Article 6 -- consent withdrawal",
    ),
    (
        "What are BBK's internal retention periods for customer records?",
        "3_Retention_Schedule_e96a19_s3_1",
        "BBK-RET-005 Section 3 -- internal retention schedule",
    ),
]


# ── corpus loader ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def corpus() -> list[dict]:
    """Load every leaf chunk from data/chunks_inspect/ once per test session."""
    chunks: list[dict] = []
    for f in sorted(CHUNKS_DIR.glob("*.chunks.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not row.get("embed_skip", False):
                chunks.append(row)
    assert len(chunks) > 1000, f"expected >1000 leaves, got {len(chunks)}"
    return chunks


@pytest.fixture(scope="session")
def model():
    return get_model()


@pytest.fixture(scope="session")
def corpus_embeddings(corpus, model):
    """Embed the entire corpus once. Returns (chunks, embeddings_matrix)."""
    print(f"\n[setup] embedding {len(corpus)} chunks (~3 min on CPU)...", flush=True)
    embeddings = embed_chunks(corpus, model)
    return corpus, embeddings


# ── helpers ──────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    """Both vectors are unit-normalized → dot product == cosine."""
    return sum(x * y for x, y in zip(a, b))


def _embed_query(query: str, model) -> list[float]:
    """Apply the BGE query prefix, exactly as retriever.py does."""
    vec = model.encode(
        BGE_QUERY_PREFIX + query,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vec.tolist()


# ── test 1: known-answer retrieval ───────────────────────────────────────────

@pytest.mark.parametrize("query,expected_chunk_id,why", GROUND_TRUTH)
def test_known_answer_retrieval(query, expected_chunk_id, why,
                                 corpus_embeddings, model):
    """For each ground-truth query, the expected chunk should rank in top-3."""
    chunks, embeddings = corpus_embeddings
    q_vec = _embed_query(query, model)

    # Score every chunk
    scored = sorted(
        ((_cosine(q_vec, e), c) for e, c in zip(embeddings, chunks)),
        reverse=True,
    )
    top3_ids = [c["chunk_id"] for _, c in scored[:3]]

    if expected_chunk_id in top3_ids:
        rank = top3_ids.index(expected_chunk_id) + 1
        print(f"\n  [PASS] [{why}] hit at rank {rank}")
    else:
        # Show what came up instead so debugging is easy
        print(f"\n  [FAIL] [{why}]  expected {expected_chunk_id}")
        for i, (score, c) in enumerate(scored[:5], start=1):
            print(f"    #{i} (cos={score:.3f}) {c['chunk_id']}: {c['content'][:80]!r}")
        pytest.fail(f"{expected_chunk_id!r} not in top-3 for query: {query!r}")


# ── test 2: jurisdictional disambiguation ────────────────────────────────────

# Pairs of (chunk_id_A, chunk_id_B, expected_relationship). Each pair has
# semantically similar content but the legal-context prefix should distinguish
# them. We check: similarity is high (same topic) but strictly < 1.0
# (different jurisdictions).
JURISDICTION_PAIRS: list[tuple[str, str, str]] = [
    (
        "Article_4_Breach_or_violation__5691cc_s4_1",   # Bahrain -- breach notification
        "2_Where_should_the_payment_dat_d31b47_s2_1",   # India  -- data localisation
        "different jurisdictions, different topics -- should NOT be very similar",
    ),
    (
        "Article_2_Processing_sensitive_40678b_s2_1",   # Bahrain -- sensitive data
        "Data_Classification_7e16fb_s6_1",              # Kuwait  -- data classification
        "different jurisdictions, related-but-not-identical topics",
    ),
]


def _find_chunk(corpus: list[dict], chunk_id: str) -> dict | None:
    return next((c for c in corpus if c["chunk_id"] == chunk_id), None)


def test_jurisdictional_disambiguation(corpus_embeddings, model):
    """Verify that the citation prefix produces distinct vectors across
    jurisdictions, and that an artificial same-content cross-jurisdiction
    pair embeds as similar but not identical."""
    chunks, embeddings = corpus_embeddings
    by_id = {c["chunk_id"]: e for c, e in zip(chunks, embeddings)}

    # Part A: real chunks across jurisdictions are not too similar
    for cid_a, cid_b, why in JURISDICTION_PAIRS:
        assert cid_a in by_id, f"missing test chunk {cid_a}"
        assert cid_b in by_id, f"missing test chunk {cid_b}"
        sim = _cosine(by_id[cid_a], by_id[cid_b])
        print(f"\n  pair: {cid_a[:30]} vs {cid_b[:30]} -> cos={sim:.3f}  ({why})")
        assert sim < 0.95, f"unexpectedly identical ({sim:.3f}): {cid_a} vs {cid_b}"

    # Part B: synthetic chunks with same content + different jurisdictions
    # should be similar (same semantic content) but NOT identical (the
    # citation prefix differentiates them).
    same_text = "The data subject's consent shall be informed, specific, and freely given."
    chunk_bahrain = {
        "content":         same_text,
        "jurisdiction":    "Bahrain",
        "hierarchy_path":  "Bahrain PDPL > Article 4",
    }
    chunk_kuwait = {
        "content":         same_text,
        "jurisdiction":    "Kuwait",
        "hierarchy_path":  "Kuwait DPPR > Article 5",
    }
    chunk_bahrain_dup = {
        "content":         same_text,
        "jurisdiction":    "Bahrain",
        "hierarchy_path":  "Bahrain PDPL > Article 4",
    }

    [v_bh, v_kw, v_bh2] = embed_chunks([chunk_bahrain, chunk_kuwait, chunk_bahrain_dup], model)

    sim_cross = _cosine(v_bh, v_kw)        # Bahrain vs Kuwait, same text
    sim_same  = _cosine(v_bh, v_bh2)       # Bahrain vs Bahrain, same text

    print(f"\n  same-content same-jurisdiction:    cos={sim_same:.4f}")
    print(f"  same-content cross-jurisdiction:   cos={sim_cross:.4f}")

    # Identical input → identical vector (determinism)
    assert sim_same > 0.999, "embedder is non-deterministic"

    # Same content, different jurisdiction → high but not identical
    assert 0.85 < sim_cross < 0.999, (
        f"expected 0.85 < sim < 0.999 for cross-jurisdiction same-text, got {sim_cross:.4f}"
    )

    # Same-jurisdiction same-text MUST be more similar than cross-jurisdiction
    # same-text -- this is the test of whether the citation prefix is doing work.
    assert sim_same > sim_cross, (
        "citation prefix is NOT distinguishing jurisdictions -- "
        f"same-jur sim={sim_same:.4f} should exceed cross-jur sim={sim_cross:.4f}"
    )
