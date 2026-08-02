"""Evaluate lightweight GraphRAG cross-reference expansion vs plain hybrid RAG.

For a set of intentionally cross-document compliance questions, this runs
retrieval BOTH ways — plain hybrid search and hybrid search + one graph hop
(retrieval.graph_expand) — and reports:

  * distinct source documents surfaced
  * distinct jurisdictions covered
  * "linked-doc recall": how many of the top hit's cross-referenced documents
    actually appear in the final context
  * (optional) a real qwen2.5:7b answer for each, so you can eyeball whether the
    extra linked context changes the answer.

Run:  .venv/Scripts/python.exe scripts/eval_graph_expansion.py            (retrieval only)
      .venv/Scripts/python.exe scripts/eval_graph_expansion.py --answers  (also generate answers)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cjpca"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cjpca.settings")

import django
django.setup()

from apps.library.models import Document
from retrieval.retriever import _get_service
from retrieval.graph_expand import expand_with_xrefs, referenced_titles, parse_xref_ids

WANT_ANSWERS = "--answers" in sys.argv

# ── Cross-document questions (each naturally spans multiple linked docs) ──────
QUESTIONS = [
    "What are the data retention limits and which regulations govern them?",
    "How must cross-border transfers of personal data be handled, and under which laws?",
    "What are the breach-notification obligations and their legal basis?",
    "What customer due-diligence / KYC obligations apply and how do they relate across jurisdictions?",
    "What technical and organisational security measures are required, and which rules mandate them?",
]

TOP_K = 5


def build_maps():
    """xref_map: {doc_title: cross_references}; id_to_title: {document_id: doc_title};
    title_to_jur: {doc_title: jurisdiction}."""
    xref_map, id_to_title, title_to_jur = {}, {}, {}
    for d in Document.objects.all():
        t = d.chunk_doc_title
        if not t:
            continue
        title_to_jur[t] = d.jurisdiction or "—"
        if d.document_id:
            id_to_title[d.document_id] = t
        if d.cross_references:
            xref_map[t] = d.cross_references
    return xref_map, id_to_title, title_to_jur


def jurs_of(nodes, title_to_jur):
    out = set()
    for n in nodes:
        dt = n.node.metadata.get("doc_title")
        j = n.node.metadata.get("jurisdiction") or title_to_jur.get(dt)
        if j:
            out.add(j)
    return out


def docs_of(nodes):
    return {n.node.metadata.get("doc_title") for n in nodes if n.node.metadata.get("doc_title")}


def gen_answer(query, nodes):
    """One-shot qwen2.5:7b answer grounded in the given chunks."""
    import requests
    ctx = "\n\n".join(
        f"[{n.node.metadata.get('jurisdiction','?')} · {n.node.metadata.get('article_ref') or n.node.metadata.get('doc_title','?')}]\n"
        + (n.node.text or "")[:700]
        for n in nodes
    )
    prompt = (
        "You are a compliance analyst. Using ONLY the sources below, answer the "
        "question. Cite the jurisdiction/article for each point. If sources from "
        "multiple jurisdictions apply, compare them.\n\n"
        f"SOURCES:\n{ctx}\n\nQUESTION: {query}\n\nANSWER:"
    )
    try:
        r = requests.post("http://localhost:11434/api/generate",
                          json={"model": "qwen2.5:7b", "prompt": prompt, "stream": False,
                                "options": {"temperature": 0.1, "num_predict": 320}},
                          timeout=180)
        return r.json().get("response", "").strip()
    except Exception as exc:
        return f"(answer generation failed: {exc})"


def main():
    xref_map, id_to_title, title_to_jur = build_maps()
    svc = _get_service()
    print(f"Loaded {len(xref_map)} docs with cross-references, "
          f"{len(id_to_title)} document_id→title mappings.\n")

    agg = {"plain_docs": 0, "graph_docs": 0, "plain_jurs": 0, "graph_jurs": 0,
           "plain_linked": 0, "graph_linked": 0, "possible_linked": 0}

    for i, q in enumerate(QUESTIONS, 1):
        plain = svc.search(q, top_k=TOP_K, rerank=True)
        graph, info = expand_with_xrefs(list(plain), q, svc,
                                        xref_map=xref_map, id_to_title=id_to_title)

        # linked-doc recall: of the top hits' cross-referenced docs, how many
        # are present in each result set?
        linked = referenced_titles(plain, xref_map, id_to_title)
        plain_docs, graph_docs = docs_of(plain), docs_of(graph)
        plain_linked = len([t for t in linked if t in plain_docs])
        graph_linked = len([t for t in linked if t in graph_docs])

        pj, gj = jurs_of(plain, title_to_jur), jurs_of(graph, title_to_jur)

        print("=" * 78)
        print(f"Q{i}. {q}")
        print(f"  plain : {len(plain_docs)} docs · {len(pj)} jurisdictions {sorted(pj)}")
        print(f"  graph : {len(graph_docs)} docs · {len(gj)} jurisdictions {sorted(gj)}  (+{info['added']} linked chunks)")
        print(f"  linked-doc recall: plain {plain_linked}/{len(linked)}  →  graph {graph_linked}/{len(linked)}")
        if info["ref_titles"]:
            print(f"  added via links: {[t[:38] for t in info['ref_titles']]}")

        agg["plain_docs"] += len(plain_docs); agg["graph_docs"] += len(graph_docs)
        agg["plain_jurs"] += len(pj); agg["graph_jurs"] += len(gj)
        agg["plain_linked"] += plain_linked; agg["graph_linked"] += graph_linked
        agg["possible_linked"] += len(linked)

        if WANT_ANSWERS:
            print("\n  --- PLAIN answer ---")
            print("  " + gen_answer(q, plain).replace("\n", "\n  ")[:900])
            print("\n  --- GRAPH answer ---")
            print("  " + gen_answer(q, graph).replace("\n", "\n  ")[:900])
        print()

    n = len(QUESTIONS)
    print("=" * 78)
    print("AGGREGATE (avg per question)")
    print(f"  distinct docs    : plain {agg['plain_docs']/n:.1f}  →  graph {agg['graph_docs']/n:.1f}")
    print(f"  jurisdictions    : plain {agg['plain_jurs']/n:.1f}  →  graph {agg['graph_jurs']/n:.1f}")
    pl, gl, po = agg["plain_linked"], agg["graph_linked"], agg["possible_linked"]
    print(f"  linked-doc recall: plain {pl}/{po} ({100*pl/po if po else 0:.0f}%)  →  "
          f"graph {gl}/{po} ({100*gl/po if po else 0:.0f}%)")


if __name__ == "__main__":
    main()
