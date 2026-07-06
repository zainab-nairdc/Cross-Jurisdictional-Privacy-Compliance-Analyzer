"""Generate the condensed 20-row Functional Requirements summary document.

Supervisor-requested format with 8 columns:
    No | Source | Description | Data | Process | Communication | Priority | Status

Output: thesis_functional_requirements_summary.docx in the project root.
Sections are functional groupings (not pipeline phases) shown as merged-cell
header rows between requirements.
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt, RGBColor


NAVY = RGBColor(0x00, 0x25, 0x83)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

CHECK = '✔'  # ✔
DASH  = '-'


# (source, description, data, process, communication, priority, status)
SECTIONS = [
    (
        'Document Ingestion',
        [
            ('BBK consultation',
             'The system shall ingest privacy regulations from Bahrain, India, and Kuwait.',
             True, True, False, 'H', 'Closed'),
            ('Brief',
             "The system shall ingest BBK's internal privacy policies, governance documents, and operational SOPs.",
             True, True, False, 'H', 'Closed'),
            ('Legal document analysis',
             'The system shall store metadata for every document, including jurisdiction, version, publication date, and source.',
             True, True, False, 'H', 'Closed'),
            ('Research paper',
             'The system shall split documents into searchable chunks that preserve their section structure.',
             True, True, False, 'H', 'Closed'),
        ],
    ),
    (
        'Retrieval Layer',
        [
            ('Research paper',
             'The system shall retrieve and rank chunks using combined semantic and keyword search.',
             True, True, False, 'H', 'Closed'),
            ('Research paper',
             'The system shall expand queries using equivalent legal terminology across jurisdictions.',
             True, True, False, 'H', 'Closed'),
            ('Legal document analysis',
             'The system shall return citation-preserving results linked to their source documents.',
             True, True, True, 'H', 'Closed'),
        ],
    ),
    (
        'Reasoning & Analysis',
        [
            ('Meeting with BBK',
             'The system shall compare obligations between two selected regulatory frameworks for a chosen compliance topic.',
             True, True, True, 'H', 'Closed'),
            ('Legal document analysis',
             'The system shall identify similarities, differences, and conflicts between compared regulatory obligations.',
             True, True, True, 'H', 'Closed'),
            ('Legal document analysis',
             'The system shall determine equivalence levels between obligations across jurisdictions.',
             True, True, True, 'H', 'Closed'),
            ('Meeting with BBK',
             'The system shall map internal policy documents against one or more regulations.',
             True, True, True, 'H', 'Closed'),
            ('BBK consultation',
             'The system shall classify policy coverage as Fully Covered, Partially Covered, Requires Review, or Not Covered.',
             True, True, True, 'H', 'Closed'),
            ('Discussion',
             'The system shall automatically route policy mapping workflows to relevant regulations based on detected compliance topics.',
             True, True, True, 'H', 'Closed'),
            ('Meeting with BBK',
             'The system shall aggregate uncovered obligations from multiple jurisdictions into a unified gap analysis report.',
             True, True, True, 'H', 'Closed'),
        ],
    ),
    (
        'Web Application',
        [
            ('Meeting with BBK',
             'The system shall provide a home dashboard summarising overall compliance posture.',
             True, False, True, 'H', 'Closed'),
            ('Meeting with BBK',
             'The system shall provide a library workspace for browsing regulations, internal policies, obligations, and legal terminology dictionaries.',
             True, True, True, 'H', 'Closed'),
            ('Meeting with BBK',
             'The system shall support analyst-driven document uploads.',
             True, True, True, 'H', 'Closed'),
            ('Meeting with BBK',
             'The system shall provide a comparison workspace for configuring cross-regulation comparisons.',
             True, True, True, 'H', 'Closed'),
            ('Meeting with BBK',
             'The system shall provide a policy mapping workspace for configuring policy-to-regulation mapping workflows.',
             True, True, True, 'H', 'Closed'),
            ('BBK consultation',
             'The system shall provide a reviewer validation queue for reviewing AI-generated findings.',
             True, True, True, 'H', 'Closed'),
            ('Meeting with BBK',
             'The system shall support export of analysis reports in XLSX, DOCX, and PDF formats.',
             True, True, True, 'H', 'Closed'),
            ('Meeting with BBK',
             'The system shall provide a cross-jurisdiction gap analysis workspace.',
             True, True, True, 'H', 'Closed'),
            ('Existing system analysis',
             'The system shall provide a role-based analytics dashboard summarising compliance coverage, gaps, conflicts, and reviewer activity.',
             True, True, True, 'M', 'Closed'),
        ],
    ),
    (
        'Copilot Agent',
        [
            ('Meeting with BBK',
             'The system shall provide a global AI Copilot chat overlay accessible from every page.',
             True, True, True, 'H', 'Closed'),
            ('Research paper',
             'The system shall ground every Copilot answer in retrieved corpus chunks before responding.',
             True, True, False, 'H', 'Closed'),
            ('Research paper',
             'The system shall return Copilot answers with regulation-name, article-reference, and excerpt-level citations.',
             True, True, True, 'H', 'Closed'),
            ('Research paper',
             'The system shall report a confidence score and a hallucination risk score alongside every Copilot answer.',
             False, True, True, 'M', 'Closed'),
        ],
    ),
    (
        'Security & Access Control',
        [
            ('Existing system analysis',
             'The system shall require username and password authentication for every user account.',
             True, True, True, 'H', 'Closed'),
            ('Existing system analysis',
             'The system shall require time-based one-time password (TOTP) multi-factor authentication for every user account.',
             True, True, True, 'H', 'Closed'),
            ('Existing system analysis',
             'The system shall enforce TOTP enrolment before any user can access business functionality after first login.',
             True, True, True, 'H', 'Closed'),
            ('Existing system analysis',
             'The system shall enforce password complexity requirements of minimum twelve characters, including uppercase, lowercase, digit, and symbol classes.',
             True, True, False, 'H', 'Closed'),
            ('Existing system analysis',
             'The system shall lock user accounts after a configurable threshold of failed login attempts, keyed on both username and source IP address.',
             True, True, False, 'H', 'Closed'),
            ('Existing system analysis',
             'The system shall log users out automatically after a configurable period of inactivity.',
             True, True, True, 'H', 'Closed'),
            ('Research paper',
             'The system shall harden session and CSRF cookies with HttpOnly, SameSite, and Secure flags in production.',
             True, True, False, 'H', 'Closed'),
            ('BBK consultation',
             'The system shall enforce role-based access control with three roles: Compliance Analyst, Legal Reviewer, and Administrator.',
             True, True, False, 'H', 'Closed'),
            ('Existing system analysis',
             'The system shall allow administrators to create user accounts and assign one of the three roles (Analyst, Reviewer, Administrator).',
             True, True, True, 'H', 'Closed'),
            ('BBK consultation',
             'The system shall maintain a global audit log of every security-relevant action, capturing actor, role at time of action, IP address, target object, and metadata.',
             True, True, False, 'H', 'Closed'),
            ('Research paper',
             'The system shall enforce Cross-Site Request Forgery (CSRF) protection on every state-changing request.',
             False, True, True, 'H', 'Closed'),
            ('Research paper',
             'The system shall scan every ingested chunk for prompt-injection content using a catalogue of known attack patterns.',
             True, True, True, 'H', 'Closed'),
            ('Research paper',
             'The system shall verify every AI-generated citation against the underlying retrieved chunks before returning results, rejecting any citation whose quoted text does not appear in source.',
             True, True, False, 'H', 'Closed'),
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
    out_path = base / 'thesis_functional_requirements_summary.docx'
    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = base / f'thesis_functional_requirements_summary_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break
    doc = Document()

    # Landscape orientation gives us more horizontal room for 8 columns.
    from docx.enum.section import WD_ORIENT
    for section in doc.sections:
        section.orientation = WD_ORIENT.LANDSCAPE
        # Swap page dimensions for landscape.
        new_width, new_height = section.page_height, section.page_width
        section.page_width  = new_width
        section.page_height = new_height
        section.top_margin    = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin   = Cm(1.5)
        section.right_margin  = Cm(1.5)

    title = doc.add_heading('Functional Requirements (Summary)', level=0)
    for run in title.runs:
        run.font.color.rgb = NAVY

    intro = doc.add_paragraph(
        "This section presents a focused selection of the system's most important "
        "functional requirements, drawn verbatim from the complete requirements "
        "specification and organized across the six pipeline phases: Document "
        "Ingestion, Retrieval Layer, Reasoning & Analysis, Web Application, Copilot "
        "Agent, and Security & Access Control. Each requirement records its primary "
        "elicitation source, the categories it engages (Data, Process, Communication), "
        "a MoSCoW priority, and its current status. The complete fine-grained set of "
        "functional requirements (120 atomic entries) is provided in Appendix A."
    )
    for run in intro.runs:
        run.font.size = Pt(11)
        run.font.color.rgb = NAVY

    total_rows = 1 + sum(1 + len(rows) for _, rows in SECTIONS)
    table = doc.add_table(rows=total_rows, cols=8)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False

    # Column widths sized for A4 landscape with 1.5cm margins (usable ~27cm).
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

    # Header row.
    header = table.rows[0]
    headers = ['No.', 'Source', 'Requirement Description', 'Data', 'Process',
               'Communication', 'Priority', 'Status']
    for i, h in enumerate(headers):
        header.cells[i].text = h
        shade_cell(header.cells[i], '002583')
        header.cells[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = header.cells[i].paragraphs[0]
        # Centre-align the tick-column headers; left-align the rest.
        para.alignment = (WD_ALIGN_PARAGRAPH.CENTER if i in (3, 4, 5, 6, 7)
                          else WD_ALIGN_PARAGRAPH.LEFT)
        for run in para.runs:
            _set_run_style(run, bold=True, color=WHITE, size=10)

    req_counter = 0
    row_idx = 1
    for section_name, rows in SECTIONS:
        # Section divider row spanning all 8 columns.
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
            data_row.cells[0].text = f'Req{req_counter}'
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
                    # Center the tick columns and the priority/status.
                    align = (WD_ALIGN_PARAGRAPH.CENTER if i in (0, 3, 4, 5, 6, 7)
                             else WD_ALIGN_PARAGRAPH.LEFT)
                    _style_paragraph(paragraph, color=NAVY, size=10, align=align)
            # Bold the ID + Priority columns.
            for run in data_row.cells[0].paragraphs[0].runs:
                run.font.bold = True
            for run in data_row.cells[6].paragraphs[0].runs:
                run.font.bold = True
            row_idx += 1

    doc.save(str(out_path))
    print(f'Wrote: {out_path} ({req_counter} requirements across {len(SECTIONS)} sections)')


if __name__ == '__main__':
    main()
