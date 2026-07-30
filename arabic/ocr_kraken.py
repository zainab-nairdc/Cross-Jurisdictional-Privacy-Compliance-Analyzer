"""Kraken OCR extraction — the fix for PDFs with a broken text layer.

When a PDF's font encoding is damaged (glyphs map to the wrong Unicode, so
PyMuPDF/PDFium return garbled Arabic), text extraction cannot be salvaged — the
data itself is wrong. OCR sidesteps it entirely: we render each page to an
image and read the *pixels*, which display correctly regardless of the broken
font.

Kraken (with the `arabic_best` recognition model) gives markedly cleaner Arabic
than easyocr on these documents. It has heavy, version-pinned dependencies that
conflict with the main CJPCA venv, so it lives in its OWN venv and we call its
CLI as a subprocess — the main process only renders images (PyMuPDF) and reads
back text. Nothing kraken touches the main environment.

Paths default to the sandbox venv + htrmopo model cache and are overridable via
env vars (KRAKEN_EXE, KRAKEN_ARABIC_MODEL) for other machines / deployment.
"""
import os
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF — rendering only, runs in the main venv

# Isolated kraken CLI (its deps conflict with the main venv — keep it separate).
KRAKEN_EXE = os.environ.get(
    "KRAKEN_EXE",
    r"c:\Users\zainab.hammad\projects\arabic-rag-sandbox\.venv-kraken\Scripts\kraken.exe",
)
# Arabic recognition model (baseline segmentation uses kraken's bundled blla).
ARABIC_MODEL = os.environ.get(
    "KRAKEN_ARABIC_MODEL",
    r"c:\Users\zainab.hammad\AppData\Local\htrmopo\htrmopo"
    r"\b4a70336-339f-508b-abf4-24b698091dd7\arabic_best.mlmodel",
)

# Render zoom. PDF is 72 dpi; zoom 3.0 -> ~216 dpi, which matched the sandbox's
# validated kraken runs. Bump toward 4.0 (~288 dpi) for small/dense type.
DEFAULT_ZOOM = 3.0


def _render_pages(pdf_path: Path, out_dir: Path, zoom: float) -> list[Path]:
    """Rasterize every page to a PNG. Returns the image paths in page order."""
    doc = fitz.open(str(pdf_path))
    pngs = []
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            p = out_dir / f"page_{i:03d}.png"
            pix.save(str(p))
            pngs.append(p)
    finally:
        doc.close()
    return pngs


def check_available() -> tuple[bool, str]:
    """Verify the kraken CLI and Arabic model are present before a long run."""
    if not Path(KRAKEN_EXE).exists():
        return False, f"kraken CLI not found at {KRAKEN_EXE} (set KRAKEN_EXE)"
    if not Path(ARABIC_MODEL).exists():
        return False, f"Arabic model not found at {ARABIC_MODEL} (set KRAKEN_ARABIC_MODEL)"
    return True, "ok"


def ocr_pdf(pdf_path, zoom: float = DEFAULT_ZOOM,
            kraken_exe: str = KRAKEN_EXE, model: str = ARABIC_MODEL,
            base_dir: str = "R", max_pages: int | None = None) -> str:
    """OCR a PDF with kraken and return the full Arabic text.

    All pages are OCR'd in ONE kraken invocation so the recognition model loads
    only once (the slow part). ``max_pages`` limits the run for a quick probe.

    ``base_dir="R"`` is essential: without it kraken auto-detects direction and
    emits Arabic in VISUAL (reversed) order (المادة -> ةداملا). Forcing RTL base
    direction produces correct logical order.
    """
    ok, msg = check_available()
    if not ok:
        raise RuntimeError(msg)

    pdf_path = Path(pdf_path)
    with tempfile.TemporaryDirectory(prefix="krakenocr_") as td:
        td = Path(td)
        pngs = _render_pages(pdf_path, td, zoom=zoom)
        if max_pages:
            pngs = pngs[:max_pages]

        # kraken CLI: `kraken -i IN OUT [-i IN OUT ...] segment -bl ocr -m MODEL`
        args = [kraken_exe]
        outs = []
        for png in pngs:
            out = png.with_suffix(".txt")
            outs.append(out)
            args += ["-i", str(png), str(out)]
        args += ["segment", "-bl", "ocr", "-m", model, "--base-dir", base_dir]

        # kraken prints Unicode progress marks (✓); force UTF-8 so it doesn't
        # crash on Windows' cp1252 console — that silently aborts kraken BEFORE
        # it writes the output files (exit 0, empty result).
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.run(args, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"kraken failed (exit {proc.returncode}): {proc.stderr[-500:]}"
            )

        texts = [out.read_text(encoding="utf-8") for out in outs if out.exists()]
        return "\n\n".join(texts).strip()


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    pdf = sys.argv[1] if len(sys.argv) > 1 else "data/raw/qatar_pdpl_arabic.pdf"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    print(f"OCR (kraken) first {pages} page(s) of {pdf} ...")
    print(ocr_pdf(pdf, max_pages=pages)[:800])
