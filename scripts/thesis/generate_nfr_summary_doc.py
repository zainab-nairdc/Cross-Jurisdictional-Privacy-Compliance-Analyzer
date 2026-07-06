"""Generate the condensed Non-Functional Requirements summary document.

Matches the FR summary format requested by the supervisor: 8 columns —
    No | Source | Description | Data | Process | Communication | Priority | Status

Output: thesis_non_functional_requirements_summary.docx
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt, RGBColor


NAVY = RGBColor(0x00, 0x25, 0x83)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

CHECK = '✔'
DASH  = '-'


# (source, description, data, process, communication, priority, status)
SECTIONS = [
    (
        'Performance Efficiency',
        [
            ('Technical feasibility study',
             'The system shall return retrieval results within 2 seconds for typical queries on a warm cache.',
             False, True, True, 'H', 'Closed'),
            ('Technical feasibility study',
             'The system shall complete a single-topic policy mapping within 90 seconds for a typical policy document.',
             False, True, True, 'M', 'Closed'),
        ],
    ),
    (
        'Scalability',
        [
            ('Existing system analysis',
             'The system shall support concurrent use by at least 100 active users at the BBK deployment scale.',
             True, True, False, 'H', 'Closed'),
            ('Technical feasibility study',
             'The system shall support a regulatory corpus of at least 50,000 indexed chunks without degradation of retrieval response time.',
             True, True, False, 'H', 'Closed'),
        ],
    ),
    (
        'Reliability & Availability',
        [
            ('Research paper',
             'The system shall execute reasoning workflows as a bounded iterative correction process.',
             False, True, False, 'H', 'Closed'),
            ('Research paper',
             'The system shall produce a deterministic fallback response when reasoning workflows cannot produce a verified answer.',
             False, True, True, 'M', 'Closed'),
            ('Existing system analysis',
             'The system shall provide an offline processing capability for reasoning workloads under restricted external connectivity.',
             False, True, False, 'M', 'Closed'),
            ('Research paper',
             'The system shall support idempotent re-ingestion of documents via content hashing, recovering from transient ingestion failures without data loss.',
             True, True, False, 'M', 'Closed'),
        ],
    ),
    (
        'Maintainability',
        [
            ('Technical feasibility study',
             'The system shall be organised into loosely coupled modules with clear interface boundaries (ingestion, retrieval, reasoning, web).',
             False, True, False, 'M', 'Closed'),
            ('Existing system analysis',
             'The system shall provide an automated test suite covering authentication, role-based access, audit logging, monitoring, and retrieval quality.',
             True, True, False, 'H', 'Closed'),
            ('Technical feasibility study',
             'The system shall support swappable LLM providers via configuration, including managed and locally-hosted options.',
             False, True, False, 'M', 'Closed'),
        ],
    ),
    (
        'Usability',
        [
            ('BBK consultation',
             'The system shall display live progress for any background operation expected to exceed five seconds.',
             False, True, True, 'H', 'Closed'),
            ('Existing system analysis',
             'The system shall warn users of impending idle-session timeout and allow them to extend the session without losing the current page state.',
             False, True, True, 'M', 'Closed'),
            ('Meeting with BBK',
             'The system shall provide audit-quality export of analysis reports in XLSX, DOCX, and PDF formats.',
             True, True, True, 'H', 'Closed'),
        ],
    ),
    (
        'Configurability',
        [
            ('Technical feasibility study',
             'The system shall expose runtime configuration via environment variables for session timeout, MFA enforcement, retry limits, geo-fencing, and LLM provider selection.',
             False, True, False, 'M', 'Closed'),
        ],
    ),
    (
        'Observability',
        [
            ('Meeting with NAIRDC',
             'The system shall provide an administrator monitoring dashboard summarising LLM provider health, vector store statistics, lexical index statistics, active sessions, audit log volume, and recent reasoning failures.',
             True, True, True, 'M', 'Closed'),
        ],
    ),
    (
        'AI Quality & Governance',
        [
            ('Research paper',
             'The system shall evaluate whether AI-generated outputs are semantically supported by the retrieved evidence.',
             False, True, False, 'M', 'Closed'),
            ('Meeting with NAIRDC',
             'The system shall monitor reasoning performance against a rolling baseline, including approval rate, confidence, and validation-error rate.',
             True, True, True, 'M', 'Closed'),
            ('Meeting with NAIRDC',
             'The system shall monitor bias parity across user roles and jurisdictions, flagging approval-rate gaps above a configurable threshold.',
             True, True, True, 'M', 'Closed'),
            ('Meeting with NAIRDC',
             'The system shall surface anomaly signals to administrators, including output distribution skew, validation-error spikes, and failed-login surges.',
             True, True, True, 'M', 'Closed'),
        ],
    ),
]


def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def _set_run_style(run, *, bold=False, color=NAVY, size=10):
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.size = Pt(size)


def _style_paragraph(paragraph, *, bold=False, color=NAVY, size=10, align=None):
    if align is not None:
        paragraph.alignment = align
    for run in paragraph.runs:
        _set_run_style(run, bold=bold, color=color, size=size)


def main():
    base = Path(__file__).resolve().parent.parent
    out_path = base / 'thesis_non_functional_requirements_summary.docx'
    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = base / f'thesis_non_functional_requirements_summary_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break
    doc = Document()

    for section in doc.sections:
        section.orientation = WD_ORIENT.LANDSCAPE
        new_width, new_height = section.page_height, section.page_width
        section.page_width  = new_width
        section.page_height = new_height
        section.top_margin    = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin   = Cm(1.5)
        section.right_margin  = Cm(1.5)

    title = doc.add_heading('Non-Functional Requirements (Summary)', level=0)
    for run in title.runs:
        run.font.color.rgb = NAVY

    intro = doc.add_paragraph(
        "This section presents a focused selection of the system's most important "
        "non-functional requirements, drawn verbatim from the complete requirements "
        "specification and organized across the eight quality categories: Performance "
        "Efficiency, Scalability, Reliability & Availability, Maintainability, "
        "Usability, Configurability, Observability, and AI Quality & Governance. "
        "Each requirement records its primary elicitation source, the categories it "
        "engages (Data, Process, Communication), a MoSCoW priority, and its current "
        "status. The complete fine-grained set of non-functional requirements (32 "
        "atomic entries) is provided in Appendix B."
    )
    for run in intro.runs:
        run.font.size = Pt(11)
        run.font.color.rgb = NAVY

    total_rows = 1 + sum(1 + len(rows) for _, rows in SECTIONS)
    table = doc.add_table(rows=total_rows, cols=8)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False

    widths = [
        Cm(1.3),  # No
        Cm(3.2),  # Source
        Cm(11.5), # Description
        Cm(1.3),  # Data
        Cm(1.5),  # Process
        Cm(2.4),  # Communication
        Cm(1.5),  # Priority
        Cm(1.6),  # Status
    ]
    for col_idx, width in enumerate(widths):
        for cell in table.columns[col_idx].cells:
            cell.width = width

    header = table.rows[0]
    headers = ['No.', 'Source', 'Requirement Description', 'Data', 'Process',
               'Communication', 'Priority', 'Status']
    for i, h in enumerate(headers):
        header.cells[i].text = h
        shade_cell(header.cells[i], '002583')
        header.cells[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = header.cells[i].paragraphs[0]
        para.alignment = (WD_ALIGN_PARAGRAPH.CENTER if i in (3, 4, 5, 6, 7)
                          else WD_ALIGN_PARAGRAPH.LEFT)
        for run in para.runs:
            _set_run_style(run, bold=True, color=WHITE, size=10)

    req_counter = 0
    row_idx = 1
    for section_name, rows in SECTIONS:
        sec_row = table.rows[row_idx]
        merged = sec_row.cells[0]
        for c in range(1, 8):
            merged = merged.merge(sec_row.cells[c])
        merged.text = section_name
        shade_cell(merged, '002583')
        merged.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = merged.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            _set_run_style(run, bold=True, color=WHITE, size=11)
        row_idx += 1

        for source, desc, data, process, comm, priority, status in rows:
            req_counter += 1
            data_row = table.rows[row_idx]
            data_row.cells[0].text = f'NFR{req_counter}'
            data_row.cells[1].text = source
            data_row.cells[2].text = desc
            data_row.cells[3].text = CHECK if data    else DASH
            data_row.cells[4].text = CHECK if process else DASH
            data_row.cells[5].text = CHECK if comm    else DASH
            data_row.cells[6].text = priority
            data_row.cells[7].text = status
            for i, cell in enumerate(data_row.cells):
                cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
                for paragraph in cell.paragraphs:
                    align = (WD_ALIGN_PARAGRAPH.CENTER if i in (0, 3, 4, 5, 6, 7)
                             else WD_ALIGN_PARAGRAPH.LEFT)
                    _style_paragraph(paragraph, color=NAVY, size=10, align=align)
            for run in data_row.cells[0].paragraphs[0].runs:
                run.font.bold = True
            for run in data_row.cells[6].paragraphs[0].runs:
                run.font.bold = True
            row_idx += 1

    doc.save(str(out_path))
    print(f'Wrote: {out_path} ({req_counter} requirements across {len(SECTIONS)} sections)')


if __name__ == '__main__':
    main()
