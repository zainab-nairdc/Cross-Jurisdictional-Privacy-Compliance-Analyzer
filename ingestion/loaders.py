"""turns pdf/docx files into markdown using docling.

we only read the text layer — no ocr. so if someone hands us a scanned pdf
with no text layer, the result comes back empty, and the orchestrator
(scripts/load_all.py) catches that by checking the output size.

the one function you actually call from outside is load_document(path).
"""
import os
import hashlib
from dataclasses import dataclass
from pathlib import Path

# keep docling's onnx threads quiet so it doesn't fight the embedder for cpu.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")


@dataclass(frozen=True)
class LoadedDocument:
    text:         str
    content_hash: str
    page_count:   int
    source:       Path


_SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md"}

_converter = None


def _get_converter():
    """build the docling converter once and reuse it for every doc.
    starting docling fresh each time would be slow and waste memory."""
    global _converter
    if _converter is not None:
        return _converter

    try:
        from docling.document_converter   import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except ImportError as e:
        raise ImportError(
            "Docling not installed. Run: "
            ".venv\\Scripts\\python.exe -m pip install docling"
        ) from e

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr             = False
    pipeline_options.do_table_structure = True

    _converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
    return _converter


def load_document(path: Path) -> LoadedDocument:
    """take a file path, hand it to docling, get markdown back.
    no ocr fallback — if there's no text layer, you get an empty string."""
    if path.suffix.lower() not in _SUPPORTED:
        raise ValueError(f"Unsupported file type: {path.suffix} — {path.name}")

    converter   = _get_converter()
    conv_result = converter.convert(str(path))
    text        = conv_result.document.export_to_markdown()
    page_count  = len(conv_result.document.pages) if hasattr(conv_result.document, "pages") else 0

    return LoadedDocument(
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        page_count=max(page_count, 0),
        source=path,
    )
