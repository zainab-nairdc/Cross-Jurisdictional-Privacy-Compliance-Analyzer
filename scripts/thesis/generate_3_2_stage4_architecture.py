"""Generate Section 3.2.4 System Architecture (Stage 4) as a Word document.

Output: thesis_docs/3_2_4_architecture.docx

Contents (kept deliberately lean — security depth lives in §3.2.5):
  3.2.4 System Architecture
    3.2.4.1 Architectural style          + Figure 15
    3.2.4.2 Components and responsibilities + Figure 16
    3.2.4.3 Configuration per component  + Component Configuration Table
    3.2.4.4 Architectural decisions      + Architectural Decisions Table
    3.2.4.5 Quality attributes           (prose, brief)
    3.2.4.6 Cross-cutting concerns       (prose, brief; security → §3.2.5)

Target: ~200 words main body so §3.2.5 cybersecurity has room.
Style follows the Stage 1–3 generators (navy headings, 2 cm margins).
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


NAVY = RGBColor(0x00, 0x25, 0x83)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK_GRAY = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x6B, 0x72, 0x80)


# ── Component Configuration table rows ───────────────────────────────────
COMPONENT_CONFIG_ROWS = [
    ('Web browser', 'Client', 'HTMX 2 + Alpine.js 3 + Chart.js; CSP allowlist'),
    ('Reverse proxy', 'Edge', 'TLS 1.3 termination; static asset caching; HTTPS on port 443'),
    ('Django ASGI', 'Application',
     'Python 3.13; port 8000; RBAC + 2FA + CSRF; SESSION_COOKIE_AGE = 28 800 s; '
     'IDLE_TIMEOUT = 1 800 s'),
    ('Background workers', 'Application',
     'Same Python venv; threading.Thread daemons for ingestion; subprocess '
     'dispatch for mapping / comparison jobs'),
    ('ChromaDB', 'Data',
     'HNSW vector index; BGE-small (384-dim); chroma_data/ on disk; '
     'collection "regulations"'),
    ('SQLite FTS5', 'Data',
     'BM25 keyword index; fts_chunks virtual table; jurisdiction filter at '
     'query time'),
    ('Django SQLite', 'Data',
     'db.sqlite3; WAL journaling; users, models, audit log; '
     'DB-backed sessions'),
    ('Ollama daemon', 'LLM service',
     'localhost:11434; default model llama3.2:1b; HTTP only to Django'),
    ('File storage', 'Data',
     'media/ (uploads), data/ (corpus), hf_cache/ (BGE model), '
     'chroma_data/ (vectors)'),
]


# ── Architectural Decisions table rows ───────────────────────────────────
DECISION_ROWS = [
    ('Hosting',
     'Cloud / Kubernetes',
     'Single-host on-premises',
     'No document or query may leave the host (confidentiality policy)'),
    ('Async dispatch',
     'Celery + Redis',
     'Fire-and-forget subprocess and daemon thread',
     'Avoids extra infrastructure; subprocess carries its own DB connections'),
    ('Relational store',
     'PostgreSQL',
     'SQLite with WAL journaling',
     'Single-machine deployment; backup is one folder'),
    ('Keyword index',
     'In-memory BM25 (LlamaIndex)',
     'Persistent SQLite FTS5 with filter pushdown',
     'hit_rate@5 0.95 vs 0.875 baseline; survives process restarts'),
    ('LLM provider',
     'Cloud-hosted LLM only',
     'Provider abstraction with local default',
     'Same confidentiality boundary; provider switch by env var (NFR-16)'),
    ('Retry policy',
     'Unlimited retry',
     'Bounded retries + deterministic SafeFallback',
     'Prevents multi-minute hangs; fallback returns a safe summary'),
]


# ── Style helpers ─────────────────────────────────────────────────────────

def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def set_run_style(run, *, bold=False, italic=False, color=NAVY, size=11):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)


def add_paragraph(doc, text, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    set_run_style(run, bold=bold, italic=italic, color=color, size=size)
    return p


def add_heading(doc, text, *, level=1):
    style_map = {1: 'Heading 2', 2: 'Heading 3', 3: 'Heading 4'}
    size_map = {1: 14, 2: 12, 3: 11}
    h = doc.add_paragraph(style=style_map[level])
    run = h.add_run(text)
    run.font.color.rgb = NAVY
    run.font.bold = True
    run.font.size = Pt(size_map[level])
    return h


def add_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(12)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_image(doc, image_path: Path, width_cm: float = 16.0):
    if not image_path.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f'[MISSING IMAGE: {image_path.name}]')
        set_run_style(run, bold=True, italic=True, color=MUTED, size=10)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(image_path), width=Cm(width_cm))


def add_table(doc, headers, rows, widths_cm):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)

    header_row = table.rows[0]
    for i, h in enumerate(headers):
        cell = header_row.cells[i]
        cell.text = h
        shade_cell(cell, '002583')
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            set_run_style(run, bold=True, color=WHITE, size=10)

    for r_idx, row_values in enumerate(rows, start=1):
        row = table.rows[r_idx]
        for c_idx, value in enumerate(row_values):
            cell = row.cells[c_idx]
            cell.text = str(value)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            for para in cell.paragraphs:
                for run in para.runs:
                    set_run_style(
                        run,
                        bold=(c_idx == 0),
                        color=DARK_GRAY,
                        size=9,
                    )


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '3_2_4_architecture.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'3_2_4_architecture_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    diagrams = base / 'diagrams'
    fig_15 = diagrams / 'Figure_15_LayeredArchitecture.drawio.png'
    fig_16 = diagrams / 'Figure_16_URLRoutesCatalog.drawio.png'

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, '3.2.4 System Architecture', level=1)

    # 3.2.4.1 Architectural style
    add_heading(doc, '3.2.4.1 Architectural style', level=2)
    add_paragraph(
        doc,
        'The system is a layered monolith with event-driven cross-cutting '
        'concerns. Six pipeline phases (ingestion, preprocessing, '
        'embedding, retrieval, reasoning, output) stack vertically; only '
        'the LLM call crosses the Django process boundary, and even that '
        'stays on localhost. Communication is mostly synchronous in-process '
        'Python calls; Django signals carry event-driven cascades '
        '(audit logging, gap reconciliation); WebSocket via Channels '
        'relays live ingestion progress to the browser.',
    )
    add_image(doc, fig_15, width_cm=15.0)
    add_caption(doc, 'Figure 15.', 'CJPCA Layered Architecture')

    # 3.2.4.2 Components and responsibilities
    add_heading(doc, '3.2.4.2 Components and responsibilities', level=2)
    add_paragraph(
        doc,
        'Five Python packages own the pipeline. Ingestion reads documents '
        'and writes the corpus; retrieval reads from the corpus and '
        'returns ranked chunks; reasoning takes those chunks and produces '
        'verified answers via the LangGraph agent; the web layer is a '
        'Django project of ten apps that orchestrates user-facing flows; '
        'and the copilot wraps the reasoning agent behind a chat interface '
        'that reuses approved evidence. Figure 16 lists the user-facing '
        'URL routes grouped by Django app, with HTTP method colour-coded.',
    )
    add_image(doc, fig_16, width_cm=15.0)
    add_caption(doc, 'Figure 16.', 'Django URL Routes Catalog')

    # 3.2.4.3 Configuration per component (~25 words + table)
    add_heading(doc, '3.2.4.3 Configuration per component', level=2)
    add_paragraph(
        doc,
        'The configuration of each component on the host is summarised '
        'below. Values are pulled from the project\'s settings and config '
        'modules.',
    )
    add_caption(doc, 'Table 8.', 'Component Configuration')
    add_table(
        doc,
        ['Component', 'Tier', 'Configuration'],
        COMPONENT_CONFIG_ROWS,
        widths_cm=[3.5, 2.5, 10.5],
    )

    # 3.2.4.4 Architectural decisions and trade-offs (~25 words + table)
    add_heading(doc, '3.2.4.4 Architectural decisions and trade-offs',
                level=2)
    add_paragraph(
        doc,
        'Table 9 captures the design decisions that gave the system its '
        'current shape, with the alternatives considered and the rationale.',
    )
    add_caption(doc, 'Table 9.', 'Architectural Decisions')
    add_table(
        doc,
        ['Decision', 'Alternative considered', 'Chosen', 'Rationale'],
        DECISION_ROWS,
        widths_cm=[3.0, 3.5, 4.0, 6.0],
    )

    # 3.2.4.5 Quality attributes (~50 words)
    add_heading(doc, '3.2.4.5 Quality attributes', level=2)
    add_paragraph(
        doc,
        'Performance is supported by persistent indexes (HNSW, FTS5) and '
        'a bounded reasoning loop. Scalability is bounded by the single '
        'host but DB-backed sessions handle the working analyst '
        'population. Maintainability comes from layer isolation and '
        'Pydantic schemas at module boundaries. Recoverability is provided '
        'by SQLite WAL, a stuck-job recovery command, and the audit-hash '
        'chain on exports.',
    )

    # 3.2.4.6 Cross-cutting concerns (~25 words; security → §3.2.5)
    add_heading(doc, '3.2.4.6 Cross-cutting concerns', level=2)
    add_paragraph(
        doc,
        'Audit logging, structured per-job logs, signal-based cascades '
        '(Algorithm A.7.2.a), and centralised error handling run across '
        'every layer. The security architecture is the subject of §3.2.5.',
    )

    doc.save(out_path)
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
