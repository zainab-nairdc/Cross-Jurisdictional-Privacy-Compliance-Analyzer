"""Generate the Constraints Word document for the thesis.

Output: thesis_constraints.docx in the project root.

Same layout as the FR / NFR docs: one continuous table with four columns
(ID, Type, Constraint, Impact / Mitigation). Category names appear as
merged-cell section headers between constraint groups.
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


CATEGORIES = [
    (
        'Hardware & Compute',
        [
            (
                'Hardware',
                'The system was developed on a device without an NVIDIA GPU; local LLM inference was too slow for interactive use.',
                "A managed cloud LLM (Claude Haiku 4.5) was used in development for speed; local Ollama was tested on NAIRDC's GPU-equipped device. Providers are swappable, so local can be the production default.",
            ),
        ],
    ),
    (
        'Data Access',
        [
            (
                'Data',
                "Direct access to BBK's internal policies, governance documents, and SOPs was not available.",
                'Twelve synthetic policy artefacts were authored to mirror typical bank compliance documents. The ingestion pipeline is corpus-agnostic; real BBK documents can be substituted without code changes.',
            ),
            (
                'Data',
                "The regulatory document set was not validated by BBK's legal function.",
                '~43 documents across Bahrain, India, and Kuwait were assembled through independent research from publicly available sources. Documents can be added or replaced without code changes.',
            ),
            (
                'Data Quality',
                'Output quality is bounded by data quality: synthetic policies, varied regulatory document formatting, and a researcher-authored taxonomy and term dictionary.',
                'Outputs are analytical assistance subject to reviewer validation; every finding is citation-traceable to source. Better inputs would directly improve output quality without code changes.',
            ),
            (
                'Regulatory Regime',
                "The three jurisdictions are not equally mature in privacy regulation. Bahrain has a comprehensive PDPL with ten subordinate orders; India has the DPDP Act 2023 plus RBI circulars; Kuwait's regime is thinner and mostly sectoral. Documents vary significantly in length, hierarchy, and depth, with some having no direct analogue in other jurisdictions.",
                "The comparison workflow uses asymmetric categories (equivalent, stronger, weaker, partial, absent), treating 'no analogue' as a valid finding. Auto-routing dispatches comparisons only against regulations that cover the relevant topic. Header-aware chunking preserves each regime's native hierarchy (Article, Section, Resolution) in citations.",
            ),
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
    out_path = base / 'thesis_constraints.docx'
    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = base / f'thesis_constraints_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break
    doc = Document()

    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    title = doc.add_heading('Constraints', level=0)
    for run in title.runs:
        run.font.color.rgb = NAVY

    intro = doc.add_paragraph(
        "This section presents the constraints that shaped the functionality and "
        "development of the system, organized across four categories: Hardware & "
        "Compute, Data Access, Process & Development, and Deployment Environment. "
        "Each constraint records its type and the mitigation strategy applied."
    )
    for run in intro.runs:
        run.font.size = Pt(11)
        run.font.color.rgb = NAVY

    total_rows = 1 + sum(1 + len(rows) for _, rows in CATEGORIES)
    table = doc.add_table(rows=total_rows, cols=4)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False

    widths = [Cm(1.2), Cm(1.8), Cm(6.5), Cm(7.5)]
    for col_idx, width in enumerate(widths):
        for cell in table.columns[col_idx].cells:
            cell.width = width

    # Header row.
    header = table.rows[0]
    header.cells[0].text = 'ID'
    header.cells[1].text = 'Type'
    header.cells[2].text = 'Constraint'
    header.cells[3].text = 'Impact / Mitigation'
    for cell in header.cells:
        shade_cell(cell, '002583')
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            _set_run_style(run, bold=True, color=WHITE, size=10)

    con_counter = 0
    row_idx = 1
    for category_name, rows in CATEGORIES:
        # Category divider row: merge all four cells, navy fill, white bold text.
        cat_row = table.rows[row_idx]
        merged = (
            cat_row.cells[0]
            .merge(cat_row.cells[1])
            .merge(cat_row.cells[2])
            .merge(cat_row.cells[3])
        )
        merged.text = category_name
        shade_cell(merged, '002583')
        merged.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = merged.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            _set_run_style(run, bold=True, color=WHITE, size=11)
        row_idx += 1

        for type_label, constraint, mitigation in rows:
            con_counter += 1
            data_row = table.rows[row_idx]
            data_row.cells[0].text = f'CON-{con_counter:02d}'
            data_row.cells[1].text = type_label
            data_row.cells[2].text = constraint
            data_row.cells[3].text = mitigation
            for cell in data_row.cells:
                cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
                for paragraph in cell.paragraphs:
                    _style_paragraph(paragraph, color=NAVY, size=10)
            # Bold the ID and the Type.
            for run in data_row.cells[0].paragraphs[0].runs:
                run.font.bold = True
            for run in data_row.cells[1].paragraphs[0].runs:
                run.font.bold = True
            row_idx += 1

    doc.save(str(out_path))
    print(f'Wrote: {out_path} ({con_counter} constraints across {len(CATEGORIES)} categories)')


if __name__ == '__main__':
    main()
