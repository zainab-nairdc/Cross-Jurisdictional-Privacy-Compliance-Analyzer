"""Arabic text normalization for extracted PDF text.

Cleans the common extraction artifacts (reordered alef-lam ligatures, digits
glued to words, tatweel, stray page numbers) while KEEPING line breaks so the
chunker can still see article/section headings on their own lines.

Deliberately light: we do NOT strip diacritics or fold letter shapes
aggressively — bge-m3 handles those, and over-normalizing hurts the faithful
Arabic we display and cite. The authoritative text stored for display should be
the lightly-normalized form, not a shape-folded one.
"""
import re
import unicodedata

_ARABIC = r"؀-ۿ"

# Arabic-Indic (٠-٩) and Extended (۰-۹) digits -> Western, so article numbers
# parse regardless of how the PDF encoded them.
_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# Extraction frequently reorders the definite article ال when it precedes a
# hamza/alef form, producing these glued sequences. Map them back.
_LIGATURE_FIXES = {
    "اإل": "الإ",
    "األ": "الأ",
    "اال": "الا",
    "اآل": "الآ",
}


def western_digits(s: str) -> str:
    """Convert Arabic-Indic / Extended digits to Western 0-9."""
    return (s or "").translate(_DIGIT_MAP)


def normalize(text: str) -> str:
    """Return cleaned Arabic text suitable for chunking + embedding."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    # OCR recognition models sometimes emit the Persian yeh/kaf for the Arabic
    # ones (فی -> في). Fold them to the Arabic forms.
    text = text.replace("ی", "ي").replace("ک", "ك")
    for bad, good in _LIGATURE_FIXES.items():
        text = text.replace(bad, good)

    # un-glue digits from Arabic letters:  رقم30 -> رقم 30
    text = re.sub(rf"([{_ARABIC}])(\d)", r"\1 \2", text)
    text = re.sub(rf"(\d)([{_ARABIC}])", r"\1 \2", text)

    # drop bare page numbers alone on a line (1-3 digits); 4-digit years survive
    text = re.sub(r"(?m)^[ \t]*\d{1,3}[ \t]*$", "", text)

    # drop "--- page N ---" style page markers some extractors inject
    text = re.sub(r"(?im)^-*\s*page\s*\d+\s*-*$", "", text)

    text = text.replace("�", "")   # replacement char from bad glyphs
    text = text.replace("ـ", "")         # tatweel (kashida) — decorative only

    # tidy whitespace but PRESERVE newlines (headings live on their own lines)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


if __name__ == "__main__":
    sample = "المــادة رقم30 الآلِيَّة"
    print("IN :", sample)
    print("OUT:", normalize(sample))
    print("digits:", western_digits("المادة ٤٢"))
