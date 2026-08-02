# workflows.py
# three specialised langgraph workflows that replace analyzer.py:
#
#   compare_regulations      -> ComparisonReport
#   map_policy_coverage      -> PolicyMappingReport
#   generate_gap_analysis    -> GapAnalysisReport
#
# each workflow follows the same skeleton:
#
#   prepare  -> retrieve chunks, build context blocks
#       │
#       ▼
#   draft    -> llm call, parse output into the workflow's pydantic schema
#       │
#       ▼
#   verify   -> check every citation against the chunk-citation headers,
#               auto-correct where possible
#       │
#       ▼
#   correct (loop, max_retries) ─┐
#       │                        │
#       ▼                        ▼
#   finalize                  fallback (empty report with explanation)
#
# this is the same architecture as orchestrator.py, just with three
# different schemas / prompts / verifiers per workflow. shared infrastructure
# lives in generator.py (llm builder), workflow_helpers.py (format + verify),
# prompts/ (yaml templates).

from __future__ import annotations

import logging
import re
from typing import Optional, TypedDict

from langgraph.graph             import END, StateGraph
from langchain_classic.output_parsers import OutputFixingParser
from langchain_core.output_parsers    import PydanticOutputParser

from .config           import cfg
from .generator        import _get_llm
from .prompts.registry import load_prompt
from .schemas import (
    ComparisonReport, ObligationComparison,
    PolicyMappingReport, PolicyCoverageItem, SkippedTopic,
    GapAnalysisReport,  GapItem,
)
from .workflow_helpers import (
    format_nodes,
    verify_comparison_citations,
    verify_policy_mapping_citations,
    verify_simple_citations,
)

log = logging.getLogger(__name__)


# shared draft helper
# all three workflows do the same thing in their draft step: render a
# prompt, call the llm, parse the output into a pydantic model, with
# automatic re-prompting on parse failure.

async def _draft_with_parser(prompt_text: str, response_model: type):
    """one llm call, parsed straight into the pydantic model. only re-prompts
    if the raw output fails to parse.

    Previously this did `llm.ainvoke(prompt)` AND then `parser.parse(text)`,
    where OutputFixingParser could fire its OWN llm call inside `.parse()` —
    so one "draft" was up to 2 LLM hits even on the happy path, and 4 hits
    when the with_fallbacks chain bounced to Ollama. The mapping screen
    spending 5+ minutes on a single topic was directly attributable to this
    multiplier compounding with the verify→correct loop.

    Now: one real call, parse the text directly. Only on a parse failure do
    we delegate to OutputFixingParser to re-prompt — and that path is gated
    by cfg.llm.retry_attempts so the cap is observable from config.
    """
    base_parser = PydanticOutputParser(pydantic_object=response_model)
    llm = _get_llm()
    raw = await llm.ainvoke(prompt_text)
    text = raw.content if hasattr(raw, "content") else str(raw)
    try:
        return base_parser.parse(text)
    except Exception as parse_err:
        if cfg.llm.retry_attempts <= 0:
            raise
        log.warning("draft parse failed, re-prompting once: %s", str(parse_err)[:200])
        fixing = OutputFixingParser.from_llm(
            parser      = base_parser,
            llm         = llm,
            max_retries = cfg.llm.retry_attempts,
        )
        return fixing.parse(text)


# 1. comparison workflow

class ComparisonState(TypedDict, total=False):
    query:         str | list[str]
    reg_a:         str
    reg_b:         str
    context_a:     str
    context_b:     str
    nodes_a:       list   # raw NodeWithScore list, for evidence verification
    nodes_b:       list
    draft:         Optional[ComparisonReport]
    cite_issues:   Optional[str]
    retries:       int
    final_output:  Optional[ComparisonReport]


async def _comparison_draft(state: ComparisonState) -> dict:
    prompt = load_prompt("comparison_workflow.yaml")
    text   = prompt.format(
        query           = state["query"],
        context_a       = state["context_a"],
        context_b       = state["context_b"],
        correction_hint = state.get("cite_issues") or "",
        previous_answer = state["draft"].model_dump_json() if state.get("draft") else "",
    )
    draft = await _draft_with_parser(text, ComparisonReport)
    return {"draft": draft, "retries": state.get("retries", 0)}


async def _comparison_verify(state: ComparisonState) -> dict:
    draft = state["draft"]
    obligations_dicts = [o.model_dump() for o in draft.obligations]
    verified, issues = verify_comparison_citations(
        obligations_dicts,
        state["context_a"], state["context_b"],
        nodes_a=state.get("nodes_a"), nodes_b=state.get("nodes_b"),
    )
    draft.obligations = [ObligationComparison.model_validate(o) for o in verified]
    return {
        "draft":       draft,
        "cite_issues": "; ".join(issues) if issues else None,
    }


async def _comparison_correct(state: ComparisonState) -> dict:
    if state.get("retries", 0) >= cfg.validation.max_retries:
        # max retries hit. ship what we have, but mark unverified rows as
        # such — UIs can grey them out. no fallback "empty" report here
        # because partial verification is still useful for analysts.
        return {"final_output": state["draft"]}
    state["retries"] = state.get("retries", 0) + 1
    return await _comparison_draft(state)


def _comparison_route(state: ComparisonState) -> str:
    if state.get("cite_issues") and state.get("retries", 0) < cfg.validation.max_retries:
        return "correct"
    return "finalize"


async def _comparison_finalize(state: ComparisonState) -> dict:
    return {"final_output": state["draft"]}


def _build_comparison_graph():
    g = StateGraph(ComparisonState)
    g.add_node("draft",    _comparison_draft)
    g.add_node("verify",   _comparison_verify)
    g.add_node("correct",  _comparison_correct)
    g.add_node("finalize", _comparison_finalize)

    g.set_entry_point("draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", _comparison_route,
                            {"correct": "correct", "finalize": "finalize"})
    g.add_edge("correct", "verify")
    g.add_edge("finalize", END)
    # no checkpointer: we keep raw NodeWithScore objects in state for the
    # evidence verifier, and they're not msgpack-serializable. each workflow
    # call is one-shot anyway (no resume-from-checkpoint use case), so the
    # checkpointer was dead weight that crashed the run.
    return g.compile()


comparison_graph = _build_comparison_graph()


# 2. policy mapping workflow

class MappingState(TypedDict, total=False):
    query:              str
    jurisdiction:       str
    context_regulation: str
    context_policies:   str
    nodes_regulation:   list   # raw NodeWithScore — needed for evidence + NLI checks
    nodes_policies:     list
    draft:              Optional[PolicyMappingReport]
    cite_issues:        Optional[str]
    retries:            int
    final_output:       Optional[PolicyMappingReport]


async def _mapping_draft(state: MappingState) -> dict:
    prompt = load_prompt("policy_mapping_workflow.yaml")
    text   = prompt.format(
        query              = state["query"],
        jurisdiction       = state["jurisdiction"],
        context_regulation = state["context_regulation"],
        context_policies   = state["context_policies"],
        correction_hint    = state.get("cite_issues") or "",
        previous_answer    = state["draft"].model_dump_json() if state.get("draft") else "",
    )
    draft = await _draft_with_parser(text, PolicyMappingReport)
    return {"draft": draft, "retries": state.get("retries", 0)}


async def _mapping_verify(state: MappingState) -> dict:
    draft = state["draft"]
    items_dicts = [i.model_dump() for i in draft.items]
    # mirror comparison's both-sides verification: the regulation side is
    # required (citation_verified depends on it) and the policy side is
    # checked when claimed but allowed to be empty for legitimate "Not
    # Covered" rows.
    verified, issues = verify_policy_mapping_citations(
        items_dicts,
        context_regulation = state["context_regulation"],
        context_policies   = state["context_policies"],
        nodes_regulation   = state.get("nodes_regulation"),
        nodes_policies     = state.get("nodes_policies"),
    )
    draft.items = [PolicyCoverageItem.model_validate(i) for i in verified]
    return {
        "draft":       draft,
        "cite_issues": "; ".join(issues) if issues else None,
    }


async def _mapping_correct(state: MappingState) -> dict:
    if state.get("retries", 0) >= cfg.validation.max_retries:
        return {"final_output": state["draft"]}
    state["retries"] = state.get("retries", 0) + 1
    return await _mapping_draft(state)


def _mapping_route(state: MappingState) -> str:
    if state.get("cite_issues") and state.get("retries", 0) < cfg.validation.max_retries:
        return "correct"
    return "finalize"


async def _mapping_finalize(state: MappingState) -> dict:
    return {"final_output": state["draft"]}


def _build_mapping_graph():
    g = StateGraph(MappingState)
    g.add_node("draft",    _mapping_draft)
    g.add_node("verify",   _mapping_verify)
    g.add_node("correct",  _mapping_correct)
    g.add_node("finalize", _mapping_finalize)
    g.set_entry_point("draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", _mapping_route,
                            {"correct": "correct", "finalize": "finalize"})
    g.add_edge("correct", "verify")
    g.add_edge("finalize", END)
    # no checkpointer: we keep raw NodeWithScore objects in state for the
    # evidence verifier, and they're not msgpack-serializable. each workflow
    # call is one-shot anyway (no resume-from-checkpoint use case), so the
    # checkpointer was dead weight that crashed the run.
    return g.compile()


mapping_graph = _build_mapping_graph()


# 3. gap analysis workflow

class GapState(TypedDict, total=False):
    topic:         str
    jurisdictions: list[str]
    context:       str
    nodes:         list   # raw NodeWithScore across all jurisdictions + policies
    max_gaps:      int
    draft:         Optional[GapAnalysisReport]
    cite_issues:   Optional[str]
    retries:       int
    final_output:  Optional[GapAnalysisReport]


async def _gap_draft(state: GapState) -> dict:
    prompt = load_prompt("gap_analysis_workflow.yaml")
    text   = prompt.format(
        topic           = state["topic"],
        jurisdictions   = ", ".join(state["jurisdictions"]),
        max_gaps        = state.get("max_gaps", 15),
        context         = state["context"],
        correction_hint = state.get("cite_issues") or "",
        previous_answer = state["draft"].model_dump_json() if state.get("draft") else "",
    )
    draft = await _draft_with_parser(text, GapAnalysisReport)
    return {"draft": draft, "retries": state.get("retries", 0)}


async def _gap_verify(state: GapState) -> dict:
    draft = state["draft"]
    gaps_dicts = [g.model_dump() for g in draft.gaps]
    verified, issues = verify_simple_citations(
        gaps_dicts, state["context"],
        citation_field   = "regulatory_source",
        label_field      = "gap_id",
        nodes            = state.get("nodes"),
        chunk_id_field   = "regulatory_chunk_id",
        evidence_field   = "regulatory_evidence",
        doc_title_field  = "regulatory_doc_title",
        summary_field    = "obligation_summary",
    )
    draft.gaps = [GapItem.model_validate(g) for g in verified]
    return {
        "draft":       draft,
        "cite_issues": "; ".join(issues) if issues else None,
    }


async def _gap_correct(state: GapState) -> dict:
    if state.get("retries", 0) >= cfg.validation.max_retries:
        return {"final_output": state["draft"]}
    state["retries"] = state.get("retries", 0) + 1
    return await _gap_draft(state)


def _gap_route(state: GapState) -> str:
    if state.get("cite_issues") and state.get("retries", 0) < cfg.validation.max_retries:
        return "correct"
    return "finalize"


async def _gap_finalize(state: GapState) -> dict:
    return {"final_output": state["draft"]}


def _build_gap_graph():
    g = StateGraph(GapState)
    g.add_node("draft",    _gap_draft)
    g.add_node("verify",   _gap_verify)
    g.add_node("correct",  _gap_correct)
    g.add_node("finalize", _gap_finalize)
    g.set_entry_point("draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", _gap_route,
                            {"correct": "correct", "finalize": "finalize"})
    g.add_edge("correct", "verify")
    g.add_edge("finalize", END)
    # no checkpointer: we keep raw NodeWithScore objects in state for the
    # evidence verifier, and they're not msgpack-serializable. each workflow
    # call is one-shot anyway (no resume-from-checkpoint use case), so the
    # checkpointer was dead weight that crashed the run.
    return g.compile()


gap_graph = _build_gap_graph()


# public API — same signatures analyzer.py used to expose
# the django app and tests call these. they retrieve chunks, drive the
# right graph, and return the structured report. all the magic happens
# inside the graph.

import asyncio
from retrieval.retriever import hybrid_search, search_comparative


def _run_async(coro):
    """sync wrapper around an async coroutine.

    Modern asyncio probe: get_running_loop() raises RuntimeError when no
    loop is active in this thread — the normal sync-caller case. If a loop
    IS running (e.g. called from inside an async context, or under a
    Django ASGI worker), we run the coro on a worker thread with its own
    loop because nesting asyncio.run() in a running loop would raise."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop running in this thread — the normal sync-caller case.
        return asyncio.run(coro)

    # We're inside an event loop. Spawn a worker thread.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as exe:
        return exe.submit(asyncio.run, coro).result()


def _multi_query_retrieve(
    queries: list[str], reg_a: str, reg_b: str,
    top_k_per_query: int = 2,
    doc_title_a: str | None = None, doc_title_b: str | None = None,
    topics_per_query: list[str] | None = None,
    subcategories_per_query: list[str] | None = None,
    rerank: bool = True,
) -> dict:
    """retrieve per-concept chunks and merge, preserving topic diversity.

    used when compare_regulations() is called with a list of queries (e.g.
    one query per picked topic). when ``topics_per_query`` is provided the
    function applies that topic as a taxonomy filter for the matching query —
    so each query retrieves chunks tagged with its specific topic rather than
    bleeding across topics. lists must be the same length as ``queries`` or
    are ignored (best-effort).
    """
    titles_a = [doc_title_a] if doc_title_a else None
    titles_b = [doc_title_b] if doc_title_b else None
    use_per_topic = (
        topics_per_query is not None and len(topics_per_query) == len(queries)
    )
    use_per_sub = (
        subcategories_per_query is not None
        and len(subcategories_per_query) == len(queries)
    )

    seen_a: dict[str, object] = {}
    seen_b: dict[str, object] = {}
    for i, q in enumerate(queries):
        topic = topics_per_query[i] if use_per_topic else None
        sub   = subcategories_per_query[i] if use_per_sub else None
        nodes_a = _scoped_retrieve(
            q, top_k=top_k_per_query, jurisdiction=reg_a,
            doc_titles=titles_a, scope_mode="strict", rerank=rerank,
            topic=topic, subcategory=sub,
        )
        nodes_b = _scoped_retrieve(
            q, top_k=top_k_per_query, jurisdiction=reg_b,
            doc_titles=titles_b, scope_mode="strict", rerank=rerank,
            topic=topic, subcategory=sub,
        )
        for node in nodes_a:
            nid = (node.node.metadata.get("node_id")
                   or node.node.metadata.get("chunk_id")
                   or node.node.get_content()[:60])
            seen_a.setdefault(nid, node)
        for node in nodes_b:
            nid = (node.node.metadata.get("node_id")
                   or node.node.metadata.get("chunk_id")
                   or node.node.get_content()[:60])
            seen_b.setdefault(nid, node)
    return {"regulation_a": list(seen_a.values()), "regulation_b": list(seen_b.values())}


def _multi_query_mapping_retrieve(
    queries:           list[str],
    jurisdiction:      str,
    top_k_per_query:   int = 2,
    doc_titles_reg:    list[str] | None = None,
    doc_titles_policy: list[str] | None = None,
    scope_mode:        str = "strict",
    topic:             str | None = None,
    subcategory:       str | None = None,
) -> dict:
    """retrieve per-concept chunks for both the regulation and the policy
    side, merge, and preserve topic diversity. used when map_policy_coverage
    is called with a list of queries (full coverage assessment) — mirrors
    _multi_query_retrieve but for the regulation/BBK split rather than two
    regulations."""
    seen_reg: dict[str, object] = {}
    seen_pol: dict[str, object] = {}
    for q in queries:
        reg = _scoped_retrieve(
            q, top_k=top_k_per_query, jurisdiction=jurisdiction,
            doc_titles=doc_titles_reg, scope_mode=scope_mode, rerank=False,
            topic=topic, subcategory=subcategory,
        )
        pol = _scoped_retrieve(
            q, top_k=top_k_per_query, jurisdiction="BBK",
            doc_titles=doc_titles_policy, scope_mode=scope_mode, rerank=False,
            topic=topic, subcategory=subcategory,
        )
        for node in reg:
            nid = (node.node.metadata.get("node_id")
                   or node.node.metadata.get("chunk_id")
                   or node.node.get_content()[:60])
            seen_reg.setdefault(nid, node)
        for node in pol:
            nid = (node.node.metadata.get("node_id")
                   or node.node.metadata.get("chunk_id")
                   or node.node.get_content()[:60])
            seen_pol.setdefault(nid, node)
    return {"regulation": list(seen_reg.values()), "policies": list(seen_pol.values())}


def _scoped_retrieve(
    query:        str,
    top_k:        int,
    jurisdiction: str | None = None,
    doc_titles:   list[str] | None = None,
    scope_mode:   str = "strict",
    rerank:       bool = True,
    topic:        str | None = None,
    subcategory:  str | None = None,
) -> list:
    """document-scoped retrieval with two modes:

    - strict: only returns chunks from `doc_titles`. push-down filter at the
      database layer — the llm physically cannot see anything else.
    - open:   first pass returns chunks from `doc_titles`, second pass
      returns chunks from the broader corpus (same jurisdiction). merged
      and deduplicated. selected docs come first.

    if `doc_titles` is None or empty, this just delegates to a normal
    jurisdiction-scoped search regardless of mode.

    `topic` / `subcategory` push down a taxonomy filter onto both the
    chroma metadata filter and the bm25 sidecar table. only chunks that
    have been classified into the requested tag will be returned — chunks
    that haven't been backfilled yet are invisible to a topic-scoped
    search by design (see `chunk_tags` table).
    """
    if not doc_titles:
        return hybrid_search(query, top_k=top_k, jurisdiction=jurisdiction,
                             topic=topic, subcategory=subcategory, rerank=rerank)

    primary = hybrid_search(
        query, top_k=top_k, jurisdiction=jurisdiction,
        doc_titles=doc_titles, topic=topic, subcategory=subcategory, rerank=rerank,
    )
    if scope_mode != "open":
        return primary

    # open mode: also pull from the broader corpus, dedupe by node_id.
    # taxonomy filter still applies — open scope means "wider doc set",
    # not "wider topic set".
    secondary = hybrid_search(
        query, top_k=top_k, jurisdiction=jurisdiction,
        topic=topic, subcategory=subcategory, rerank=rerank,
    )
    seen_ids = {n.node.metadata.get("node_id") for n in primary}
    extra = [n for n in secondary if n.node.metadata.get("node_id") not in seen_ids]
    return primary + extra[:top_k]


# Strips a formatted context-header echo the local model sometimes copies
# verbatim into a citation field, e.g. "[Chunk 2] (node_id=abc) CITATION: ...".
_CHUNK_HEADER_ECHO_RE = re.compile(
    r'^\s*\[chunk\s*\d+\]\s*(?:\(node_id=[^)]*\))?\s*(?:citation:|doc:|article:)?\s*',
    re.IGNORECASE,
)


def _grounded_citation(raw: str, chunk_id: str) -> tuple[str, bool]:
    """Return a display citation read from the STORED provision record, not
    echoed from model output — the same anti-fabrication rule the coverage
    flow uses. Falls back to a de-echoed version of the model's text if the
    chunk can't be found. Returns (citation, grounded)."""
    from retrieval.bm25_store import get_chunk_provision
    prov = get_chunk_provision(chunk_id) if chunk_id else None
    if prov:
        article = (prov.get("article_ref") or "").strip()
        regname = (prov.get("regulation_name") or prov.get("doc_title") or "").strip()
        if article:
            return (f"{regname} — {article}" if regname else article), True
        if regname:
            return regname, True
    cleaned = _CHUNK_HEADER_ECHO_RE.sub("", raw or "").strip()
    return cleaned, False


def _clean_comparison_citations(report: "ComparisonReport") -> "ComparisonReport":
    """Post-process every obligation so the citations shown are grounded in the
    stored provision records and free of any context-header echo. A citation
    that can't be grounded on either side downgrades citation_verified — a
    model-echoed reference must never render as verified."""
    for o in report.obligations:
        a_cit, a_ok = _grounded_citation(o.reg_a_citation, o.reg_a_chunk_id)
        b_cit, b_ok = _grounded_citation(o.reg_b_citation, o.reg_b_chunk_id)
        o.reg_a_citation = a_cit
        o.reg_b_citation = b_cit
        if not (a_ok and b_ok):
            o.citation_verified = False
    return report


def compare_regulations(
    query:       str | list[str],
    reg_a:       str,
    reg_b:       str,
    top_k:       int       = 8,
    rerank:      bool      = False,
    doc_title_a: str | None = None,
    doc_title_b: str | None = None,
    doc_titles_a: list[str] | None = None,
    doc_titles_b: list[str] | None = None,
    scope_mode:  str = "strict",
    topic:        str | None = None,
    subcategory:  str | None = None,
    topics:       list[str] | None = None,
    subcategories: list[str] | None = None,
) -> ComparisonReport:
    """compare two regulations on a topic.

    document scoping:
      - pass `doc_titles_a=[...]` / `doc_titles_b=[...]` to limit retrieval
        to specific documents on each side.
      - scope_mode='strict' (default): the llm only sees chunks from the
        selected documents on each side.
      - scope_mode='open': the llm sees the selected documents PLUS related
        chunks from the rest of that jurisdiction's corpus, labelled as
        supporting context.

    taxonomy scoping:
      - pass `topic=...` and optionally `subcategory=...` to filter chunks
        by the canonical compliance taxonomy *before* semantic search.
        only chunks classified into the requested tag are eligible — this
        prevents the LLM from comparing a Bahrain rectification clause
        against an India access clause just because they share vocabulary.
    """
    # backwards compat: if a single doc_title_a/b was passed, lift it into a list
    titles_a = doc_titles_a or ([doc_title_a] if doc_title_a else None)
    titles_b = doc_titles_b or ([doc_title_b] if doc_title_b else None)

    if isinstance(query, list):
        # multi-query path: per-concept retrieval. doesn't currently support
        # 'open' mode — the analyst-style full comparison is always strict.
        # ``topics`` / ``subcategories`` are forwarded as per-query taxonomy
        # filters so each query retrieves chunks tagged with its specific
        # topic, not a bleed across topics. ``top_k_per_query`` bumped to 3
        # so each topic contributes useful context (was 1, too narrow).
        retrieved = _multi_query_retrieve(
            query, reg_a, reg_b,
            top_k_per_query=max(top_k // max(len(query), 1), 3),
            doc_title_a=titles_a[0] if titles_a and len(titles_a) == 1 else None,
            doc_title_b=titles_b[0] if titles_b and len(titles_b) == 1 else None,
            topics_per_query=topics,
            subcategories_per_query=subcategories,
            rerank=rerank,
        )
        prompt_query = "privacy regulation full comparison"
    else:
        # single-query path: use _scoped_retrieve per side, which honours
        # both strict and open scope modes plus taxonomy filtering.
        nodes_a = _scoped_retrieve(
            query, top_k=top_k, jurisdiction=reg_a,
            doc_titles=titles_a, scope_mode=scope_mode, rerank=rerank,
            topic=topic, subcategory=subcategory,
        )
        nodes_b = _scoped_retrieve(
            query, top_k=top_k, jurisdiction=reg_b,
            doc_titles=titles_b, scope_mode=scope_mode, rerank=rerank,
            topic=topic, subcategory=subcategory,
        )
        retrieved = {"regulation_a": nodes_a, "regulation_b": nodes_b}
        prompt_query = query

    # max_chars bumped 2000 -> 6000: the 2000-char cap truncated most retrieved
    # clauses, so the LLM only ever saw ~2 obligations' worth of text and
    # produced sparse comparisons. 6000 fits comfortably in the 8192 num_ctx of
    # the qwen2.5:7b fallback and lets the model extract a fuller obligation set.
    context_a = format_nodes(retrieved["regulation_a"], f"REGULATION A — {reg_a.upper()}", max_chars=6000)
    context_b = format_nodes(retrieved["regulation_b"], f"REGULATION B — {reg_b.upper()}", max_chars=6000)

    state = {
        "query":     prompt_query,
        "reg_a":     reg_a,
        "reg_b":     reg_b,
        "context_a": context_a,
        "context_b": context_b,
        "nodes_a":   retrieved["regulation_a"],   # raw nodes for evidence + NLI
        "nodes_b":   retrieved["regulation_b"],
        "retries":   0,
    }
    result = _run_async(comparison_graph.ainvoke(state))

    report: ComparisonReport = result["final_output"]
    # stamp the original input fields onto the report (the llm doesn't
    # produce these — they're context for the caller).
    report.query        = query
    report.regulation_a = reg_a
    report.regulation_b = reg_b
    # Ground every citation in the stored provision records (strip any header
    # echo the local model copied in). Must run before the caller persists.
    _clean_comparison_citations(report)
    return report


def compare_regulations_auto(
    reg_a:        str,
    reg_b:        str,
    doc_title_a:  str,
    doc_title_b:  str,
    top_k_per_topic: int  = 8,
    rerank:       bool = True,
    max_topics:   int  = 8,
    min_chunks:   int  = 1,
    progress_cb:  callable | None = None,
) -> ComparisonReport:
    """Topic-routed comparison of two specific regulation documents.

    The generic "full scope" query retrieves a scattershot of unrelated
    articles from each side, so the local model finds few genuine A↔B pairs
    and returns a near-empty report. This routes instead: for each taxonomy
    topic BOTH documents are classified on, retrieve each side filtered to
    that topic (so the clauses actually align) and run one topic-scoped
    comparison, then merge. That produces a fuller, better-aligned obligation
    set on the local model — the same pattern map_policy_coverage_auto uses.

    Requires both documents to be classified (chunk_tags). Topics only one
    side legislates on are recorded as unique-to-A / unique-to-B in the
    summary, never fabricated into comparisons."""
    from retrieval.bm25_store import topics_for_docs
    from reasoning.taxonomy   import TAXONOMY

    norm_a = _normalise_jurisdiction(reg_a)
    norm_b = _normalise_jurisdiction(reg_b)

    topics_a = dict(topics_for_docs([doc_title_a], jurisdiction=norm_a))
    topics_b = dict(topics_for_docs([doc_title_b], jurisdiction=norm_b))

    shared = [t for t in topics_a if topics_b.get(t, 0) >= min_chunks
              and topics_a.get(t, 0) >= min_chunks]
    shared.sort(key=lambda t: topics_a[t] + topics_b[t], reverse=True)
    shared = shared[:max_topics]

    only_a = sorted(set(topics_a) - set(topics_b))
    only_b = sorted(set(topics_b) - set(topics_a))

    if not shared:
        # No shared classified topics — fall back to the single generic pass
        # so the caller still gets whatever the model can pair.
        log.warning("compare_regulations_auto: no shared topics for %s vs %s; "
                    "falling back to generic comparison", doc_title_a, doc_title_b)
        return compare_regulations(
            query="general privacy compliance obligations",
            reg_a=reg_a, reg_b=reg_b,
            doc_title_a=doc_title_a, doc_title_b=doc_title_b,
            top_k=top_k_per_topic, rerank=rerank, scope_mode="strict",
        )

    all_obligations = []
    summaries       = []
    total = len(shared)
    for idx, topic_tag in enumerate(shared, 1):
        label = TAXONOMY.get(topic_tag, {}).get("label", topic_tag)
        if progress_cb is not None:
            try:
                progress_cb(idx, total, label)
            except Exception:
                pass
        try:
            sub = compare_regulations(
                query=label, reg_a=reg_a, reg_b=reg_b,
                doc_title_a=doc_title_a, doc_title_b=doc_title_b,
                top_k=top_k_per_topic, rerank=rerank, scope_mode="strict",
                topic=topic_tag,
            )
        except Exception as e:
            log.warning("topic-routed comparison failed for %s: %s", topic_tag, e)
            continue
        for o in sub.obligations:
            if not (o.topic or "").strip():
                o.topic = label
        all_obligations.extend(sub.obligations)
        summaries.append(f"[{label}] {sub.summary}".strip())

    if only_a:
        summaries.append("Topics only " + reg_a + " legislates on (not compared): "
                         + ", ".join(TAXONOMY.get(t, {}).get("label", t) for t in only_a) + ".")
    if only_b:
        summaries.append("Topics only " + reg_b + " legislates on (not compared): "
                         + ", ".join(TAXONOMY.get(t, {}).get("label", t) for t in only_b) + ".")

    report = ComparisonReport(
        obligations  = all_obligations,
        summary      = "\n\n".join(summaries),
        query        = [TAXONOMY.get(t, {}).get("label", t) for t in shared],
        regulation_a = reg_a,
        regulation_b = reg_b,
    )
    return report


def map_policy_coverage(
    query:             str | list[str],
    jurisdiction:      str,
    top_k:             int  = 7,
    rerank:            bool = True,
    doc_titles_reg:    list[str] | None = None,
    doc_titles_policy: list[str] | None = None,
    scope_mode:        str = "strict",
    topic:             str | None = None,
    subcategory:       str | None = None,
) -> PolicyMappingReport:
    """map regulatory obligations to internal policies.

    document scoping:
      - doc_titles_reg=[...]    → limit which regulations are considered
      - doc_titles_policy=[...] → limit which internal policies are considered
      - scope_mode='strict' (default): only the selected docs feed the llm
      - scope_mode='open': selected docs PLUS related chunks from the rest
        of the corpus on that side

    taxonomy scoping (parity with compare_regulations):
      - pass `topic=...` and optionally `subcategory=...` to filter chunks
        by the canonical compliance taxonomy *before* semantic search. only
        chunks classified into the requested tag are eligible — this stops
        the llm from pretending a Bahrain consent clause covers an India
        cross-border-transfer obligation just because they share vocabulary.

    multi-query mode (parity with compare_regulations):
      - pass `query=[...]` (list of strings) to assess coverage across many
        obligations at once. each query retrieves a small slice and the
        results are merged, preserving topic diversity. useful for full
        coverage assessments rather than single-topic questions.
    """
    if isinstance(query, list):
        per_q = max(1, top_k // max(len(query), 1))
        retrieved = _multi_query_mapping_retrieve(
            query, jurisdiction,
            top_k_per_query   = per_q,
            doc_titles_reg    = doc_titles_reg,
            doc_titles_policy = doc_titles_policy,
            scope_mode        = scope_mode,
            topic             = topic,
            subcategory       = subcategory,
        )
        reg_nodes    = retrieved["regulation"]
        policy_nodes = retrieved["policies"]
        # mirror compare_regulations: use a generic prompt query for the
        # multi-topic case. the per-topic content arrives via the chunks.
        prompt_query = "policy coverage full assessment"
    else:
        reg_nodes = _scoped_retrieve(
            query, top_k=top_k, jurisdiction=jurisdiction,
            doc_titles=doc_titles_reg, scope_mode=scope_mode, rerank=rerank,
            topic=topic, subcategory=subcategory,
        )
        policy_nodes = _scoped_retrieve(
            query, top_k=top_k, jurisdiction="BBK",
            doc_titles=doc_titles_policy, scope_mode=scope_mode, rerank=False,
            topic=topic, subcategory=subcategory,
        )
        prompt_query = query

    context_regulation = format_nodes(reg_nodes, f"REGULATORY CLAUSES — {jurisdiction.upper()}", max_chars=3500)
    context_policies   = (
        format_nodes(policy_nodes, "INTERNAL POLICIES", max_chars=3500)
        if policy_nodes
        else "=== INTERNAL POLICIES ===\n(No matching sections retrieved.)\n"
    )

    state = {
        "query":              prompt_query,
        "jurisdiction":       jurisdiction,
        "context_regulation": context_regulation,
        "context_policies":   context_policies,
        "nodes_regulation":   reg_nodes,
        "nodes_policies":     policy_nodes,
        "retries":            0,
    }
    result = _run_async(mapping_graph.ainvoke(state))

    report: PolicyMappingReport = result["final_output"]
    # stamp the original input on the report so callers see what they asked
    # for, even when prompt_query was a generic placeholder.
    report.query        = query
    report.jurisdiction = jurisdiction
    return report


# policy-driven topic-routed mapping
# the methodological story: instead of asking the user "which topic do you
# want to map?", we let the policy itself answer that question. read the
# topics already classified onto the policy's chunks; for each topic the
# policy actually covers, run a topic-scoped mapping pass; merge the results.
# this stops the system from forcing false "Not Covered" verdicts on
# obligations the policy was never trying to address (e.g. mapping a
# retention policy against breach-notification clauses).

# how to normalise a jurisdiction string for the chroma/bm25 sidecar
# lookups. ingestion stores BBK as 'Bbk' (titlecase via _normalise_jurs),
# so callers passing 'BBK' / 'bbk' need to be coerced to that exact spelling
# or the sidecar joins return zero rows.
def _normalise_jurisdiction(j: str) -> str:
    from retrieval.retriever import JURISDICTION_NORM
    return JURISDICTION_NORM.get((j or "").lower(), j)


def _classify_policy_chunks_on_demand(
    doc_titles_policy: list[str],
    jurisdiction:      str = "Bbk",
) -> int:
    """run the chunk classifier on any policy chunks that don't yet have a
    chunk_tags row, write tags to both the bm25 sidecar and chroma metadata.
    idempotent: chunks already tagged are skipped. returns the number of
    chunks newly tagged.

    used by map_policy_coverage_auto so a policy can be routed at first use
    without requiring the operator to run `manage.py classify_chunks` ahead
    of time. policies are small enough (a few dozen chunks each) that the
    one-time classification cost is acceptable inline."""
    from retrieval.bm25_store    import untagged_chunks_for_docs, upsert_chunk_tags
    from reasoning.classifier    import classify_chunk
    from reasoning               import taxonomy

    untagged = untagged_chunks_for_docs(doc_titles_policy, jurisdiction=jurisdiction)
    if not untagged:
        return 0

    # write to chroma using the same singleton chroma collection the retriever
    # owns. opening a second persistent client on Windows can hit file locks,
    # so reuse the existing one rather than creating a fresh client.
    from retrieval.retriever import _get_service
    svc = _get_service()
    col = svc._index._vector_store.client   # llama-index's ChromaVectorStore exposes the raw collection as `client`

    written = 0
    for row in untagged:
        tag = classify_chunk(
            chunk_text   = row["content"] or "",
            doc_title    = row["doc_title"] or "",
            jurisdiction = row["jurisdiction"] or "",
        )
        upsert_chunk_tags([{
            "node_id":     row["node_id"],
            "topic":       tag.topic,
            "subcategory": tag.subcategory,
            "confidence":  tag.confidence,
        }])
        written += 1
        # only push categorised tags to chroma — UNCLASSIFIED is implicit
        # (no metadata key = not classified), and pushing it would just
        # bloat the index.
        if tag.topic != taxonomy.UNCLASSIFIED:
            try:
                col.update(
                    ids=[row["node_id"]],
                    metadatas=[{"topic": tag.topic, "subcategory": tag.subcategory}],
                )
            except Exception:
                # individual update failure (e.g. id missing from chroma) is
                # not fatal — the bm25 sidecar already has the tag.
                continue

    log.info("classified %d previously-untagged policy chunks for %s",
             written, doc_titles_policy)
    return written


def map_policy_coverage_auto(
    doc_titles_policy: list[str],
    jurisdiction:      str,
    top_k_per_topic:   int  = 6,
    rerank:            bool = True,
    min_chunks:        int  = 1,
    max_topics:        int  = 8,
    auto_classify:     bool = True,
    progress_cb:       callable | None = None,
    doc_titles_reg:    list[str] | None = None,
) -> PolicyMappingReport:
    """policy-driven, topic-routed coverage mapping.

    instead of asking 'how does my retention policy cover the topic the
    caller picked?', this asks 'what topics does my retention policy cover,
    and how does each of those map to {jurisdiction}?'. the policy's own
    classification scopes the retrieval — irrelevant regulation chunks
    (consent, breach notification, etc.) are never even considered when the
    policy is about retention.

    pipeline:
      1. enumerate distinct topics on chunks from `doc_titles_policy`
         (read from the chunk_tags sidecar — written by the classifier at
         ingest time or by the on-demand backfill below)
      2. if no topics exist yet for these docs and `auto_classify=True`,
         run the classifier on the policy's chunks now
      3. for each topic with at least `min_chunks` chunks, dispatch a
         topic-scoped `map_policy_coverage` pass (topic filter pushes down
         to retrieval on BOTH the regulation and the policy side)
      4. concatenate the per-topic items into one PolicyMappingReport,
         keep per-topic summaries in the report's summary field

    parameters:
      doc_titles_policy : the BBK policies to assess (must be doc_title
                          values that exist in the bm25 index)
      jurisdiction      : the regulation jurisdiction to map against
      top_k_per_topic   : retrieval depth per topic on each side
      min_chunks        : skip topics covered by fewer than this many
                          policy chunks (avoids dispatching mapping passes
                          on noise from a single misclassified chunk)
      max_topics        : safety cap on the number of LLM calls. takes the
                          top-N most-represented topics in the policy.
      auto_classify     : run the classifier on the fly if the policy
                          doesn't have chunk_tags rows yet. set False to
                          require an explicit manage.py classify_chunks
                          backfill instead.
    """
    from retrieval.bm25_store import topics_for_docs, topics_for_jurisdiction
    from reasoning.taxonomy   import TAXONOMY

    norm_jurisdiction_bbk = _normalise_jurisdiction("BBK")
    norm_jurisdiction_reg = _normalise_jurisdiction(jurisdiction)

    topics = topics_for_docs(doc_titles_policy, jurisdiction=norm_jurisdiction_bbk)

    if not topics and auto_classify:
        n = _classify_policy_chunks_on_demand(
            doc_titles_policy, jurisdiction=norm_jurisdiction_bbk,
        )
        if n:
            topics = topics_for_docs(doc_titles_policy, jurisdiction=norm_jurisdiction_bbk)

    # pre-flight: drop topics the target regulation has zero classified
    # chunks for. When the caller scoped to specific doc_titles_reg, only
    # those documents' tags count — otherwise we end up enumerating topics
    # that exist somewhere in the jurisdiction but NOT in the selected reg,
    # and every LLM call retrieves chunks from siblings the user did not
    # pick. (Previously this used topics_for_jurisdiction, which is why
    # picking "Order 42" produced obligations citing Order 43 / CBB.)
    if doc_titles_reg:
        reg_topics = topics_for_docs(doc_titles_reg, jurisdiction=norm_jurisdiction_reg)
        reg_topics = dict(reg_topics)
    else:
        reg_topics = topics_for_jurisdiction(norm_jurisdiction_reg)
    skipped: list[tuple[str, int]] = []
    eligible: list[tuple[str, int]] = []
    for t, c in topics:
        if reg_topics.get(t, 0) > 0:
            eligible.append((t, c))
        else:
            skipped.append((t, c))

    # filter and cap. min_chunks guards against routing on a single noisy
    # classification; max_topics caps the LLM cost so a policy that touches
    # everything doesn't run forever.
    topics = [(t, c) for t, c in eligible if c >= min_chunks][:max_topics]

    if not topics:
        # nothing to route — fall back to a single un-scoped mapping pass so
        # the caller still gets a usable report rather than an empty shell.
        log.warning("no classified topics found for %s; falling back to "
                    "un-routed map_policy_coverage", doc_titles_policy)
        fallback = map_policy_coverage(
            query             = "general policy coverage",
            jurisdiction      = jurisdiction,
            top_k             = top_k_per_topic,
            rerank            = rerank,
            doc_titles_reg    = doc_titles_reg,
            doc_titles_policy = doc_titles_policy,
        )
        return fallback

    # 3) per-topic mapping pass
    all_items   = []
    summaries   = []
    topics_used = []
    total_topics = len(topics)
    for topic_idx, (topic_tag, chunk_count) in enumerate(topics, start=1):
        label = TAXONOMY.get(topic_tag, {}).get("label", topic_tag)
        # Heartbeat so the UI shows which topic is in flight instead of
        # sitting on "0/1 — Mapping against <reg>" for the entire wall time.
        if progress_cb is not None:
            try:
                progress_cb(topic_idx, total_topics, label)
            except Exception:
                pass
        try:
            sub = map_policy_coverage(
                query             = label,
                jurisdiction      = jurisdiction,
                top_k             = top_k_per_topic,
                rerank            = rerank,
                doc_titles_reg    = doc_titles_reg,
                doc_titles_policy = doc_titles_policy,
                topic             = topic_tag,
            )
        except Exception as e:
            # one bad topic shouldn't kill the whole report — log and continue.
            log.warning("auto-routed mapping failed for topic %s: %s", topic_tag, e)
            continue
        # Stamp the routing topic onto every item so the coverage rollup can
        # attribute each obligation to its topic without re-deriving.
        for _it in sub.items:
            _it.topic = topic_tag
        all_items.extend(sub.items)
        summaries.append(f"[{label}] ({chunk_count} policy chunks) {sub.summary}".strip())
        topics_used.append(label)

    # prepend a one-line note about topics the policy covers but the target
    # jurisdiction does not. this is the audit-trail line the analyst needs
    # to see — "your retention policy was not mapped against Bahrain because
    # Bahrain has no retention-tagged clauses in the indexed corpus."
    if skipped:
        skipped_labels = [TAXONOMY.get(t, {}).get("label", t) for t, _ in skipped]
        scope_label = (
            f"the selected regulation{'s' if doc_titles_reg and len(doc_titles_reg) != 1 else ''}"
            if doc_titles_reg else f"{jurisdiction}'s classified corpus"
        )
        skipped_note = (
            f"Topics covered by the policy but absent from {scope_label} "
            f"(skipped, not mapped): {', '.join(skipped_labels)}."
        )
        summaries.insert(0, skipped_note)

    skipped_structured = [
        SkippedTopic(
            topic=t,
            label=TAXONOMY.get(t, {}).get("label", t),
            policy_chunks=c,
        )
        for t, c in skipped
    ]

    return PolicyMappingReport(
        items        = all_items,
        summary      = "\n\n".join(summaries),
        # query carries the human-readable topic labels — the report shows
        # the caller what the policy was actually mapped against, which is
        # the methodological point of this entry point.
        query        = topics_used,
        jurisdiction = jurisdiction,
        skipped_topics = skipped_structured,
    )


def generate_gap_analysis(
    topic:             str,
    jurisdictions:     list[str],
    top_k:             int  = 6,
    rerank:            bool = True,
    max_gaps:          int  = 15,
    doc_titles_reg:    list[str] | None = None,
    doc_titles_policy: list[str] | None = None,
    scope_mode:        str = "strict",
) -> GapAnalysisReport:
    """structured gap analysis across one or more jurisdictions.

    document scoping:
      - doc_titles_reg=[...]    → limit which regulations are scanned (across
                                  ALL listed jurisdictions). leave None to
                                  scan everything in those jurisdictions.
      - doc_titles_policy=[...] → limit which internal policies are scanned.
      - scope_mode='strict' (default): only the selected docs feed the llm
      - scope_mode='open': selected docs PLUS broader corpus
    """
    policy_nodes = _scoped_retrieve(
        topic, top_k=top_k, jurisdiction="BBK",
        doc_titles=doc_titles_policy, scope_mode=scope_mode, rerank=False,
    )
    policy_context = (
        format_nodes(policy_nodes, "INTERNAL POLICIES", max_chars=3500)
        if policy_nodes
        else "=== INTERNAL POLICIES ===\n(No matching sections retrieved.)\n"
    )

    all_nodes = list(policy_nodes)   # accumulate all nodes for the verifier
    blocks = []
    for jur in jurisdictions:
        reg_nodes = _scoped_retrieve(
            topic, top_k=top_k, jurisdiction=jur,
            doc_titles=doc_titles_reg, scope_mode=scope_mode, rerank=rerank,
        )
        if reg_nodes:
            all_nodes.extend(reg_nodes)
            blocks.append(format_nodes(reg_nodes, f"REGULATIONS — {jur.upper()}", max_chars=3000))
    blocks.append(policy_context)

    state = {
        "topic":         topic,
        "jurisdictions": list(jurisdictions),
        "max_gaps":      max_gaps,
        "context":       "\n\n".join(blocks),
        "nodes":         all_nodes,    # all retrieved nodes (regs + policies) for the verifier
        "retries":       0,
    }
    result = _run_async(gap_graph.ainvoke(state))

    report: GapAnalysisReport = result["final_output"]
    report.topic         = topic
    report.jurisdictions = list(jurisdictions)
    return report


# pretty printers (kept for cli / debug parity with analyzer.py)

def print_comparison_report(r: ComparisonReport) -> None:
    print(f"COMPARISON: {r.query}")
    print(f"Reg A: {r.regulation_a}  |  Reg B: {r.regulation_b}")
    for i, o in enumerate(r.obligations, 1):
        print(f"\n[{i}] {o.topic}  ->  {o.equivalence}")
        print(f"    A ({o.reg_a_citation}): {o.reg_a_requirement}")
        print(f"    B ({o.reg_b_citation}): {o.reg_b_requirement}")
        if o.key_difference:
            print(f"    Difference: {o.key_difference}")
    print(f"\nSUMMARY: {r.summary}")
    print(f"\n{r.disclaimer}")


def print_policy_mapping_report(r: PolicyMappingReport) -> None:
    icons = {"Covered": "[OK]", "Fully Covered": "[OK]", "Partially Covered": "[PARTIAL]",
             "Requires Review": "[REVIEW]", "Not Covered": "[GAP]"}
    query_display = "; ".join(r.query) if isinstance(r.query, list) else r.query
    print(f"POLICY MAPPING: {query_display}  |  {r.jurisdiction.upper()}")
    for i, item in enumerate(r.items, 1):
        print(f"\n[{i}] {item.regulatory_obligation}")
        print(f"    {icons.get(item.coverage_status,'[?]')} {item.coverage_status}")
        print(f"    Regulation: {item.regulation_citation}")
        print(f"    Policy:     {item.policy_section}")
        if item.gap_description:
            print(f"    Gap:        {item.gap_description}")
        if item.remediation_suggestion:
            print(f"    Fix:        {item.remediation_suggestion}")
    print(f"\nSUMMARY: {r.summary}")
    print(f"\n{r.disclaimer}")


def print_gap_analysis_report(r: GapAnalysisReport) -> None:
    pri = {"High": "[!!!]", "Medium": "[!!]", "Low": "[!]"}
    counts = {p: sum(1 for g in r.gaps if g.priority == p) for p in ["High","Medium","Low"]}
    print(f"GAP ANALYSIS: {r.topic}")
    print(f"Jurisdictions: {', '.join(r.jurisdictions)}")
    print(f"Gaps: {len(r.gaps)}  (H:{counts['High']} M:{counts['Medium']} L:{counts['Low']})")
    for g in r.gaps:
        print(f"\n{g.gap_id}  {pri.get(g.priority,'[?]')} {g.priority}  |  {g.jurisdiction}")
        print(f"    Source:      {g.regulatory_source}")
        print(f"    Obligation:  {g.obligation_summary}")
        print(f"    Policy:      {g.internal_policy_reference}")
        print(f"    Status:      {g.coverage_status}")
        print(f"    Gap:         {g.gap_description}")
        print(f"    Remediation: {g.remediation_suggestion}")
    print(f"\nSUMMARY: {r.summary}")
    print(f"\n{r.disclaimer}")
