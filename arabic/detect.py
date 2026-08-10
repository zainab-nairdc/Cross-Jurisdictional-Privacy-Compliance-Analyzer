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


# Legacy Arabic typefaces that predate Unicode. They draw Arabic glyphs from
# Latin code points, so a PDF built with them extracts as Latin gibberish
# ("IOÉ``ŸG" for "المادة") no matter which extractor reads it.
_ARABIC_FONT_HINTS = (
    "axt", "arabic", "arabtype", "simplified", "traditional", "decotype",
    "sakkal", "majalla", "ge_ss", "ge ss", "naskh", "kufi", "thuluth",
    "diwani", "amiri", "lateef", "scheherazade", "mcs", "hacen",
)


def _page_fonts(doc, sample_pages: int) -> list[str]:
    """Font names used on the sampled pages, lowercased. Subset prefixes
    ("AAAAAB+AXtManalBold") are kept as-is; the hint match is a substring test."""
    names = []
    for i in range(min(sample_pages, len(doc))):
        try:
            names += [str(f[3]).lower() for f in doc[i].get_fonts(full=True)]
        except Exception:
            continue
    return names


def _junk_ratio(letters: list[str]) -> float:
    """Share of letters that are Latin-1 supplement oddities (À-ÿ). Real English
    prose is ~0; text drawn from a legacy Arabic font is dominated by them."""
    if not letters:
        return 0.0
    return sum(1 for c in letters if 0x00C0 <= ord(c) <= 0x00FF) / len(letters)


def text_layer_is_broken(pdf_path, sample_pages: int = 5) -> bool:
    """True when the PDF HAS a text layer but it can't be trusted.

    The Oman PDPL is the reference case: Type1 `AXtManal*` fonts with
    MacRomanEncoding and no ToUnicode CMap. Every page extracts 1000+ characters
    of Latin punctuation soup with an Arabic ratio of exactly 0.000, so a
    language check that only counts Arabic characters concludes "English" and
    sends a 10-page Arabic law down the English pipeline.
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return False
    try:
        text = "".join(doc[i].get_text("text") for i in range(min(sample_pages, len(doc))))
        letters = [c for c in text if c.isalpha()]
        if len(letters) < 50:
            return False                      # no text layer at all — not our case
        if any(_is_arabic_char(c) for c in letters):
            return False                      # real Arabic came through
        font_names = _page_fonts(doc, sample_pages)
    finally:
        doc.close()
    legacy_arabic_font = any(h in n for n in font_names for h in _ARABIC_FONT_HINTS)
    return legacy_arabic_font and _junk_ratio(letters) > 0.15


def detect_language(pdf_path, sample_pages: int = 5, threshold: float = 0.30) -> str:
    """Return 'ar' if the document is predominantly Arabic, else 'en'.

    Looks at the ALL text of the first few pages (not just Arabic blocks) and
    measures the share of alphabetic characters that are Arabic. A threshold of
    0.30 comfortably separates an Arabic law (mostly Arabic) from an English one
    with the odd Arabic word in a header.
    """
    # PyMuPDF only opens PDFs (and a few image formats). A non-PDF the caller
    # passed by mistake — most commonly a legacy .doc — raises here; treat that as
    # "can't tell" and default to the English path rather than crashing the whole
    # analyze / ingestion job. Real format rejection happens up front in the view.
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return "en"
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
    if arabic_ratio >= threshold:
        return "ar"
    # Zero Arabic found, but the text layer may be unreadable rather than English.
    # Decided from the FONTS, which stay legible when the glyph mapping doesn't:
    # a legacy Arabic typeface means an Arabic document, and routing it to 'ar'
    # lets needs_ocr() take over and read the pixels instead.
    if text_layer_is_broken(pdf_path, sample_pages):
        return "ar"
    return "en"


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
