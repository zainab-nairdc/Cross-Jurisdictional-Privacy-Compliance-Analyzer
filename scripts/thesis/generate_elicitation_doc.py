"""Generate the Requirements Elicitation Word document for the thesis.

Output: thesis_requirements_elicitation.docx in the project root.

Hybrid format:
    1. Section heading
    2. Short intro paragraph
    3. Five-step numbered process (high-level methodology, one sentence each)
    4. Appendix 1 pointer
    5. Summary table (No | Approach | Process) — detailed techniques used in step 2
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


def add_para(doc, text: str, *, size=11):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.color.rgb = NAVY
    run.font.size = Pt(size)
    return p


def add_numbered_step(doc, number: int, title: str, body: str):
    p = doc.add_paragraph()
    run = p.add_run(f'{number}. ')
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.size = Pt(11)
    run = p.add_run(f'{title} — ')
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.size = Pt(11)
    run = p.add_run(body)
    run.font.color.rgb = NAVY
    run.font.size = Pt(11)


TABLE_ROWS = [
    (
        'Stakeholder Meetings',
        "Direct meetings were conducted with representatives from the Bank of Bahrain and Kuwait (BBK) as the client and NAIRDC as the project-management proxy. These meetings aimed to understand the client's compliance challenges, expected user workflows, and operational priorities. Insights gathered from these meetings helped in identifying the primary user-facing capabilities and the operational structure of the system.",
    ),
    (
        'BBK Consultations',
        "Focused consultations with BBK were held to gather detailed information about the bank's compliance practices, operational conventions, and audit expectations. These consultations aimed to ensure the system reflected the bank's existing terminology and processes rather than imposing external structures. Insights gathered from these consultations directly shaped how the system organises its outputs and aligns with internal compliance workflows.",
    ),
    (
        'Document Analysis',
        "The project brief, the bank's existing security posture, and the regulatory corpus of Bahrain, India, and Kuwait were reviewed to extract structural and methodological requirements. This analysis aimed to understand the legal and operational context in which the system would operate. The review identified the key methodological challenges of cross-jurisdictional comparison and informed the design of the system's analytical workflows.",
    ),
    (
        'Research',
        "Research on retrieval-augmented generation, prompt-injection defence, and AI output verification was conducted to identify state-of-the-art techniques relevant to the system. This research aimed to derive technical requirements that internal stakeholders would not have articulated directly. Findings from the research informed the design of the system's retrieval, reasoning, and output-validation components.",
    ),
    (
        'Technical Feasibility Study',
        "A short prototyping phase was carried out to validate that the proposed analytical pipeline could be implemented on the available hardware. This study aimed to confirm performance and resource feasibility before committing to full development. The findings informed the system's performance targets and led to the swappable-LLM-provider architecture used in deployment.",
    ),
    (
        'Requirements Prioritisation',
        "Once requirements were gathered, they were prioritised based on their importance to stakeholders, alignment with project objectives, and feasibility of implementation. This prioritisation process used the MoSCoW classification along with the Volere-style Data / Process / Communication tagging. The process ensured that key features were addressed first, supporting incremental development and timely delivery of value to stakeholders.",
    ),
]


def main():
    base = Path(__file__).resolve().parent.parent
    out_path = base / 'thesis_requirements_elicitation.docx'
    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = base / f'thesis_requirements_elicitation_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()

    for section in doc.sections:
        section.top_margin    = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin   = Cm(2.0)
        section.right_margin  = Cm(2.0)

    # ── Section heading ──
    title = doc.add_heading('3.1.1 Requirements Elicitation', level=1)
    for run in title.runs:
        run.font.color.rgb = NAVY

    # ── Intro paragraph ──
    add_para(
        doc,
        "Requirements elicitation for CJPCA involved BBK as the client, NAIRDC as "
        "the project-management proxy, and legal and compliance analysts as end "
        "users. Six elicitation techniques were used to gather and validate "
        "requirements, as summarized in Table 2, with supporting details provided "
        "in Appendix 1."
    )

    doc.add_paragraph()

    # ── Table ──
    total_rows = 1 + len(TABLE_ROWS)
    table = doc.add_table(rows=total_rows, cols=3)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False

    widths = [Cm(1.2), Cm(4.0), Cm(11.8)]
    for col_idx, width in enumerate(widths):
        for cell in table.columns[col_idx].cells:
            cell.width = width

    # Header row.
    header = table.rows[0]
    headers = ['No.', 'Approach', 'Process']
    for i, h in enumerate(headers):
        header.cells[i].text = h
        shade_cell(header.cells[i], '002583')
        header.cells[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = header.cells[i].paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            _set_run_style(run, bold=True, color=WHITE, size=11)

    # Data rows.
    for i, (approach, process) in enumerate(TABLE_ROWS, 1):
        row = table.rows[i]
        row.cells[0].text = str(i)
        row.cells[1].text = approach
        row.cells[2].text = process
        for j, cell in enumerate(row.cells):
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            for paragraph in cell.paragraphs:
                paragraph.alignment = (WD_ALIGN_PARAGRAPH.CENTER if j == 0
                                       else WD_ALIGN_PARAGRAPH.LEFT)
                for run in paragraph.runs:
                    _set_run_style(run, color=NAVY, size=10,
                                   bold=(j in (0, 1)))

    # ── Table caption (below table, matching thesis convention) ──
    caption = doc.add_paragraph()
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = caption.add_run('Table 2. Requirements Elicitation Approaches')
    run.font.bold = True
    run.font.italic = True
    run.font.color.rgb = NAVY
    run.font.size = Pt(11)

    doc.save(str(out_path))
    print(f'Wrote: {out_path} ({len(TABLE_ROWS)} approaches)')


if __name__ == '__main__':
    main()
