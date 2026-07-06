"""retrieval evaluation: runs llamaindex's RetrieverEvaluator over the
production retriever (retrieval/retriever.py) and prints the standard
information-retrieval metrics.

metrics computed:
  - hit_rate    : did the expected chunk show up in top-k at all?
  - mrr         : 1 / rank of the first relevant chunk (higher = better)
  - precision   : fraction of returned chunks that were relevant
  - recall      : fraction of relevant chunks that were returned
  - ap          : average precision across the ranking
  - ndcg        : normalised discounted cumulative gain (rank-aware)

ground truth comes from two sources:
  1. tests/test_embedder.py — 8 hand-picked question-to-chunk_id pairs
  2. tests/synthetic_qa.json — q-a pairs auto-generated from chunks via
     ollama. run scripts.generate_eval_dataset to refresh.

run from project root:
    .venv\\Scripts\\python.exe -X utf8 -m tests.eval_retrievers
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llama_index.core.evaluation import RetrieverEvaluator
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema     import NodeWithScore, QueryBundle, TextNode

from retrieval.retriever import RetrievalService

SYNTHETIC_PATH = ROOT / "tests" / "synthetic_qa.json"

# hand-picked ground truth: 8 queries with the chunk we expect to rank top.
# spans all four jurisdictions and mixes obligation/definition/procedural
# language, so a regression in any of those areas shows up here.
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


def build_chunk_to_node_map() -> dict[str, str]:
    """walk chunks_inspect/*.jsonl and build {chunk_id: node_id}.
    chunks_inspect uses the same chunker as ingestion, so the node_ids
    here match what's in chromadb."""
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


def _load_synthetic_pairs(chunk_to_node: dict[str, str]) -> list[tuple[str, str, str]]:
    """load tests/synthetic_qa.json (if it exists) and resolve to node_ids."""
    if not SYNTHETIC_PATH.exists():
        return []
    rows = json.loads(SYNTHETIC_PATH.read_text(encoding="utf-8"))
    pairs: list[tuple[str, str, str]] = []
    for r in rows:
        nid = r.get("expected_node_id") or chunk_to_node.get(r.get("expected_chunk_id", ""))
        if not nid:
            continue
        pairs.append((r["query"], nid, f"synthetic [{r.get('jurisdiction','?')}]"))
    return pairs


class RetrieverAdapter(BaseRetriever):
    """thin BaseRetriever shim around RetrievalService.search().
    RetrieverEvaluator drives any object exposing _retrieve(query_bundle)
    -> list[NodeWithScore]. we set node.id_ explicitly so the evaluator
    can match retrieved ids against the ground-truth node_ids."""

    def __init__(self, service: RetrievalService, top_k: int = 5, rerank: bool = True):
        super().__init__()
        self.svc    = service
        self.top_k  = top_k
        self.rerank = rerank

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        results = self.svc.search(
            query_bundle.query_str,
            top_k=self.top_k,
            rerank=self.rerank,
            expand_parent=False,    # eval doesn't care about parent bodies
        )
        out = []
        for n in results:
            md  = n.node.metadata
            nid = md.get("node_id") or n.node.node_id
            tn  = TextNode(text=n.node.get_content(), metadata=md, id_=nid)
            out.append(NodeWithScore(node=tn, score=n.score))
        return out


def _aggregate_metrics(eval_results: list) -> dict[str, float]:
    """average each metric across all queries."""
    metrics = ["hit_rate", "mrr", "precision", "recall", "ap", "ndcg"]
    out = {m: 0.0 for m in metrics}
    n = len(eval_results)
    if n == 0:
        return out
    for er in eval_results:
        for m, v in er.metric_vals_dict.items():
            if m in out:
                out[m] += v
    return {m: out[m] / n for m in metrics}


def main() -> None:
    print("=" * 78)
    print("  RETRIEVAL EVALUATION (RetrieverEvaluator over retrieval.retriever)")
    print("=" * 78)

    print("\n  loading chunks_inspect map (chunk_id -> node_id)...")
    chunk_to_node = build_chunk_to_node_map()
    print(f"  loaded {len(chunk_to_node):,} chunk -> node mappings")

    # build the dataset: hand-picked + synthetic
    dataset: list[tuple[str, str, str]] = []
    for query, chunk_id, why in GROUND_TRUTH:
        nid = chunk_to_node.get(chunk_id)
        if not nid:
            print(f"  WARN  unresolved chunk_id: {chunk_id}")
            continue
        dataset.append((query, nid, why))
    print(f"  hand-picked: {len(dataset)} pairs")

    synthetic = _load_synthetic_pairs(chunk_to_node)
    print(f"  synthetic  : {len(synthetic)} pairs")
    dataset.extend(synthetic)
    print(f"  total      : {len(dataset)} ground-truth pairs\n")

    print("  warming up retriever...")
    svc = RetrievalService()
    svc.search("warm up", top_k=1, rerank=True, expand_parent=False)
    print("  done.\n")

    metrics = ["hit_rate", "mrr", "precision", "recall", "ap", "ndcg"]
    adapter = RetrieverAdapter(svc, top_k=5, rerank=True)
    evaluator = RetrieverEvaluator.from_metric_names(metrics, retriever=adapter)

    async def _run():
        results = []
        for query, expected_nid, _why in dataset:
            try:
                er = await evaluator.aevaluate(query=query, expected_ids=[expected_nid])
                results.append(er)
            except Exception as e:
                print(f"  ERR on {query[:40]!r}: {e}")
        return results

    print("=" * 78)
    print(f"  running {len(dataset)} queries through the retriever...")
    t0 = time.time()
    results = asyncio.run(_run())
    dt = time.time() - t0
    print(f"  done in {dt:.1f}s ({dt/len(dataset):.2f}s per query)\n")

    # per-query rank table
    print("=" * 78)
    print("  PER-QUERY RANK (position in top-5; '-' = miss)")
    print("=" * 78)
    print(f"  {'query':<70}  {'rank':>5}")
    for (query, _nid, _why), er in zip(dataset, results):
        rank = "-" if er.metric_vals_dict["mrr"] == 0 else f"{int(round(1/er.metric_vals_dict['mrr']))}"
        print(f"  {query[:68]:<70}  {rank:>5}")

    # final summary
    agg = _aggregate_metrics(results)
    print()
    print("=" * 78)
    print("  AVERAGE METRICS (higher is better, 0.0-1.0 range)")
    print("=" * 78)
    for m in metrics:
        bar = "#" * int(agg[m] * 40)
        print(f"  {m:<12}  {agg[m]:6.4f}  {bar}")

    n_hits = sum(1 for r in results if r.metric_vals_dict["hit_rate"] > 0)
    print(f"\n  hits in top-5     : {n_hits} / {len(results)}")
    print(f"  total queries     : {len(dataset)}")
    print(f"  avg latency       : {dt/len(dataset)*1000:.0f} ms")


if __name__ == "__main__":
    main()
