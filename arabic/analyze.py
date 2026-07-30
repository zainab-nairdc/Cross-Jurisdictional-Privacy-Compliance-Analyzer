"""Document structure analysis — powers the confirm-before-ingest workflow.

Before committing to ingestion, the upload UI shows the user what the system
detected: language, a structure summary (parts / sections / articles /
definitions), a nested hierarchy tree (the "Structure Preview" screen), and a
suggested document type. The user confirms or overrides, THEN we finalize.

This is the generic "Legal Node" view: every chunk is a node with a type
(article / definition / …), a place in the hierarchy (part > section), and a
citation label. Today it reads the Arabic legal structure (الباب / الفصل /
مادة); the same shape extends to clauses (contracts) and numbered sections
(policies) by swapping the marker profile in chunk.py.
"""
from collections import OrderedDict

from .detect import detect_language, needs_ocr
from .extract import extract_arabic
from .normalize import normalize
from .chunk import chunk_arabic


def structure_summary(chunks: list[dict]) -> dict:
    """Roll a chunk list up into counts + a part > section > node tree."""
    parts: "OrderedDict[str, OrderedDict]" = OrderedDict()
    sections: set = set()
    articles = definitions = 0

    for c in chunks:
        ctype = c.get("chunk_type")
        if ctype == "definition":
            definitions += 1
        elif ctype == "article":
            articles += 1

        part = (c.get("part") or "").strip() or "Articles"
        sec = (c.get("section") or "").strip()
        if sec:
            sections.add((part, sec))

        sec_map = parts.setdefault(part, OrderedDict())
        leaf = sec_map.setdefault(sec or "—", [])
        num = c.get("article_number")
        label = c.get("term") if ctype == "definition" else (
            f"Article ({num})" if isinstance(num, int) else (c.get("article_title") or "Section")
        )
        leaf.append({
            "type": ctype or "node",
            "number": num,
            "label": label,
            "title": (c.get("article_title") or "")[:70],
        })

    return {
        "parts": len(parts),
        "sections": len(sections),
        "articles": articles,
        "definitions": definitions,
        "total_nodes": len(chunks),
        "tree": parts,   # {part: {section: [nodes]}}
    }


def suggest_type(summary: dict) -> str:
    """Heuristic document-type suggestion from the detected structure."""
    if summary["articles"] and summary["parts"] > 1:
        return "law"            # articles organised into multiple parts
    if summary["articles"]:
        return "regulation"     # article-structured but flat
    return "other"


def analyze(pdf_path, declared_language: str | None = None) -> dict:
    """Full pre-ingest analysis of a PDF. Returns language, whether OCR was
    needed, the structure summary/tree, a suggested type, and the chunks
    themselves (cached so the confirm step can embed without re-extracting).
    """
    lang = declared_language or detect_language(pdf_path)
    out: dict = {"language": lang}

    if lang == "ar":
        use_ocr = needs_ocr(pdf_path)
        if use_ocr:
            from .ocr_kraken import ocr_pdf
            raw = ocr_pdf(pdf_path)
        else:
            raw = extract_arabic(pdf_path)
        chunks = chunk_arabic(normalize(raw), source="_analyze_")
        summary = structure_summary(chunks)
        out.update({
            "used_ocr": use_ocr,
            "structure": summary,
            "suggested_type": suggest_type(summary),
            "chunks": chunks,
        })
    else:
        out.update({"note": "English structure analysis not wired yet"})
    return out
