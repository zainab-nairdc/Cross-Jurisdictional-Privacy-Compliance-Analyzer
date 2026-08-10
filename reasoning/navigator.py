"""Navigator-lite — structure-aware retrieval ("read like a person").

Ordinary retrieval matches flat chunks by similarity. This instead reads a
document the way a person would: look at the OUTLINE (its section headings),
reason about which section holds the answer, open just that section, and read
it — with its heading path still attached. It reuses the article structure the
chunker already stored in Chroma, so there is no re-parsing.

Designed as the *hybrid* the structure-RAG literature recommends: similarity
finds the right DOCUMENT; this navigates WITHIN it. It augments retrieval — it
never has to be the only source.

100% local: section selection uses the local Ollama model (via
``reasoning.doc_intel._chat_json``). Every function fails soft (returns []),
so a hiccup degrades to ordinary similarity retrieval, never an error.
"""
from __future__ import annotations

import re

_MAX_SECTIONS = 3        # sections opened per question
_MIN_OUTLINE = 3         # below this the doc is too flat to navigate — use search
_PREVIEW_CHARS = 140


def _collection():
    import chromadb
    from config import CHROMA_DIR, CHROMA_COLLECTION
    return chromadb.PersistentClient(path=str(CHROMA_DIR)).get_or_create_collection(
        CHROMA_COLLECTION)


def build_outline(doc_title: str) -> list[dict]:
    """The document's table of contents, reconstructed from its indexed chunks:
    one entry per section in document order, each with a short text preview so
    the model can judge relevance without reading the body. No re-parsing."""
    col = _collection()
    r = col.get(where={"doc_title": doc_title},
                include=["metadatas", "documents"], limit=5000)
    if not r["ids"]:
        return []
    order: dict[str, int] = {}
    preview: dict[str, str] = {}
    hpath: dict[str, str] = {}
    for meta, text in zip(r["metadatas"], r["documents"]):
        ref = (meta.get("article_ref") or meta.get("section_title") or "").strip()
        if not ref:
            continue
        idx = meta.get("chunk_index", 0) or 0
        if ref not in order or idx < order[ref]:
            order[ref] = idx
        # keep the earliest (lowest chunk_index) preview for the section
        if ref not in preview or idx <= order[ref]:
            if text:
                preview[ref] = re.sub(r"\s+", " ", text).strip()[:_PREVIEW_CHARS]
                hpath[ref] = (meta.get("hierarchy_path") or "").strip()
    return [{"ref": ref, "preview": preview.get(ref, ""), "hpath": hpath.get(ref, "")}
            for ref in sorted(order, key=lambda k: order[k])]


_SELECT_PROMPT = """You are navigating a legal/regulatory document to answer a
question — the way a person flips to the right section instead of reading the
whole thing. Below is the document's outline: each line is a section heading and
a short preview of what it contains.

QUESTION: {question}

OUTLINE:
{outline}

Choose ONLY the 1-3 sections most likely to contain the answer. Use the section
headings EXACTLY as written above. If none look relevant, return an empty list.
Return JSON: {{"refs": ["<heading>", ...]}}"""


def select_sections(question: str, outline: list[dict],
                    max_sections: int = _MAX_SECTIONS) -> list[str]:
    """One local-LLM call: which section(s) should we open? Returns the chosen
    heading refs (validated against the outline)."""
    if not outline:
        return []
    from reasoning.doc_intel import _chat_json
    lines = "\n".join(f"- {o['ref']}: {o['preview']}" for o in outline)
    data = _chat_json(_SELECT_PROMPT.format(question=question, outline=lines))
    refs = data.get("refs") if isinstance(data, dict) else None
    if not isinstance(refs, list):
        return []
    valid = {o["ref"] for o in outline}
    picked, seen = [], set()
    for r in refs:
        r = str(r).strip()
        if r in valid and r not in seen:
            picked.append(r)
            seen.add(r)
    return picked[:max_sections]


def read_sections(doc_title: str, refs: list[str]):
    """Read the FULL text of each selected section (all its chunks stitched in
    order — or the section parent when present) and return NodeWithScore objects
    so they slot straight into the answer pipeline, heading path intact."""
    from llama_index.core.schema import TextNode, NodeWithScore
    col = _collection()
    nodes = []
    for ref in refs:
        r = col.get(where={"$and": [{"doc_title": doc_title}, {"article_ref": ref}]},
                    include=["metadatas", "documents"], limit=500)
        if not r["ids"]:
            continue
        parts = sorted(zip(r["metadatas"], r["documents"]),
                       key=lambda mt: mt[0].get("chunk_index", 0) or 0)
        parent = next((t for m, t in parts if m.get("embed_skip") and t), None)
        text = parent or "\n".join(t for m, t in parts if not m.get("embed_skip") and t)
        if not (text or "").strip():
            continue
        m0 = parts[0][0]
        node = TextNode(
            text=text,
            id_=m0.get("node_id") or f"{doc_title}::{ref}",
            metadata={
                "node_id":         m0.get("node_id") or f"{doc_title}::{ref}",
                "doc_title":       doc_title,
                "article_ref":     ref,
                "section_title":   ref,
                "hierarchy_path":  m0.get("hierarchy_path", ""),
                "regulation_name": m0.get("regulation_name", ""),
                "jurisdiction":    m0.get("jurisdiction", ""),
                "doc_type":        m0.get("doc_type", ""),
                "_navigator":      True,      # marks structure-navigated context
            },
        )
        nodes.append(NodeWithScore(node=node, score=1.0))
    return nodes


def navigate(question: str, doc_title: str, max_sections: int = _MAX_SECTIONS):
    """Full navigator-lite pass for one document: outline -> select -> read.

    Returns a list of NodeWithScore (full sections with their headings), or []
    when navigation isn't applicable (doc too flat, nothing selected, or any
    error) — in which case the caller keeps its ordinary similarity results."""
    try:
        outline = build_outline(doc_title)
        if len(outline) < _MIN_OUTLINE:
            return []
        refs = select_sections(question, outline, max_sections)
        if not refs:
            return []
        return read_sections(doc_title, refs)
    except Exception:
        return []


def top_doc_title(nodes) -> str | None:
    """The doc_title of the highest-ranked retrieved node — the document the
    hybrid step navigates within."""
    for n in nodes or []:
        dt = (getattr(n, "node", n).metadata or {}).get("doc_title")
        if dt:
            return dt
    return None
