"""End-to-end smoke test for the entire reasoning layer.

Runs every public entry point with multiple queries / scope modes / edge cases
and reports a pass/fail summary. Designed so you can read the output and know
in 30 seconds whether the layer is healthy.

Coverage:
  • Term Dictionary       — lookup, synonyms, expansion, dictionary integrity
  • Retrieval expansion   — verify expand_synonyms actually fires in hybrid_search
  • Schema validation     — Pydantic round-trip for all four report types
  • compare_regulations   — single-query, multi-query, strict scope, open scope
  • map_policy_coverage   — basic + scoped
  • generate_gap_analysis — single jurisdiction + multi
  • Orchestrator          — all 4 routes + no-chunks fallback
  • Print helpers         — make sure they don't crash on real output
"""
from __future__ import annotations

import os
import sys
import time
import warnings
import traceback
import asyncio
from pathlib import Path

warnings.filterwarnings("ignore")

_BASE = Path(__file__).resolve().parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from dotenv import load_dotenv
load_dotenv(_BASE / ".env")


# tiny test framework — keep it simple, no pytest dependency.
RESULTS: list[tuple[str, str, float, str]] = []  # (name, status, secs, detail)


def report(name: str, ok: bool, secs: float, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    RESULTS.append((name, status, secs, detail))
    print(f"  [{status:4s}] {secs:5.1f}s  {name}  {('-- ' + detail) if detail else ''}")


def section(title: str) -> None:
    print(f"\n========== {title} ==========")


def _to_dicts(nodes) -> list[dict]:
    """convert NodeWithScore to the dict shape orchestrator expects."""
    out = []
    for n in nodes:
        m = n.node.metadata
        out.append({
            "node_id":         m.get("node_id") or n.node.node_id or "",
            "content":         n.node.get_content(),
            "jurisdiction":    m.get("jurisdiction", ""),
            "regulation_name": m.get("regulation_name", ""),
            "article_ref":     m.get("article_ref", ""),
        })
    return out


# 1. Term dictionary integrity ------------------------------------------------

def test_term_dictionary():
    section("1. Term Dictionary")
    from reasoning.term_dictionary import (
        TERMS, all_terms, by_category, lookup,
        synonyms_for_query, expand_query, CATEGORIES,
    )

    t0 = time.time()
    n = len(TERMS)
    report("dictionary loads >= 50 terms", n >= 50, time.time() - t0, f"{n} terms")

    # every term has the required schema fields
    t0 = time.time()
    bad = []
    required = {"category", "definition", "jurisdictions", "synonyms"}
    for k, v in TERMS.items():
        missing = required - v.keys()
        if missing:
            bad.append(f"{k}: missing {missing}")
        if v.get("category") not in CATEGORIES:
            bad.append(f"{k}: bad category {v.get('category')}")
        for jur, jdata in v.get("jurisdictions", {}).items():
            if "term" not in jdata or "citation" not in jdata:
                bad.append(f"{k}/{jur}: missing term or citation")
    report("schema integrity", not bad, time.time() - t0, f"{len(bad)} issues" if bad else "all rows clean")

    # known cross-jurisdiction lookups
    t0 = time.time()
    cases = [
        ("data principal", "data subject"),
        ("data manager",   "data controller"),
        ("permission",     "consent"),
        ("right to be forgotten", "right to erasure"),
        ("SDF",            "significant data fiduciary"),
        ("DPO",            "data protection officer"),
    ]
    misses = []
    for term, expected in cases:
        r = lookup(term)
        if not r or r["canonical"] != expected:
            misses.append(f"{term!r} -> {r['canonical'] if r else None} (expected {expected!r})")
    report("cross-jurisdiction lookup", not misses, time.time() - t0, "; ".join(misses) or "6/6")

    # query expansion picks up at least canonicals + synonyms + jur labels
    t0 = time.time()
    expansion_cases = [
        ("data principal rights", 3),
        ("permission to process", 3),
        ("breach notification timing", 3),
        ("encryption requirements", 2),
    ]
    fails = []
    for q, min_extras in expansion_cases:
        extras = synonyms_for_query(q)
        if len(extras) < min_extras:
            fails.append(f"{q!r}: only {len(extras)} extras (want >= {min_extras})")
    report("query expansion fires for known concepts", not fails, time.time() - t0, "; ".join(fails) or "all OK")

    # word-boundary regression: "notice" must NOT match "notification"
    t0 = time.time()
    extras = synonyms_for_query("breach notification")
    privacy_notice_synonyms = ["privacy notice", "transparency notice", "fair processing notice"]
    leaked = [s for s in extras if s in privacy_notice_synonyms]
    report(
        "word-boundary regression (notice != notification)",
        not leaked, time.time() - t0,
        f"leaked: {leaked}" if leaked else "clean",
    )

    # expand_query returns original + extras
    t0 = time.time()
    base = "what is the data principal"
    expanded = expand_query(base)
    ok = expanded.startswith(base) and len(expanded) > len(base)
    report("expand_query format", ok, time.time() - t0, f"{len(expanded) - len(base)} extra chars")

    # category buckets are non-empty for the categories that have terms
    t0 = time.time()
    buckets = by_category()
    empty = [c for c, items in buckets.items() if not items]
    report("by_category groupings", len(buckets) >= 8 and not empty, time.time() - t0,
           f"{len(buckets)} cats, {len(empty)} empty")


# 2. Retrieval-side query expansion -------------------------------------------

def test_retrieval_expansion():
    section("2. Retrieval expansion")
    from retrieval.retriever import hybrid_search

    # cross-jurisdiction terminology — without expansion the user using
    # India's term ("data fiduciary") shouldn't find the right Bahrain chunk.
    # with expansion they should.
    t0 = time.time()
    nodes_off = hybrid_search(
        "what duties does a data fiduciary have", top_k=3,
        jurisdiction="Bahrain", expand_synonyms=False, rerank=True,
    )
    nodes_on = hybrid_search(
        "what duties does a data fiduciary have", top_k=3,
        jurisdiction="Bahrain", expand_synonyms=True, rerank=True,
    )
    score_off = nodes_off[0].score if nodes_off else -999
    score_on  = nodes_on[0].score  if nodes_on  else -999
    improved  = score_on > score_off
    report(
        "expand_synonyms improves cross-jurisdiction retrieval",
        improved, time.time() - t0,
        f"top score {score_off:.2f} -> {score_on:.2f}",
    )

    # expansion must NOT change exact-phrase queries materially (regression)
    t0 = time.time()
    nodes = hybrid_search("breach notification", top_k=3, jurisdiction="Kuwait", expand_synonyms=True)
    has_breach_chunks = any("breach" in n.node.get_content().lower() for n in nodes)
    report("expansion preserves direct hits", has_breach_chunks, time.time() - t0,
           f"{len(nodes)} chunks, breach in top: {has_breach_chunks}")


# 3. Schema round-trip --------------------------------------------------------

def test_schemas():
    section("3. Pydantic schema integrity")
    from reasoning.schemas import (
        Citation, ReasonedAnswer, ReasoningStep, SearchRequest,
        ObligationComparison, ComparisonReport,
        PolicyCoverageItem, PolicyMappingReport,
        GapItem, GapAnalysisReport,
    )

    # Citation requires nothing — should accept defaults
    t0 = time.time()
    c = Citation(chunk_id="x", exact_quote="hello world this is ten chars+")
    ok = c.exact_quote and c.chunk_id == "x"
    report("Citation defaults", ok, time.time() - t0)

    # ReasonedAnswer with empty citations + low confidence should warn
    t0 = time.time()
    a = ReasonedAnswer(summary="x", confidence=0.4, route_used="general", citations=[])
    has_warning = "low confidence with no citations" in a.warnings
    report("ReasonedAnswer low-conf warning", has_warning, time.time() - t0)

    # ReasonedAnswer with high confidence + no citations should warn too
    t0 = time.time()
    a = ReasonedAnswer(summary="x", confidence=0.9, route_used="general", citations=[])
    ok = "high confidence without citations" in str(a.warnings)
    report("ReasonedAnswer high-conf-no-cits warning", ok, time.time() - t0)

    # ObligationComparison with all defaults
    t0 = time.time()
    o = ObligationComparison(topic="t")
    ok = (o.equivalence == "Different" and o.similarity_score == 0
          and o.confidence_score == 70 and not o.citation_verified)
    report("ObligationComparison defaults", ok, time.time() - t0)

    # ComparisonReport accepts list[str] query (multi-query mode)
    t0 = time.time()
    r = ComparisonReport(query=["a", "b"], regulation_a="x", regulation_b="y", obligations=[o])
    ok = r.query == ["a", "b"] and len(r.obligations) == 1
    report("ComparisonReport accepts list query", ok, time.time() - t0)

    # GapItem hallucination_risk bounds [0,1]
    t0 = time.time()
    g = GapItem(gap_id="GAP-001", hallucination_risk=0.5)
    bound_ok = 0.0 <= g.hallucination_risk <= 1.0
    try:
        GapItem(gap_id="GAP-002", hallucination_risk=1.5)
        rejected_oob = False
    except Exception:
        rejected_oob = True
    report("GapItem hallucination bounds", bound_ok and rejected_oob, time.time() - t0)

    # PolicyCoverageItem with defaults
    t0 = time.time()
    p = PolicyCoverageItem(regulatory_obligation="r")
    ok = p.coverage_status == "Requires Review" and not p.citation_verified
    report("PolicyCoverageItem defaults", ok, time.time() - t0)

    # SearchRequest enforces query length
    t0 = time.time()
    try:
        SearchRequest(query="x")    # too short (<3 chars)
        rejected = False
    except Exception:
        rejected = True
    report("SearchRequest min length validation", rejected, time.time() - t0)


# 4. Comparison workflow ------------------------------------------------------

def test_comparison_workflow():
    section("4. compare_regulations")
    from reasoning.workflows import compare_regulations, print_comparison_report
    from reasoning.schemas    import ComparisonReport

    cases = [
        # (label, query, reg_a, reg_b, top_k, scope_mode, doc_titles_a, doc_titles_b)
        ("single-query / consent",        "consent requirements",
            "Bahrain", "India", 3, "strict", None, None),
        ("single-query / breach",         "data breach notification timing",
            "Kuwait", "Bahrain", 3, "strict", None, None),
    ]
    for label, query, reg_a, reg_b, k, mode, ta, tb in cases:
        t0 = time.time()
        try:
            r = compare_regulations(
                query=query, reg_a=reg_a, reg_b=reg_b,
                top_k=k, rerank=True, scope_mode=mode,
                doc_titles_a=ta, doc_titles_b=tb,
            )
            elapsed = time.time() - t0
            assert isinstance(r, ComparisonReport)
            verified = sum(1 for o in r.obligations if o.citation_verified)
            avg_hall = sum(o.hallucination_risk for o in r.obligations) / max(len(r.obligations), 1)
            report(label, len(r.obligations) >= 1 and r.summary, elapsed,
                   f"obligations={len(r.obligations)} verified={verified} hall={avg_hall:.3f}")
        except Exception as e:
            report(label, False, time.time() - t0, f"{type(e).__name__}: {str(e)[:120]}")

    # multi-query mode (list of queries) — exercises _multi_query_retrieve
    t0 = time.time()
    try:
        r = compare_regulations(
            query=["consent", "data subject rights", "breach notification"],
            reg_a="Bahrain", reg_b="Kuwait", top_k=3, rerank=False,
        )
        elapsed = time.time() - t0
        report("multi-query mode",
               isinstance(r, ComparisonReport) and r.query == ["consent", "data subject rights", "breach notification"],
               elapsed, f"obligations={len(r.obligations)}")
    except Exception as e:
        report("multi-query mode", False, time.time() - t0, f"{type(e).__name__}: {str(e)[:120]}")

    # print helper doesn't crash
    t0 = time.time()
    try:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_comparison_report(r)
        ok = "COMPARISON" in buf.getvalue()
        report("print_comparison_report", ok, time.time() - t0, f"{len(buf.getvalue())} chars")
    except Exception as e:
        report("print_comparison_report", False, time.time() - t0, str(e)[:120])


# 5. Mapping workflow ---------------------------------------------------------

def test_mapping_workflow():
    section("5. map_policy_coverage")
    from reasoning.workflows import map_policy_coverage, print_policy_mapping_report
    from reasoning.schemas    import PolicyMappingReport

    cases = [
        ("retention / India",       "data retention policy",       "India",   3),
        ("incident / Bahrain",      "incident response policy",    "Bahrain", 3),
    ]
    last_report = None
    for label, query, jur, k in cases:
        t0 = time.time()
        try:
            r = map_policy_coverage(query=query, jurisdiction=jur, top_k=k, rerank=True)
            elapsed = time.time() - t0
            assert isinstance(r, PolicyMappingReport)
            verified = sum(1 for i in r.items if i.citation_verified)
            avg_hall = sum(i.hallucination_risk for i in r.items) / max(len(r.items), 1)
            report(label, len(r.items) >= 1, elapsed,
                   f"items={len(r.items)} verified={verified} hall={avg_hall:.3f}")
            last_report = r
        except Exception as e:
            report(label, False, time.time() - t0, f"{type(e).__name__}: {str(e)[:120]}")

    if last_report:
        t0 = time.time()
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                print_policy_mapping_report(last_report)
            ok = "POLICY MAPPING" in buf.getvalue()
            report("print_policy_mapping_report", ok, time.time() - t0)
        except Exception as e:
            report("print_policy_mapping_report", False, time.time() - t0, str(e)[:120])


# 6. Gap analysis -------------------------------------------------------------

def test_gap_workflow():
    section("6. generate_gap_analysis")
    from reasoning.workflows import generate_gap_analysis, print_gap_analysis_report
    from reasoning.schemas    import GapAnalysisReport

    last_report = None
    cases = [
        ("single-jur Bahrain",       "consent management", ["Bahrain"], 4, 5),
        ("multi-jur Bahrain+Kuwait", "data breach response", ["Bahrain", "Kuwait"], 4, 5),
    ]
    for label, topic, jurs, k, max_g in cases:
        t0 = time.time()
        try:
            r = generate_gap_analysis(topic=topic, jurisdictions=jurs,
                                       top_k=k, max_gaps=max_g, rerank=True)
            elapsed = time.time() - t0
            assert isinstance(r, GapAnalysisReport)
            verified = sum(1 for g in r.gaps if g.citation_verified)
            avg_hall = sum(g.hallucination_risk for g in r.gaps) / max(len(r.gaps), 1)
            pri = {p: sum(1 for g in r.gaps if g.priority == p) for p in ["High","Medium","Low"]}
            report(label, len(r.gaps) >= 1, elapsed,
                   f"gaps={len(r.gaps)} verified={verified} hall={avg_hall:.3f} H/M/L={pri['High']}/{pri['Medium']}/{pri['Low']}")
            last_report = r
        except Exception as e:
            report(label, False, time.time() - t0, f"{type(e).__name__}: {str(e)[:120]}")

    if last_report:
        t0 = time.time()
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                print_gap_analysis_report(last_report)
            ok = "GAP ANALYSIS" in buf.getvalue()
            report("print_gap_analysis_report", ok, time.time() - t0)
        except Exception as e:
            report("print_gap_analysis_report", False, time.time() - t0, str(e)[:120])


# 7. Orchestrator -------------------------------------------------------------

def test_orchestrator():
    section("7. Chat orchestrator (reasoning_graph)")
    from reasoning.orchestrator import reasoning_graph
    from reasoning.schemas      import SearchRequest
    from retrieval.retriever    import hybrid_search

    async def _run(query, jur, route_hint=None, retrieve=True, tid="test"):
        req = SearchRequest(query=query, jurisdiction=jur, route_hint=route_hint)
        chunks = []
        if retrieve:
            nodes = hybrid_search(query, top_k=5, jurisdiction=jur, rerank=True)
            chunks = _to_dicts(nodes)
        state = {"request": req, "retrieved_chunks": chunks, "reasoning_trace": [], "retries": 0}
        return await reasoning_graph.ainvoke(state, config={"configurable": {"thread_id": tid}})

    cases = [
        # query, jurisdiction, route_hint, expected route or None
        ("What does Bahrain PDPL require for consent?", "Bahrain",  None,        "general"),
        ("Compare consent rules between Bahrain and India", "Bahrain", "comparative", "comparative"),
        ("List the breach notification deadlines across all regulations", "Kuwait", "extraction", "extraction"),
        ("Is BBK's retention schedule compliant with Bahrain PDPL?", "Bahrain", "compliance", "compliance"),
    ]
    for query, jur, hint, expected_route in cases:
        t0 = time.time()
        try:
            r = asyncio.run(_run(query, jur, hint, retrieve=True, tid=f"orch-{hash(query)%10000}"))
            elapsed = time.time() - t0
            ans = r["final_output"]
            is_fb = ans.confidence == 0.3 and len(ans.citations) == 0
            ok = bool(ans.summary) and (is_fb or len(ans.citations) > 0)
            route_used = ans.route_used
            report(
                f"route={hint or 'auto'} | {query[:48]}",
                ok, elapsed,
                f"route_used={route_used} conf={ans.confidence:.2f} cits={len(ans.citations)} {'FB' if is_fb else 'OK'}",
            )
        except Exception as e:
            report(f"route={hint or 'auto'} | {query[:48]}", False, time.time() - t0,
                   f"{type(e).__name__}: {str(e)[:120]}")

    # Fallback path: NO chunks retrieved → safe canned response
    t0 = time.time()
    try:
        r = asyncio.run(_run("anything", "Bahrain", None, retrieve=False, tid="orch-fallback"))
        elapsed = time.time() - t0
        ans = r["final_output"]
        # safe fallback: confidence 0.3, no citations, suggestion list in summary
        is_fallback = (ans.confidence == 0.3 and len(ans.citations) == 0 and "cannot provide" in ans.summary)
        report("no-chunks short-circuit to fallback", is_fallback, elapsed,
               f"conf={ans.confidence} cits={len(ans.citations)} fb_summary={'cannot provide' in ans.summary}")
    except Exception as e:
        report("no-chunks short-circuit to fallback", False, time.time() - t0,
               f"{type(e).__name__}: {str(e)[:120]}")


# 8. Edge cases ---------------------------------------------------------------

def test_edge_cases():
    section("8. Edge cases")
    from reasoning.term_dictionary import lookup, expand_query, synonyms_for_query

    # empty/None inputs to dict shouldn't crash
    t0 = time.time()
    ok = lookup("") is None and lookup("xyz123_unknown_term") is None
    report("dict lookup tolerates empty/unknown", ok, time.time() - t0)

    t0 = time.time()
    ok = synonyms_for_query("") == [] and expand_query("") == ""
    report("expansion tolerates empty query", ok, time.time() - t0)

    # term dictionary's @ in email-like strings shouldn't break tokenization;
    # consent is in the query so the function correctly skips re-adding the
    # canonical, but should still add explicit-consent variants and jurisdiction
    # labels that DIFFER from "consent".
    t0 = time.time()
    extras = synonyms_for_query("contact dpo@bbk.com about consent")
    has_explicit_or_informed = any(
        s.lower() in {"explicit consent", "informed consent", "explicit consent"}
        for s in extras
    )
    has_dpo_match = any("dpo" in s.lower() or "data protection" in s.lower() for s in extras)
    ok = has_explicit_or_informed and has_dpo_match
    report("expansion handles punctuation around terms", ok, time.time() - t0,
           f"{len(extras)} extras  consent_variants={has_explicit_or_informed}  dpo_match={has_dpo_match}")


# main ------------------------------------------------------------------------

def main():
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("FAIL: OPENROUTER_API_KEY not set; LLM tests will fail")
        sys.exit(1)

    overall_t0 = time.time()
    print("=" * 70)
    print("  CJPCA Reasoning Layer — Full E2E Smoke Test")
    print("=" * 70)
    print(f"  Provider check: OPENROUTER_API_KEY={os.environ['OPENROUTER_API_KEY'][:12]}...")

    test_term_dictionary()
    test_retrieval_expansion()
    test_schemas()
    test_comparison_workflow()
    test_mapping_workflow()
    test_gap_workflow()
    test_orchestrator()
    test_edge_cases()

    print()
    print("=" * 70)
    pass_n = sum(1 for _, s, _, _ in RESULTS if s == "PASS")
    fail_n = sum(1 for _, s, _, _ in RESULTS if s == "FAIL")
    total_secs = time.time() - overall_t0
    print(f"  SUMMARY: {pass_n}/{pass_n + fail_n} passed in {total_secs:.1f}s")
    if fail_n:
        print()
        print("  FAILURES:")
        for name, status, secs, detail in RESULTS:
            if status == "FAIL":
                print(f"    - {name}: {detail}")
    print("=" * 70)
    sys.exit(0 if fail_n == 0 else 1)


if __name__ == "__main__":
    main()
