# validators.py
# post-generation checks. two of them:
#
# 1. verify_grounding: every citation the llm produced must point at a
#    chunk we actually retrieved, AND the exact_quote string must appear
#    in that chunk's content. catches the most common hallucination mode
#    (made-up citations).
#
# 2. score_hallucination: a cross-encoder NLI model rates how well the
#    answer summary is entailed by the retrieved context. high entailment
#    score -> low hallucination risk.
#
# the NLI model is heavy (~700mb). we lazy-load it on first verify call
# so importing this module is cheap.

import threading

import numpy as np
from sentence_transformers import CrossEncoder

from .config  import cfg
from .schemas import ReasonedAnswer


_ce_model: CrossEncoder | None = None
_ce_model_lock = threading.Lock()


def _get_ce_model() -> CrossEncoder:
    """Thread-safe lazy singleton. Double-checked locking so the fast path
    after init is lock-free, but two concurrent first-callers don't both
    load ~700MB of NLI model weights."""
    global _ce_model
    if _ce_model is None:
        with _ce_model_lock:
            if _ce_model is None:
                _ce_model = CrossEncoder(cfg.validation.hallucination_model)
    return _ce_model


def _normalise_quote(s: str) -> str:
    """case-insensitive + whitespace-collapsed. matches workflow_helpers' rule.
    catches LLMs that quote correctly but with whitespace drift (extra spaces,
    line breaks where the chunk had none, etc.)."""
    return " ".join((s or "").lower().split())


async def verify_grounding(draft: ReasonedAnswer, chunks: list[dict]) -> tuple[bool, str]:
    """return (grounded, issues_string).
    grounded=True means every citation in the draft is verified against a
    real chunk. issues_string lists problems found (empty if grounded).

    quote-in-source check is whitespace-tolerant. cross-chunk recovery: if
    the cited chunk doesn't contain the quote, scan every retrieved chunk;
    if the quote exists in another chunk we still accept the citation as
    grounded (and the matching chunk_id is reported in the trace). same
    philosophy as workflow_helpers: a verbatim quote from a real retrieved
    chunk is the strongest possible grounding signal even if the chunk_id
    label is mis-attributed.
    """
    if not draft.citations:
        # if the call config doesn't require citations, an empty list is fine.
        # otherwise we treat zero-citations as ungrounded so correct_node can
        # try again with a stricter prompt.
        return (not cfg.validation.require_citations), (
            "no citations" if cfg.validation.require_citations else ""
        )

    # pre-normalise once so we don't rebuild for every quote check.
    # Use .get() defensively — retrieval can occasionally return chunks
    # missing node_id or content (e.g. partial DB row); a KeyError here
    # would crash the entire verify step.
    chunk_map_norm: dict[str, str] = {}
    for c in chunks:
        nid = c.get("node_id") or ""
        body = c.get("content") or ""
        if nid:
            chunk_map_norm[nid] = _normalise_quote(body)
    all_norm_corpus = " ".join(chunk_map_norm.values())
    issues: list[str] = []

    # the chunks all came from the same retrieval call so they share a
    # jurisdiction (when the request had a filter). use the first chunk's
    # jurisdiction as the canonical one for the strict-jurisdiction check.
    expected_jur = chunks[0].get("jurisdiction") if chunks else None

    for cite in draft.citations:
        # empty exact_quote is itself a problem — the verify step is what
        # forces the model to ground citations in real text. an empty quote
        # would trivially "match" anything via substring check, defeating the
        # whole point.
        quote = (cite.exact_quote or "").strip()
        if len(quote) < 10:
            issues.append(f"citation {cite.chunk_id}: exact_quote missing or too short")
            continue

        norm_quote = _normalise_quote(quote)
        src = chunk_map_norm.get(cite.chunk_id, "")
        if src and norm_quote in src:
            pass  # cited chunk contains the quote — perfect
        elif norm_quote in all_norm_corpus:
            # quote exists somewhere in the retrieved chunks but not in the
            # cited one. accept it as grounded — cross-chunk recovery. legal
            # text is heavily cross-referenced and the LLM mis-attributing a
            # quote shouldn't make us reject the citation entirely.
            pass
        else:
            issues.append(f"citation {cite.chunk_id}: exact_quote not found in source")

        if cfg.validation.jurisdiction_strict and expected_jur and cite.jurisdiction != expected_jur:
            issues.append(
                f"citation {cite.chunk_id}: jurisdiction mismatch "
                f"(cite={cite.jurisdiction}, expected={expected_jur})"
            )

    return (len(issues) == 0), "; ".join(issues)


async def score_hallucination(summary: str, chunks: list[dict], top_k: int = 5) -> float:
    """return a 0-1 risk score. 0 = fully grounded, 1 = pure hallucination.
    no chunks at all -> max risk.

    we take the MAX entailment probability across the retrieved chunks, not
    the mean. reasoning: a multi-sentence summary only needs to be entailed
    by SOME chunk to be considered grounded — averaging entailment across
    every retrieved chunk punishes the summary for chunks that simply cover
    a different aspect of the same topic. mirrors the per-row logic in
    workflow_helpers.verify_simple_citations (best-of-all-chunks).
    """
    if not chunks:
        return 1.0

    ce = _get_ce_model()
    # Defensive: skip chunks missing content (would crash with KeyError if any
    # retrieval row is malformed). An empty-content chunk has zero entailment
    # signal anyway, so dropping it is semantically correct.
    sample = [c.get("content", "") for c in chunks[:top_k] if c.get("content")]
    if not sample:
        return 1.0
    pairs = [[ctx, summary] for ctx in sample]
    raw = ce.predict(pairs)
    raw = np.array(raw)
    if raw.ndim == 1:
        # fallback for models that return a single score per pair
        best_entailment = float(np.max(raw))
    else:
        # softmax logits -> probs. entailment is index 2.
        exp = np.exp(raw - raw.max(axis=1, keepdims=True))
        probs = exp / exp.sum(axis=1, keepdims=True)
        entailment_probs = probs[:, 2]
        best_entailment = float(np.max(entailment_probs))

    return round(1.0 - best_entailment, 3)
