"""eval harness for the langgraph reasoning pipeline.

drives a known set of queries through:
    retrieval -> reasoning_graph (route -> draft -> verify -> correct -> finalize)

what it measures (per-query):
    - which route was chosen
    - did the draft pass verification on the first try?
    - did the correction loop trigger? how many retries?
    - did the pipeline fall back to safe_fallback_response?
    - hallucination risk (0=grounded, 1=pure hallucination)
    - final confidence
    - did the expected chunk show up in the citations?
    - wall-clock latency

aggregate stats:
    - % grounded on first try
    - % triggered correction
    - % fell back
    - average confidence + hallucination risk
    - % of citations matching expected chunks (the retrieval eval's ground truth)
    - p50 / p95 latency (warm)

run from project root:
    .venv\\Scripts\\python.exe -X utf8 -m tests.eval_reasoning
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reasoning.orchestrator import reasoning_graph
from reasoning.schemas      import SearchRequest
from retrieval.retriever    import hybrid_search


# the 8 hand-picked queries from tests/eval_retrievers.py — same ground
# truth so we can compare reasoning quality against retrieval quality on
# the same questions.
GROUND_TRUTH: list[tuple[str, str | None, str, str]] = [
    # (query, jurisdiction filter, expected chunk_id, why)
    (
        "How long must banking companies retain KYC and transaction records under PMLA?",
        "india",
        "Section_12_Banking_companies_f_bb97d9_s4_1",
        "PMLA Section 12 -- 10-year retention",
    ),
    (
        "What is the breach notification timeline to the Bahrain Personal Data Protection Authority?",
        "bahrain",
        "Article_4_Breach_or_violation__5691cc_s4_1",
        "Bahrain PDPA Order 43 Article 4 -- 72-hour breach notification",
    ),
    (
        "Under what conditions can sensitive personal data be processed in Bahrain?",
        "bahrain",
        "Article_2_Processing_sensitive_40678b_s2_1",
        "Bahrain PDPA Order 45 Article 2 -- sensitive data processing",
    ),
    (
        "How does a controller obtain prior authorization to transfer data outside Bahrain?",
        "bahrain",
        "Article_3_Prior_authorization__f8317d_s3_1",
        "Bahrain PDPA Order 42 Article 3 -- cross-border authorization",
    ),
    (
        "Where must Indian payment system data be stored?",
        "india",
        "2_Where_should_the_payment_dat_d31b47_s2_1",
        "RBI 2018 circular -- payment data localisation",
    ),
    (
        "What does Kuwait DPPR require for data classification?",
        "kuwait",
        "Data_Classification_7e16fb_s6_1",
        "Kuwait DPPR Article 3 -- data classification requirement",
    ),
    (
        "Can a data subject withdraw consent under Bahrain law?",
        "bahrain",
        "Article_6_Request_to_withdraw__20e035_s6_1",
        "Bahrain PDPA Order 48 Article 6 -- consent withdrawal",
    ),
    (
        "What are BBK's internal retention periods for customer records?",
        "bbk",
        "3_Retention_Schedule_e96a19_s3_1",
        "BBK-RET-005 Section 3 -- internal retention schedule",
    ),
]


def _build_chunk_to_node_map() -> dict[str, str]:
    """{chunk_id: node_id} for resolving expected chunks to their stored ids."""
    mapping: dict[str, str] = {}
    chunks_dir = ROOT / "data" / "chunks_inspect"
    for f in chunks_dir.glob("*.chunks.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            cid = row.get("chunk_id")
            nid = row.get("node_id")
            if cid and nid:
                mapping[cid] = nid
    return mapping


def _chunks_from_nodes(nodes) -> list[dict]:
    """flatten llamaindex NodeWithScore -> the dict shape the reasoning
    pipeline expects."""
    out = []
    for n in nodes:
        md = n.node.metadata
        out.append({
            "node_id":         md.get("node_id", n.node.node_id or ""),
            "chunk_id":        md.get("chunk_id", ""),
            "content":         n.node.get_content(),
            "jurisdiction":    md.get("jurisdiction", ""),
            "regulation_name": md.get("regulation_name", ""),
            "article_ref":     md.get("article_ref", ""),
            "doc_title":       md.get("doc_title", ""),
        })
    return out


async def _run_one(idx: int, total: int, query: str, jurisdiction: str | None,
                   expected_node_id: str) -> dict:
    """drive one query through retrieval + reasoning, return a result dict."""
    print(f"\n  [{idx}/{total}] {query[:60]}...", flush=True)

    t_total = time.time()

    # 1. retrieve top-5 chunks
    t0 = time.time()
    nodes  = hybrid_search(query, top_k=5, jurisdiction=jurisdiction)
    chunks = _chunks_from_nodes(nodes)
    retrieve_dt = time.time() - t0

    # was the expected chunk in the retrieved set? (sanity check — if not,
    # reasoning can't possibly cite it correctly)
    retrieved_ids   = {c["node_id"] for c in chunks}
    expected_in_set = expected_node_id in retrieved_ids

    # 2. drive the reasoning graph
    t0 = time.time()
    state = {
        "request":          SearchRequest(query=query, jurisdiction=jurisdiction),
        "retrieved_chunks": chunks,
        "reasoning_trace":  [],
        "retries":          0,
    }
    try:
        result = await reasoning_graph.ainvoke(
            state,
            config={"configurable": {"thread_id": f"eval-{idx}-{int(time.time())}"}},
        )
        reason_dt = time.time() - t0
        final     = result["final_output"]
        route     = result.get("route", "?")
        retries   = result.get("retries", 0)
        h_risk    = result.get("hallucination_risk", None)
        v_score   = result.get("verification_score", None)
        cited_ids = {c.chunk_id for c in final.citations}
        expected_in_citations = expected_node_id in cited_ids
        fell_back = "fallback" in [s.action for s in final.reasoning_trace] or v_score == 0.0 and retries >= 2
        error     = result.get("error")
    except Exception as e:
        reason_dt = time.time() - t0
        final     = None
        route     = "?"
        retries   = 0
        h_risk    = None
        v_score   = None
        cited_ids = set()
        expected_in_citations = False
        fell_back = True
        error     = f"{type(e).__name__}: {e}"

    out = {
        "idx":                   idx,
        "query":                 query,
        "jurisdiction":          jurisdiction,
        "route":                 route,
        "retries":               retries,
        "fell_back":             fell_back,
        "error":                 error,
        "expected_in_set":       expected_in_set,
        "expected_in_citations": expected_in_citations,
        "n_citations":           len(cited_ids),
        "hallucination_risk":    h_risk,
        "verification_score":    v_score,
        "confidence":            final.confidence if final else 0.0,
        "summary":               final.summary[:200] if final else "(failed)",
        "retrieve_ms":           round(retrieve_dt * 1000),
        "reasoning_ms":          round(reason_dt * 1000),
        "total_ms":              round((time.time() - t_total) * 1000),
    }

    # one-line per-query summary so we can watch progress
    flag = "OK"
    if error:
        flag = "ERR"
    elif fell_back:
        flag = "FALLBACK"
    elif retries > 0:
        flag = f"CORRECTED({retries})"
    print(f"      [{flag:14}] route={route:11} conf={out['confidence']:.2f} "
          f"hall={(h_risk or 0):.2f} cites={len(cited_ids)} "
          f"({out['reasoning_ms']/1000:.1f}s)", flush=True)

    return out


def _summarise(results: list[dict]) -> None:
    n = len(results)
    if n == 0:
        print("no results")
        return

    n_ok        = sum(1 for r in results if not r["error"] and not r["fell_back"])
    n_fallback  = sum(1 for r in results if r["fell_back"])
    n_corrected = sum(1 for r in results if r["retries"] > 0 and not r["fell_back"])
    n_error     = sum(1 for r in results if r["error"])
    n_expected_retrieved = sum(1 for r in results if r["expected_in_set"])
    n_expected_cited     = sum(1 for r in results if r["expected_in_citations"])

    confidences = [r["confidence"] for r in results if r["confidence"]]
    h_risks     = [r["hallucination_risk"] for r in results if r["hallucination_risk"] is not None]
    latencies   = sorted(r["total_ms"] for r in results)

    avg_conf = sum(confidences) / len(confidences) if confidences else 0
    avg_hall = sum(h_risks)     / len(h_risks)     if h_risks     else 0
    p50      = latencies[len(latencies) // 2]                     if latencies else 0
    p95      = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0

    print()
    print("=" * 78)
    print("  REASONING EVAL — SUMMARY")
    print("=" * 78)
    print(f"  total queries          : {n}")
    print(f"  passed verify 1st-try  : {n_ok} ({100 * n_ok / n:.0f}%)")
    print(f"  needed correction      : {n_corrected}")
    print(f"  fell back              : {n_fallback}")
    print(f"  hard errors            : {n_error}")
    print()
    print(f"  expected chunk retrieved : {n_expected_retrieved} / {n} ({100 * n_expected_retrieved / n:.0f}%)")
    print(f"  expected chunk CITED     : {n_expected_cited} / {n} ({100 * n_expected_cited / n:.0f}%)")
    print()
    print(f"  avg confidence         : {avg_conf:.2f}")
    print(f"  avg hallucination risk : {avg_hall:.2f}  (lower = better)")
    print(f"  p50 latency            : {p50/1000:.1f}s")
    print(f"  p95 latency            : {p95/1000:.1f}s")


async def main() -> None:
    print("=" * 78)
    print("  REASONING EVAL (langgraph pipeline over 8 hand-picked queries)")
    print("=" * 78)

    print("\n  resolving expected chunk_ids -> node_ids...", flush=True)
    chunk_to_node = _build_chunk_to_node_map()

    # no warmup. the first real query pays the cold-start cost (loading
    # ollama model + nli model into memory) and we just include it in the
    # eval — the remaining seven queries give us warm-state numbers.

    print("\n  running eval queries:", flush=True)
    results = []
    for i, (query, jur, chunk_id, _why) in enumerate(GROUND_TRUTH, 1):
        nid = chunk_to_node.get(chunk_id, "")
        if not nid:
            print(f"  [{i}/{len(GROUND_TRUTH)}] WARN: no node_id for chunk_id={chunk_id}")
            continue
        out = await _run_one(i, len(GROUND_TRUTH), query, jur, nid)
        results.append(out)

    _summarise(results)

    # save the full results to a json file for later inspection
    out_path = ROOT / "tests" / "eval_reasoning_output.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  full per-query results written to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
