import os
os.environ["HF_HOME"]                = "D:\\hf_cache"
os.environ["TRANSFORMERS_CACHE"]     = "D:\\hf_cache\\transformers"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

"""
RAG Evaluation — Cross-Jurisdictional Privacy Compliance Analyzer
=================================================================
Metrics:
  1. Hit Rate @K      — does a relevant chunk appear in top-K results?
  2. MRR @K           — Mean Reciprocal Rank
  3. Context Relevance— cosine similarity between query and retrieved chunks
  4. Faithfulness     — LLM answer grounded in retrieved context
  5. Citation Accuracy— fraction of chunks with populated article_ref
"""

import sys
import json
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field

_BASE = Path(__file__).resolve().parent.parent
if str(_BASE) not in sys.path:
    sys.path.append(str(_BASE))


# ── Test set ──────────────────────────────────────────────────────────────────
# expected_articles: article refs OR None (jurisdiction-level check only)
# expected_jurisdiction: jurisdiction that must appear in results

TEST_SET = [
    # ── Bahrain ───────────────────────────────────────────────────────────────
    {
        "query":                  "definition of personal data and sensitive personal data",
        "description":            "Bahrain — Definitions",
        "expected_jurisdiction":  "Bahrain",
        "expected_articles":      ["Article (1)"],
    },
    {
        "query":                  "data breach notification obligations Bahrain",
        "description":            "Bahrain — Data breach notification",
        "expected_jurisdiction":  "Bahrain",
        "expected_articles":      ["Article (14)"],
    },
    {
        "query":                  "consent conditions for processing personal data Bahrain",
        "description":            "Bahrain — Consent for processing",
        "expected_jurisdiction":  "Bahrain",
        "expected_articles":      ["Article (5)", "Article (24)"],
    },
    {
        "query":                  "transfer of personal data outside Bahrain",
        "description":            "Bahrain — Cross-border transfer",
        "expected_jurisdiction":  "Bahrain",
        "expected_articles":      ["Article (12)", "Article (13)"],
    },
    {
        "query":                  "data protection guardian appointment duties Bahrain",
        "description":            "Bahrain — DPO equivalent",
        "expected_jurisdiction":  "Bahrain",
        "expected_articles":      ["Article (10)"],
    },
    # ── India ─────────────────────────────────────────────────────────────────
    {
        "query":                  "data fiduciary obligations India digital personal data",
        "description":            "India — Data fiduciary obligations",
        "expected_jurisdiction":  "India",
        "expected_articles":      None,
    },
    {
        "query":                  "consent manager India data principal rights",
        "description":            "India — Consent and data principal rights",
        "expected_jurisdiction":  "India",
        "expected_articles":      None,
    },
    {
        "query":                  "IT outsourcing third party RBI directions",
        "description":            "India — RBI IT outsourcing",
        "expected_jurisdiction":  "India",
        "expected_articles":      None,
    },
    # ── Kuwait ────────────────────────────────────────────────────────────────
    {
        "query":                  "data privacy protection regulation Kuwait",
        "description":            "Kuwait — Data privacy regulation",
        "expected_jurisdiction":  "Kuwait",
        "expected_articles":      None,
    },
    {
        "query":                  "cyber operational resilience framework Kuwait",
        "description":            "Kuwait — Cyber resilience",
        "expected_jurisdiction":  "Kuwait",
        "expected_articles":      None,
    },
    # ── BBK Internal Policies ─────────────────────────────────────────────────
    {
        "query":                  "data subject rights BBK policy procedure",
        "description":            "BBK — Data subject rights policy",
        "expected_jurisdiction":  "BBK",
        "expected_articles":      None,
    },
    {
        "query":                  "third party vendor data processing BBK",
        "description":            "BBK — Third party data processing policy",
        "expected_jurisdiction":  "BBK",
        "expected_articles":      None,
    },
    # ── Cross-jurisdiction ────────────────────────────────────────────────────
    {
        "query":                  "data retention period storage limitation",
        "description":            "Cross — Data retention across jurisdictions",
        "expected_jurisdiction":  None,
        "expected_articles":      None,
    },
    {
        "query":                  "penalties fines violation data protection law",
        "description":            "Cross — Penalties for non-compliance",
        "expected_jurisdiction":  None,
        "expected_articles":      None,
    },
]


# ── Metric helpers ────────────────────────────────────────────────────────────

def _hit_article(retrieved_refs: list[str], expected: list[str] | None) -> bool:
    if not expected:
        return True   # no article-level expectation
    retrieved_set = {r.strip().lower() for r in retrieved_refs}
    return any(e.strip().lower() in retrieved_set for e in expected)


def _hit_jurisdiction(retrieved_jurisdictions: list[str], expected: str | None) -> bool:
    if not expected:
        return True   # no jurisdiction expectation
    return any(j.lower() == expected.lower() for j in retrieved_jurisdictions)


def _hit(retrieved_refs, retrieved_jurisdictions, expected_articles, expected_jurisdiction) -> bool:
    return (
        _hit_article(retrieved_refs, expected_articles)
        and _hit_jurisdiction(retrieved_jurisdictions, expected_jurisdiction)
    )


def _reciprocal_rank(retrieved_refs: list[str], expected: list[str] | None) -> float:
    if not expected:
        return 1.0   # no article expectation — treat as hit
    expected_set = {e.strip().lower() for e in expected}
    for rank, ref in enumerate(retrieved_refs, 1):
        if ref.strip().lower() in expected_set:
            return 1.0 / rank
    return 0.0


def _context_relevance(query_vec: np.ndarray, node_vecs: list[np.ndarray]) -> float:
    if not node_vecs:
        return 0.0
    sims = [float(np.dot(query_vec, v)) for v in node_vecs]
    return round(float(np.mean(sims)), 4)


def _faithfulness(answer: str, context_chunks: list[str]) -> float:
    import re
    sentences = [s.strip() for s in re.split(r'[.!?]\s+', answer) if len(s.strip()) > 20]
    if not sentences:
        return 1.0
    stop = {"the", "a", "an", "of", "in", "to", "and", "or", "is", "are",
            "that", "this", "it", "by", "for", "with", "be", "has", "have",
            "its", "their", "which", "was", "as", "at", "from", "on"}
    context_tokens = set(" ".join(context_chunks).lower().split()) - stop
    scores = []
    for sent in sentences:
        sent_tokens = set(sent.lower().split()) - stop
        if not sent_tokens:
            continue
        scores.append(len(sent_tokens & context_tokens) / len(sent_tokens))
    return round(float(np.mean(scores)) if scores else 1.0, 4)


def _citation_accuracy(nodes: list) -> float:
    if not nodes:
        return 0.0
    filled = sum(
        1 for n in nodes
        if n.node.metadata.get("article_ref", "").strip()
    )
    return round(filled / len(nodes), 4)


# ── Main evaluation ───────────────────────────────────────────────────────────

@dataclass
class QueryResult:
    query:                 str
    description:           str
    expected_articles:     list[str] | None
    expected_jurisdiction: str | None
    retrieved_articles:    list[str]  = field(default_factory=list)
    retrieved_jurisdictions: list[str] = field(default_factory=list)
    hit:                   bool       = False
    reciprocal_rank:       float      = 0.0
    context_relevance:     float      = 0.0
    faithfulness:          float      = 0.0
    citation_accuracy:     float      = 0.0
    llm_answer:            str        = ""


def run_eval(top_k: int = 5, use_llm: bool = True) -> None:
    from retrieval.retriever import hybrid_search, _get_st_model, _embed_query
    from reasoning.llm_shims  import _call_llm, _format_nodes

    print(f"RAG EVALUATION — All Jurisdictions")
    print(f"{len(TEST_SET)} queries  |  top_k={top_k}")

    st_model = _get_st_model()
    results  = []

    for i, test in enumerate(TEST_SET, 1):
        query      = test["query"]
        exp_jur    = test["expected_jurisdiction"]
        exp_arts   = test["expected_articles"]

        print(f"\n[{i}/{len(TEST_SET)}] {test['description']}")
        print(f"  Query: {query}")

        # Retrieve — filter by jurisdiction if specified
        nodes = hybrid_search(
            query,
            top_k=top_k,
            jurisdiction=exp_jur,
            rerank=True,
        )

        retrieved_refs = [
            n.node.metadata.get("article_ref", "")
            for n in nodes
        ]
        retrieved_jurisdictions = [
            n.node.metadata.get("jurisdiction", "")
            for n in nodes
        ]

        # Context relevance — embed query and chunks
        query_vec  = np.array(_embed_query(query))
        chunk_vecs = []
        for n in nodes:
            text = n.node.get_content()
            vec  = st_model.encode(text, normalize_embeddings=True, show_progress_bar=False)
            chunk_vecs.append(np.array(vec))

        # LLM faithfulness
        llm_answer  = ""
        faith_score = 0.0
        context_text = [n.node.get_content() for n in nodes]

        if use_llm and nodes:
            label         = exp_jur or "Legal"
            context_block = _format_nodes(nodes, label)
            prompt = (
                f"Based ONLY on the following legal text, answer this question in 2-3 sentences:\n"
                f"Question: {query}\n\n{context_block}\n\nAnswer:"
            )
            try:
                llm_answer  = _call_llm(prompt, max_tokens=300)
                faith_score = _faithfulness(llm_answer, context_text)
            except Exception as e:
                llm_answer  = f"[LLM unavailable: {e}]"
                faith_score = 0.0

        hit = _hit(retrieved_refs, retrieved_jurisdictions, exp_arts, exp_jur)
        rr  = _reciprocal_rank(retrieved_refs, exp_arts)

        qr = QueryResult(
            query=                  query,
            description=            test["description"],
            expected_articles=      exp_arts,
            expected_jurisdiction=  exp_jur,
            retrieved_articles=     retrieved_refs,
            retrieved_jurisdictions=retrieved_jurisdictions,
            hit=                    hit,
            reciprocal_rank=        rr,
            context_relevance=      _context_relevance(query_vec, chunk_vecs),
            faithfulness=           faith_score,
            citation_accuracy=      _citation_accuracy(nodes),
            llm_answer=             llm_answer,
        )
        results.append(qr)

        hit_icon = "PASS" if qr.hit else "FAIL"
        print(f"  Expected : jur={exp_jur or 'any'}  arts={exp_arts or 'any'}")
        print(f"  Retrieved: {', '.join(r for r in retrieved_refs if r) or '(none)'}")
        print(f"  Hit@{top_k}: {hit_icon}  |  RR={qr.reciprocal_rank:.2f}  |  "
              f"CtxRel={qr.context_relevance:.3f}  |  "
              f"Faith={qr.faithfulness:.3f}  |  "
              f"CiteAcc={qr.citation_accuracy:.3f}")
        if llm_answer and "[LLM unavailable" not in llm_answer:
            print(f"  LLM: {llm_answer[:120].strip()} ...")

    # ── Aggregate ─────────────────────────────────────────────────────────────
    n                = len(results)
    hit_rate         = sum(r.hit               for r in results) / n
    mrr              = sum(r.reciprocal_rank   for r in results) / n
    avg_ctx_rel      = sum(r.context_relevance for r in results) / n
    avg_faithfulness = sum(r.faithfulness      for r in results) / n
    avg_cite_acc     = sum(r.citation_accuracy for r in results) / n

    print(f"\nAGGREGATE RESULTS")
    print(f"  Queries evaluated  : {n}")
    print(f"  Hit Rate @{top_k}       : {hit_rate:.2%}")
    print(f"  MRR @{top_k}            : {mrr:.4f}")
    print(f"  Context Relevance  : {avg_ctx_rel:.4f}")
    print(f"  Faithfulness       : {avg_faithfulness:.4f}")
    print(f"  Citation Accuracy  : {avg_cite_acc:.4f}")

    print(f"\nINTERPRETATION")
    print(f"  {'Hit Rate':.<25} {'GOOD [OK]' if hit_rate >= 0.7 else 'NEEDS WORK [!!]'}")
    print(f"  {'MRR':.<25} {'GOOD [OK]' if mrr >= 0.5 else 'NEEDS WORK [!!]'}")
    print(f"  {'Context Relevance':.<25} {'GOOD [OK]' if avg_ctx_rel >= 0.6 else 'NEEDS WORK [!!]'}")
    print(f"  {'Faithfulness':.<25} {'GOOD [OK]' if avg_faithfulness >= 0.5 else 'CHECK LLM [!!]'}")
    print(f"  {'Citation Accuracy':.<25} {'GOOD [OK]' if avg_cite_acc >= 0.8 else 'NEEDS WORK [!!]'}")

    report = {
        "summary": {
            "hit_rate":          round(hit_rate, 4),
            "mrr":               round(mrr, 4),
            "context_relevance": round(avg_ctx_rel, 4),
            "faithfulness":      round(avg_faithfulness, 4),
            "citation_accuracy": round(avg_cite_acc, 4),
        },
        "queries": [
            {
                "query":                   r.query,
                "description":             r.description,
                "expected_articles":       r.expected_articles,
                "expected_jurisdiction":   r.expected_jurisdiction,
                "retrieved_articles":      r.retrieved_articles,
                "retrieved_jurisdictions": r.retrieved_jurisdictions,
                "hit":                     r.hit,
                "reciprocal_rank":         r.reciprocal_rank,
                "context_relevance":       r.context_relevance,
                "faithfulness":            r.faithfulness,
                "citation_accuracy":       r.citation_accuracy,
            }
            for r in results
        ],
    }
    out_path = _BASE / "tests" / "eval_report.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport saved → {out_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k",  type=int,  default=5)
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM faithfulness check")
    args = parser.parse_args()
    run_eval(top_k=args.top_k, use_llm=not args.no_llm)
