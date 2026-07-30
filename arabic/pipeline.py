"""End-to-end Arabic ingestion: PDF -> Chroma (regulations_ar).

    extract (PyMuPDF) -> normalize -> chunk -> embed (bge-m3) -> store (Chroma)

One call: ``ingest(pdf_path, source, law_name)``. Re-running on the same
``source`` cleanly replaces its chunks (delete-then-add), so a re-ingest after
tuning the extractor/regex never leaves duplicates.
"""
from pathlib import Path

from .extract import extract_arabic
from .normalize import normalize
from .chunk import chunk_arabic, embed_text
from .embed import embed_texts
from . import store


def ingest(pdf_path, source: str, law_name: str = "",
           min_arabic_ratio: float = 0.5, use_ocr: bool = False) -> dict:
    """Ingest one Arabic PDF into the isolated collection. Returns a summary.

    ``use_ocr=True`` runs kraken OCR instead of text extraction — required for
    PDFs whose text layer is corrupted by a broken font (extraction returns
    garbled Arabic; OCR reads the rendered pixels and comes out clean).
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"ok": False, "error": f"file not found: {pdf_path}"}

    if use_ocr:
        from .ocr_kraken import ocr_pdf
        raw = ocr_pdf(pdf_path)
    else:
        raw = extract_arabic(pdf_path, min_arabic_ratio=min_arabic_ratio)
    clean = normalize(raw)
    if len(clean) < 50:
        return {"ok": False, "error": "extraction produced almost no Arabic text "
                "— likely a scanned PDF or a broken text layer (no OCR here)."}

    chunks = chunk_arabic(clean, source=source, law_name=law_name)
    if not chunks:
        return {"ok": False, "error": "no chunks produced from extracted text."}

    n_articles = sum(1 for c in chunks if c["chunk_type"] == "article")
    n_defs = sum(1 for c in chunks if c["chunk_type"] == "definition")

    texts = [embed_text(c) for c in chunks]
    vectors = embed_texts(texts)

    ids, docs, metas = [], [], []
    for i, c in enumerate(chunks):
        ids.append(f"{source}::{c['chunk_type']}::{c.get('article_number')}::{i}")
        docs.append(c["text"])
        metas.append(c)

    store.delete_source(source)          # clean replace on re-ingest
    store.add(ids, vectors, docs, metas)

    return {
        "ok": True, "source": source, "chunks": len(chunks),
        "articles": n_articles, "definitions": n_defs,
        "arabic_chars": sum(1 for ch in clean if "؀" <= ch <= "ۿ"),
        "no_article_headings": (n_articles == 1 and chunks[0].get("article_number") is None),
    }
