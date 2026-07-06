"""end-to-end smoke test for the langgraph reasoning pipeline.

drives one realistic query through:
  retrieval -> reasoning_graph (route -> draft -> verify -> finalize)

prints the final ReasonedAnswer plus the full reasoning trace so you can
see which nodes ran and what they decided.

run from project root:
    .venv\\Scripts\\python.exe -X utf8 -m tests.smoke_reasoning
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reasoning.orchestrator import reasoning_graph
from reasoning.schemas      import SearchRequest
from retrieval.retriever    import hybrid_search


def _chunks_from_nodes(nodes) -> list[dict]:
    """convert llamaindex NodeWithScore objects into the dict shape the
    reasoning pipeline expects (node_id, content, jurisdiction, etc.)."""
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


async def _run_one(query: str, jurisdiction: str | None = None) -> None:
    print("=" * 84)
    print(f"  QUERY: {query!r}")
    if jurisdiction:
        print(f"  filter: jurisdiction={jurisdiction}")
    print("=" * 84)

    # 1. retrieve top-5 chunks
    t0 = time.time()
    nodes  = hybrid_search(query, top_k=5, jurisdiction=jurisdiction)
    chunks = _chunks_from_nodes(nodes)
    print(f"\n  [retrieve] {len(chunks)} chunks in {time.time() - t0:.1f}s")
    for i, c in enumerate(chunks, 1):
        print(f"    [Chunk {i}] [{c['jurisdiction']}] {c['regulation_name']}: {c['content'][:80]!r}")

    # 2. drive the reasoning graph
    t0 = time.time()
    request = SearchRequest(query=query, jurisdiction=jurisdiction)
    initial_state = {
        "request":          request,
        "retrieved_chunks": chunks,
        "reasoning_trace":  [],
        "retries":          0,
    }
    result = await reasoning_graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": f"smoke-{int(time.time())}"}},
    )
    dt = time.time() - t0
    print(f"\n  [reasoning graph] finished in {dt:.1f}s")

    # 3. show the reasoning trace
    final = result["final_output"]
    print(f"\n  ROUTE:      {result.get('route', '?')}")
    print(f"  CONFIDENCE: {final.confidence:.2f}")
    print(f"  CITATIONS:  {len(final.citations)}")

    print("\n  ─ trace ─────────────────────────────────────────────────────")
    for step in result.get("reasoning_trace", []):
        print(f"    {step.action:12} | {step.description}")

    print("\n  ─ summary ───────────────────────────────────────────────────")
    print(f"    {final.summary}")

    if final.citations:
        print("\n  ─ citations ─────────────────────────────────────────────────")
        for c in final.citations:
            print(f"    [{c.jurisdiction}] {c.regulation_name} — {c.article_ref or '(no art)'}")
            print(f"      \"{c.exact_quote[:120]}...\"" if len(c.exact_quote) > 120 else f"      \"{c.exact_quote}\"")

    if final.warnings:
        print("\n  ─ warnings ──────────────────────────────────────────────────")
        for w in final.warnings:
            print(f"    ! {w}")

    print()


async def main() -> None:
    print("=" * 84)
    print("  SMOKE TEST: langgraph reasoning pipeline (route + draft + verify)")
    print("=" * 84)
    print()

    # one realistic legal question. bahrain breach notification is a known
    # tested case from tests/eval_retrievers.py — we know retrieval finds it.
    await _run_one(
        "What is the breach notification timeline to the Bahrain PDPA?",
        jurisdiction="bahrain",
    )


if __name__ == "__main__":
    asyncio.run(main())
