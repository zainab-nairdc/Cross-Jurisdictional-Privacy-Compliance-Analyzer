"""Lightweight GraphRAG-style cross-reference expansion.

Classic vector/BM25 retrieval finds chunks that are *similar* to the query. It
cannot follow the explicit links a legal corpus already encodes — "this clause
implements Article 14 of the parent law", "this policy is governed by these
three regulations". Those links live in ``Document.cross_references`` as a list
of ``document_id`` codes (e.g. "BH-PDPA-O43; IN-DPDP-RULES:Rule.7").

This module adds a single graph hop on top of ordinary retrieval: for the top
hits, resolve their cross-referenced documents and pull the query-relevant chunk
from each. That surfaces *connected* context a flat search would miss — without
the cost of building/maintaining a full knowledge graph.
"""
import re

_SPLIT = re.compile(r"[;,]")


def parse_xref_ids(cross_references: str) -> list[str]:
    """"BH-PDPA-O43; IN-DPDP-RULES:Rule.7" -> ["BH-PDPA-O43", "IN-DPDP-RULES"]."""
    ids: list[str] = []
    for part in _SPLIT.split(cross_references or ""):
        part = part.strip()
        if not part:
            continue
        docid = part.split(":")[0].strip()   # drop the :Art.X / :Rule.Y suffix
        if docid and docid not in ids:
            ids.append(docid)
    return ids


def referenced_titles(nodes, xref_map: dict, id_to_title: dict, *,
                      from_top: int = 3, max_refs_per_doc: int = 4) -> list[str]:
    """The doc_titles cross-referenced by the top ``from_top`` result docs,
    excluding docs already present in ``nodes``."""
    seen = {n.node.metadata.get("doc_title") for n in nodes if n.node.metadata.get("doc_title")}
    out: list[str] = []
    for n in nodes[:from_top]:
        dt = n.node.metadata.get("doc_title")
        for docid in parse_xref_ids(xref_map.get(dt, ""))[:max_refs_per_doc]:
            t = id_to_title.get(docid)
            if t and t not in seen and t not in out:
                out.append(t)
    return out


def expand_with_xrefs(nodes, query, service, *, xref_map, id_to_title,
                      from_top: int = 3, max_refs_per_doc: int = 4, per_ref_k: int = 1):
    """Return (combined_nodes, info). Appends one query-relevant chunk per
    cross-referenced document, each tagged ``metadata['_xref'] = True``."""
    ref_titles = referenced_titles(nodes, xref_map, id_to_title,
                                   from_top=from_top, max_refs_per_doc=max_refs_per_doc)
    added = []
    for t in ref_titles:
        try:
            extra = service.search(query, top_k=per_ref_k, doc_titles=[t],
                                   rerank=True, expand_synonyms=False)
        except Exception:
            extra = []
        for e in extra:
            e.node.metadata["_xref"] = True
            added.append(e)
    return nodes + added, {"ref_titles": ref_titles, "added": len(added)}
