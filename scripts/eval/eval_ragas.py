import os
os.environ["HF_HOME"]                = "D:\\hf_cache"
os.environ["TRANSFORMERS_CACHE"]     = "D:\\hf_cache\\transformers"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

"""
RAGAS Evaluation — Cross-Jurisdictional Privacy Compliance Analyzer
====================================================================
Metrics (no ground-truth required):
  1. Faithfulness      — is the answer grounded in the retrieved context?
  2. Answer Relevancy  — is the answer relevant to the question?

Judge LLM: Claude Haiku 4.5 via OpenRouter (matches the production
reasoning pipeline). Set OPENROUTER_API_KEY in .env.

Requires packages: pip install ragas datasets langchain-openai
"""

import sys
import json
import warnings
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
if str(_BASE) not in sys.path:
    sys.path.append(str(_BASE))

# load .env so OPENROUTER_API_KEY is available
try:
    from dotenv import load_dotenv
    load_dotenv(_BASE / ".env")
except ImportError:
    pass

# Suppress noisy deprecation warnings from langchain / ragas internals
warnings.filterwarnings("ignore", category=DeprecationWarning)

from tests.eval import TEST_SET
from retrieval.retriever import hybrid_search
from reasoning.llm_shims import _call_llm, _format_nodes

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.run_config import RunConfig

from langchain_openai import ChatOpenAI
from langchain_community.embeddings import HuggingFaceEmbeddings


# both the answer-under-test LLM and the judge LLM go through OpenRouter
# (Claude Haiku 4.5 by default). using the same provider for both keeps
# the eval harness simple — the judge model is set independently here so
# we can swap it later without touching production reasoning config.
JUDGE_MODEL = "anthropic/claude-haiku-4-5"


# ── Step 1: run retrieval + LLM for every query ───────────────────────────────

def _collect_samples(top_k: int = 5, limit: int = 0) -> dict:
    questions: list[str]        = []
    answers:   list[str]        = []
    contexts:  list[list[str]]  = []

    tests = TEST_SET[:limit] if limit else TEST_SET
    print(f"\nCollecting answers — {len(tests)} queries, top_k={top_k}")

    for i, test in enumerate(tests, 1):
        query   = test["query"]
        exp_jur = test["expected_jurisdiction"]

        print(f"  [{i:>2}/{len(TEST_SET)}] {test['description']}")

        nodes = hybrid_search(query, top_k=top_k, jurisdiction=exp_jur, rerank=True)

        context_chunks = [n.node.get_content() for n in nodes]

        label         = exp_jur or "Legal"
        context_block = _format_nodes(nodes, label)
        prompt = (
            "Based ONLY on the following legal text, "
            "answer this question in 2-3 sentences:\n"
            f"Question: {query}\n\n{context_block}\n\nAnswer:"
        )

        try:
            answer = _call_llm(prompt, max_tokens=300)
            if not answer.strip():
                answer = "(no answer generated)"
        except Exception as e:
            answer = f"(LLM error: {e})"
            print(f"         [!] LLM error: {e}")

        questions.append(query)
        answers.append(answer)
        contexts.append(context_chunks)

    return {"question": questions, "answer": answers, "contexts": contexts}


# ── Step 2: run RAGAS evaluate ────────────────────────────────────────────────

def run_ragas_eval(top_k: int = 5, limit: int = 0) -> None:
    print("RAGAS EVALUATION — Cross-Jurisdictional Privacy Compliance")
    print(f"Judge: {JUDGE_MODEL} (via OpenRouter)  |  top_k={top_k}")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENROUTER_API_KEY not set. Add it to .env or run:\n"
            "  $env:OPENROUTER_API_KEY = 'sk-or-...'"
        )

    samples = _collect_samples(top_k=top_k, limit=limit)
    dataset = Dataset.from_dict(samples)

    # Claude Haiku 4.5 via OpenRouter as the judge LLM
    judge_llm = LangchainLLMWrapper(
        ChatOpenAI(
            model       = JUDGE_MODEL,
            temperature = 0.0,
            max_tokens  = 2000,
            timeout     = 60,
            api_key     = api_key,
            base_url    = "https://openrouter.ai/api/v1",
        )
    )

    # Reuse already-downloaded bge-small embedder
    hf_embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-en-v1.5",
            cache_folder="D:\\hf_cache",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    )

    print("\nRunning RAGAS evaluate...")
    print("Metrics: faithfulness, answer_relevancy")

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=judge_llm,
        embeddings=hf_embeddings,
        raise_exceptions=False,
        run_config=RunConfig(timeout=120, max_workers=1),
    )

    df = result.to_pandas()

    # ── Per-query results ─────────────────────────────────────────────────────
    print("\nPER-QUERY RESULTS")
    tests = TEST_SET[:limit] if limit else TEST_SET
    desc_list = [t["description"] for t in tests]
    df.insert(0, "description", desc_list[: len(df)])

    col_w = 38
    print(f"  {'Description':<{col_w}} {'Faithful':>9}  {'AnsRel':>7}")
    print(f"  {'-'*col_w} {'-'*9}  {'-'*7}")
    for _, row in df.iterrows():
        faith = row.get("faithfulness", float("nan"))
        rel   = row.get("answer_relevancy", float("nan"))
        faith_s = f"{faith:.3f}" if faith == faith else "  N/A"
        rel_s   = f"{rel:.3f}"   if rel   == rel   else "  N/A"
        print(f"  {str(row['description']):<{col_w}} {faith_s:>9}  {rel_s:>7}")

    # ── Aggregate ─────────────────────────────────────────────────────────────
    avg_faith = df["faithfulness"].mean()
    avg_rel   = df["answer_relevancy"].mean()

    print(f"\nAGGREGATE")
    print(f"  Faithfulness     : {avg_faith:.4f}  "
          f"{'[OK]' if avg_faith >= 0.5 else '[!!]'}")
    print(f"  Answer Relevancy : {avg_rel:.4f}  "
          f"{'[OK]' if avg_rel >= 0.7 else '[!!]'}")

    # ── Save report ───────────────────────────────────────────────────────────
    report = {
        "summary": {
            "faithfulness":     round(float(avg_faith), 4),
            "answer_relevancy": round(float(avg_rel), 4),
        },
        "queries": df.drop(columns=["contexts"], errors="ignore")
                     .to_dict(orient="records"),
    }
    out_path = _BASE / "tests" / "eval_ragas_report.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport saved -> {out_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0, help="limit to first N queries (0 = all)")
    args = parser.parse_args()
    run_ragas_eval(top_k=args.top_k, limit=args.limit)
