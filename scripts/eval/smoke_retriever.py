"""end-to-end smoke test for the hybrid retriever.

drives a few real queries through the full pipeline (vector + bm25 + rrf
fusion + cross-encoder rerank + parent expansion) and prints the top results.
useful as a quick "is the retriever still alive?" check after touching any
ingestion or retrieval code.

run from project root:
    .venv\\Scripts\\python.exe -X utf8 -m tests.smoke_retriever
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.retriever import RetrievalService


def _show(label: str, query: str, filter_desc: str, results) -> None:
    print("=" * 92)
    print(f"  {label}")
    print(f"  query: {query!r}")
    if filter_desc:
        print(f"  filter: {filter_desc}")
    print()
    for i, r in enumerate(results, 1):
        md  = r.node.metadata
        cit = md.get("hierarchy_path", "")
        score = r.score or 0.0
        parent_marker = "  [+parent]" if md.get("_parent") else ""
        print(f"  #{i}  score={score:+.3f}{parent_marker}")
        print(f"       [{md.get('jurisdiction','?')}] {cit[:90]}")
        print(f"       -> {r.node.get_content()[:140].strip()!r}")
    print()


def main() -> None:
    print("=" * 92)
    print("  SMOKE TEST: hybrid retriever (vector + bm25 + rrf + rerank + parent)")
    print("=" * 92)
    print()

    svc = RetrievalService()

    # query 1: cross-jurisdictional — should surface penalty articles
    # from multiple regimes
    t0 = time.time()
    res = svc.search(
        "What are the penalties for unauthorized disclosure of personal data?",
        top_k=3,
    )
    _show(f"Q1 cross-jurisdictional ({time.time() - t0:.1f}s)",
          "What are the penalties for unauthorized disclosure of personal data?", "", res)

    # query 2: filtered to one jurisdiction
    t0 = time.time()
    res = svc.search("breach notification timeline", top_k=3, jurisdiction="bahrain")
    _show(f"Q2 bahrain only ({time.time() - t0:.1f}s)",
          "breach notification timeline", "jurisdiction=bahrain", res)

    # query 3: entity-heavy query — bm25 should catch "children" even when
    # vector similarity might drift to general consent provisions
    t0 = time.time()
    res = svc.search("processing children's personal data with parental consent", top_k=3)
    _show(f"Q3 entity-heavy ({time.time() - t0:.1f}s)",
          "processing children's personal data with parental consent", "", res)

    # query 4: bbk internal policy
    t0 = time.time()
    res = svc.search("vendor agreement requirements for sharing customer data",
                     top_k=3, jurisdiction="bbk")
    _show(f"Q4 bbk internal ({time.time() - t0:.1f}s)",
          "vendor agreement requirements for sharing customer data",
          "jurisdiction=bbk", res)

    # query 5: same as Q1 but with rerank turned off — useful for comparing
    # the effect of the cross-encoder
    t0 = time.time()
    res = svc.search(
        "What are the penalties for unauthorized disclosure of personal data?",
        top_k=3, rerank=False,
    )
    _show(f"Q5 rerank off ({time.time() - t0:.1f}s)",
          "same as Q1 but rerank=False", "", res)

    print("=" * 92)
    print("  smoke test done")
    print("=" * 92)


if __name__ == "__main__":
    main()
