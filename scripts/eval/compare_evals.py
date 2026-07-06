"""side-by-side comparison of three eval frameworks on the same 8 queries:
  1. our built-in eval (NLI hallucination + verifier-grounding)
  2. RAGAS  (LLM-as-judge faithfulness + answer relevancy)
  3. DeepEval (LLM-as-judge hallucination + answer relevancy)

we re-use the answers from tests/eval_reasoning_output.json (no new
reasoning calls), and re-retrieve chunks from chromadb (free, deterministic,
matches what the reasoner saw). RAGAS and DeepEval then each call the LLM
2-3 times per query to judge the answer — Claude Haiku 4.5 via openrouter.

estimated cost: ~$0.10 for the full comparison.

run from project root:
    .venv\\Scripts\\python.exe -X utf8 -m tests.compare_evals
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# load .env so OPENROUTER_API_KEY is available
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from retrieval.retriever import hybrid_search


SAVED_JSON = ROOT / "tests" / "eval_reasoning_output.json"


def _load_saved_results() -> list[dict]:
    """load the per-query results from our last reasoning eval run."""
    if not SAVED_JSON.exists():
        raise SystemExit(
            f"no saved results at {SAVED_JSON}. run "
            "`.venv/Scripts/python.exe -m tests.eval_reasoning` first."
        )
    return json.loads(SAVED_JSON.read_text(encoding="utf-8"))


def _is_fallback(summary: str) -> bool:
    """detect the canned fallback response so we can skip llm-as-judge
    scoring (no real answer to judge)."""
    return summary.startswith("I cannot provide a fully grounded answer")


def _retrieve_chunks(query: str, jurisdiction: str | None) -> list[str]:
    """re-retrieve the chunks the reasoner saw. chromadb is deterministic,
    so we get the same top-5 every call."""
    nodes = hybrid_search(query, top_k=5, jurisdiction=jurisdiction)
    return [n.node.get_content() for n in nodes]


# llm-as-judge setup (claude haiku via openrouter)

def _make_judge_llm():
    """one ChatOpenAI pointed at openrouter — used by both ragas and deepeval
    so the comparison is apples-to-apples."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model       = "anthropic/claude-haiku-4-5",
        temperature = 0.0,
        max_tokens  = 2000,
        timeout     = 60,
        api_key     = os.environ["OPENROUTER_API_KEY"],
        base_url    = "https://openrouter.ai/api/v1",
    )


def _make_embedder():
    """bge-small embedder for ragas answer_relevancy. same model the
    retrieval layer uses."""
    from langchain_community.embeddings import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-en-v1.5",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


# RAGAS evaluation

def run_ragas(samples: list[dict]) -> list[dict]:
    """score each sample with ragas faithfulness + answer relevancy.
    returns one dict per sample with the two scores."""
    print("\n  [RAGAS] scoring...")
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.run_config import RunConfig

    judge_llm = LangchainLLMWrapper(_make_judge_llm())
    embedder  = LangchainEmbeddingsWrapper(_make_embedder())

    # ragas wants user_input/response/retrieved_contexts in current versions
    rows = [
        {
            "user_input":         s["query"],
            "response":           s["summary"],
            "retrieved_contexts": s["chunks"],
        }
        for s in samples
    ]
    dataset = Dataset.from_list(rows)

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=judge_llm,
        embeddings=embedder,
        raise_exceptions=False,
        run_config=RunConfig(timeout=120, max_workers=1),
    )
    df = result.to_pandas()
    return [
        {
            "faithfulness":      float(row.get("faithfulness", float("nan"))),
            "answer_relevancy":  float(row.get("answer_relevancy", float("nan"))),
        }
        for _, row in df.iterrows()
    ]


# DeepEval

class _OpenRouterChatModel:
    """thin wrapper for deepeval's DeepEvalBaseLLM. deepeval was built around
    openai-style chat completions; we point the same call at openrouter."""

    def __init__(self):
        self._llm = _make_judge_llm()

    def load_model(self):
        return self._llm

    def generate(self, prompt: str, **_) -> str:
        # deepeval calls generate() synchronously
        return self._llm.invoke(prompt).content

    async def a_generate(self, prompt: str, **_) -> str:
        msg = await self._llm.ainvoke(prompt)
        return msg.content

    def get_model_name(self) -> str:
        return "anthropic/claude-haiku-4-5 (via openrouter)"


def run_deepeval(samples: list[dict]) -> list[dict]:
    """score each sample with deepeval hallucination + answer relevancy."""
    print("\n  [DeepEval] scoring...")
    from deepeval.metrics import HallucinationMetric, AnswerRelevancyMetric
    from deepeval.test_case import LLMTestCase
    from deepeval.models import DeepEvalBaseLLM

    class _DEModel(DeepEvalBaseLLM):
        def __init__(self):
            self._inner = _OpenRouterChatModel()
        def load_model(self):
            return self._inner
        def generate(self, prompt: str, **_) -> str:
            return self._inner.generate(prompt)
        async def a_generate(self, prompt: str, **_) -> str:
            return await self._inner.a_generate(prompt)
        def get_model_name(self) -> str:
            return self._inner.get_model_name()

    judge = _DEModel()
    halluc_metric = HallucinationMetric(threshold=0.5, model=judge, async_mode=False)
    relev_metric  = AnswerRelevancyMetric(threshold=0.5, model=judge, async_mode=False)

    out = []
    for s in samples:
        tc = LLMTestCase(
            input             = s["query"],
            actual_output     = s["summary"],
            context           = s["chunks"],         # for hallucination
            retrieval_context = s["chunks"],         # for answer relevancy
        )
        try:
            halluc_metric.measure(tc)
            relev_metric.measure(tc)
            out.append({
                # deepeval reports hallucination as 0=no hallucination, 1=full
                # hallucination. faithfulness is the inverse for parity with ragas.
                "faithfulness":     round(1.0 - float(halluc_metric.score), 3),
                "answer_relevancy": round(float(relev_metric.score), 3),
            })
        except Exception as e:
            print(f"    deepeval err on {s['query'][:40]!r}: {type(e).__name__}: {str(e)[:80]}")
            out.append({"faithfulness": float("nan"), "answer_relevancy": float("nan")})
    return out


# main

def main() -> None:
    print("=" * 96)
    print("  EVAL FRAMEWORK COMPARISON: built-in vs RAGAS vs DeepEval")
    print("=" * 96)

    saved = _load_saved_results()
    print(f"\n  loaded {len(saved)} saved query results from {SAVED_JSON.name}")

    # build the comparison set: question, summary, chunks. skip fallbacks
    # since RAGAS/DeepEval would just score the canned response (unfair).
    samples: list[dict] = []
    for r in saved:
        if _is_fallback(r["summary"]) or r.get("error"):
            continue
        chunks = _retrieve_chunks(r["query"], r.get("jurisdiction"))
        samples.append({
            "idx":          r["idx"],
            "query":        r["query"],
            "summary":      r["summary"],
            "chunks":       chunks,
            "builtin_hall": r.get("hallucination_risk"),
            "builtin_conf": r.get("confidence"),
        })

    print(f"  scoring {len(samples)} successful queries (skipped fallbacks/errors)")

    # run all three evals
    t0 = time.time()
    ragas_scores  = run_ragas(samples)
    ragas_dt = time.time() - t0

    t0 = time.time()
    deepeval_scores = run_deepeval(samples)
    deepeval_dt = time.time() - t0

    # the built-in scores are already on each sample; just transform for the
    # same shape: built-in faithfulness = 1 - hallucination_risk
    builtin = [
        {
            "faithfulness":     round(1.0 - (s["builtin_hall"] or 0.0), 3),
            "answer_relevancy": s["builtin_conf"],   # closest equivalent
        }
        for s in samples
    ]

    # report
    print()
    print("=" * 96)
    print("  PER-QUERY SCORES (faith / ans_rel)")
    print("=" * 96)
    print(f"  {'#':>2}  {'query':<46}    {'built-in':>16}  {'RAGAS':>16}  {'DeepEval':>16}")
    print(f"  {'-'*2}  {'-'*46}    {'-'*16}  {'-'*16}  {'-'*16}")
    for s, b, ra, de in zip(samples, builtin, ragas_scores, deepeval_scores):
        b_pair  = f"{b['faithfulness']:.2f}/{b['answer_relevancy']:.2f}"
        ra_pair = f"{ra['faithfulness']:.2f}/{ra['answer_relevancy']:.2f}"
        de_pair = f"{de['faithfulness']:.2f}/{de['answer_relevancy']:.2f}"
        print(f"  Q{s['idx']:>1}  {s['query'][:44]:<46}    {b_pair:>16}  {ra_pair:>16}  {de_pair:>16}")

    # aggregates
    def _avg(scores, key):
        vals = [s[key] for s in scores if isinstance(s.get(key), (int, float)) and s[key] == s[key]]
        return sum(vals) / len(vals) if vals else float("nan")

    print()
    print("=" * 96)
    print("  AGGREGATE")
    print("=" * 96)
    print(f"  {'system':<14}  {'faithfulness':>14}  {'answer_relevancy':>18}")
    print(f"  {'-'*14}  {'-'*14}  {'-'*18}")
    print(f"  {'built-in':<14}  {_avg(builtin,'faithfulness'):>14.3f}  {_avg(builtin,'answer_relevancy'):>18.3f}")
    print(f"  {'RAGAS':<14}  {_avg(ragas_scores,'faithfulness'):>14.3f}  {_avg(ragas_scores,'answer_relevancy'):>18.3f}")
    print(f"  {'DeepEval':<14}  {_avg(deepeval_scores,'faithfulness'):>14.3f}  {_avg(deepeval_scores,'answer_relevancy'):>18.3f}")

    print()
    print(f"  RAGAS    elapsed: {ragas_dt:.1f}s")
    print(f"  DeepEval elapsed: {deepeval_dt:.1f}s")


if __name__ == "__main__":
    main()
