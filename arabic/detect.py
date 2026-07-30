"""Auto-detection for the upload pipeline: language + extraction health.

Two questions the ingestion flow must answer from the file alone:
  1. detect_language(pdf) -> 'ar' | 'en'   (which pipeline to use)
  2. needs_ocr(pdf)       -> True | False   (is the text layer usable, or broken?)

These are deliberately cheap (they read only a few pages) and are the shared
foundation the document-classifier will build on later.
"""
import fitz  # PyMuPDF

from .extract import extract_arabic
from .normalize import normalize


def _is_arabic_char(c: str) -> bool:
    """True for Arabic in ANY encoding: the standard block, Supplement/Extended,
    AND the Presentation Forms (U+FB50-FDFF / U+FE70-FEFF) that some PDFs (e.g.
    the Saudi PDPL) store instead of the logical codepoints. Missing the
    presentation forms makes an Arabic doc look non-Arabic and mis-routes it."""
    o = ord(c)
    return (0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or
            0x08A0 <= o <= 0x08FF or 0xFB50 <= o <= 0xFDFF or
            0xFE70 <= o <= 0xFEFF)


def detect_language(pdf_path, sample_pages: int = 5, threshold: float = 0.30) -> str:
    """Return 'ar' if the document is predominantly Arabic, else 'en'.

    Looks at the ALL text of the first few pages (not just Arabic blocks) and
    measures the share of alphabetic characters that are Arabic. A threshold of
    0.30 comfortably separates an Arabic law (mostly Arabic) from an English one
    with the odd Arabic word in a header.
    """
    doc = fitz.open(str(pdf_path))
    try:
        text = "".join(
            doc[i].get_text("text") for i in range(min(sample_pages, len(doc)))
        )
    finally:
        doc.close()

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"  # no text layer (scan/empty) — default to the English path
    arabic_ratio = sum(_is_arabic_char(c) for c in letters) / len(letters)
    return "ar" if arabic_ratio >= threshold else "en"


def _arabic_tokens(text: str) -> list[str]:
    return [w for w in text.split() if any(_is_arabic_char(c) for c in w)]


def needs_ocr(pdf_path, min_ala: int = 3) -> bool:
    """True if the (Arabic) text layer looks corrupted and should be OCR'd.

    Signal: the word "على" ("on/upon") is the most common word in Arabic legal
    text — it appears dozens of times in any real law. A broken font encoding
    corrupts every instance (على -> عىل), so its near-absence in an otherwise-
    Arabic document is a reliable "the text layer is broken" flag. Calibrated on
    the Qatar PDPL: broken extraction had على=0, clean OCR had على=52.

    Only meaningful for Arabic docs — call after detect_language() == 'ar'.
    """
    text = normalize(extract_arabic(pdf_path))
    tokens = _arabic_tokens(text)
    if len(text) < 50 or len(tokens) < 20:
        return True  # no real text layer (scan/empty) -> OCR is the safe choice
    return text.count("على") < min_ala


def report(pdf_path) -> dict:
    """Convenience: both signals at once (used by the CLI/tests)."""
    lang = detect_language(pdf_path)
    text = normalize(extract_arabic(pdf_path))
    return {
        "language": lang,
        "ala_count": text.count("على"),   # correct "على" occurrences
        "needs_ocr": needs_ocr(pdf_path) if lang == "ar" else False,
    }
