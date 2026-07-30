"""Arabic text extraction from PDFs — layout-agnostic (PyMuPDF).

Generalized from the sandbox's hardcoded bilingual column split (which assumed
the Arabic column started at x=420 in one specific Bahrain PDF). Instead of a
fixed split, we keep only the text BLOCKS that are predominantly Arabic and
reassemble them in reading order. This handles:

  - Arabic-only PDFs        -> every block is Arabic, we keep all of it
  - bilingual two-column    -> the English column + Latin headers/footers are
                               dropped automatically (low Arabic ratio), no
                               matter which side the Arabic column is on

No OCR: this reads the text layer only. If a PDF is a scan, extraction returns
(near-)empty and the caller should report it — same contract as the main loader.
"""
import re
from pathlib import Path

import fitz  # PyMuPDF

# Arabic in any encoding: standard block, Supplement/Extended, AND the
# Presentation Forms some PDFs store (U+FB50-FDFF / U+FE70-FEFF).
_ARABIC_CHAR = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def _arabic_ratio(s: str) -> float:
    """Fraction of alphabetic characters that are Arabic. 0.0 for no letters."""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _ARABIC_CHAR.match(c)) / len(letters)


def extract_arabic(pdf_path, min_arabic_ratio: float = 0.5) -> str:
    """Extract the Arabic-dominant text from a PDF, in reading order.

    ``min_arabic_ratio`` is the share of a block's letters that must be Arabic
    for the block to be kept. 0.5 drops English columns and Latin page
    furniture while keeping Arabic text that contains the odd Latin token
    (numbers, an English acronym).
    """
    doc = fitz.open(str(pdf_path))
    pages_out = []
    try:
        for page in doc:
            blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,block_no,type)
            kept = [
                b for b in blocks
                if len(b) >= 5 and (b[4] or "").strip()
                and _arabic_ratio(b[4]) >= min_arabic_ratio
            ]
            # Reading order: group into horizontal bands top-to-bottom (y),
            # then right-to-left within a band (Arabic columns read RTL). The
            # y-rounding tolerates minor baseline jitter within a line.
            kept.sort(key=lambda b: (round(b[1] / 10.0), -b[0]))
            page_text = "\n".join((b[4] or "").strip() for b in kept)
            if page_text.strip():
                pages_out.append(page_text)
    finally:
        doc.close()
    return "\n\n".join(pages_out)


def extraction_report(pdf_path) -> dict:
    """Diagnostics for a probe run — helps decide if extraction is usable
    before committing to ingest (Arabic extraction quality is the #1 risk)."""
    doc = fitz.open(str(pdf_path))
    try:
        pages = len(doc)
        arabic = extract_arabic(pdf_path)
    finally:
        doc.close()
    return {
        "path": str(pdf_path),
        "pages": pages,
        "arabic_chars": len(_ARABIC_CHAR.findall(arabic)),
        "total_chars": len(arabic),
        "preview": arabic[:400],
    }


if __name__ == "__main__":
    import sys
    import json
    p = sys.argv[1] if len(sys.argv) > 1 else "data/raw/arabic_pdpl_good.pdf"
    print(json.dumps(extraction_report(p), ensure_ascii=False, indent=2))
