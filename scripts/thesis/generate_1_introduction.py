"""Generate §1 Introduction as a docx.

Output: thesis_docs/1_introduction.docx

Structure:
  1.1 Project Rationale          (prose)
  1.2 Project Objectives         (intro + Table 1 + Table 2)
  1.3 Proposed Solution          (prose)
  1.4 Description of the Report  (prose)

Word count target: <= 600 words of prose (tables excluded per saved
style rule). Current: 556 words.
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
    style_map = {1: 'Heading 1', 2: 'Heading 2', 3: 'Heading 3'}
    size_map = {1: 16, 2: 14, 3: 12}
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
    p.paragraph_format.space_after = Pt(8)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_table(doc, headers, rows, widths_cm, body_size=10):
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
            set_run_style(run, bold=True, color=WHITE, size=11)
    for r_idx, row_values in enumerate(rows, start=1):
        row = table.rows[r_idx]
        for c_idx, value in enumerate(row_values):
            cell = row.cells[c_idx]
            cell.text = str(value)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            for para in cell.paragraphs:
                para.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in para.runs:
                    set_run_style(
                        run,
                        bold=(c_idx == 0),
                        color=DARK_GRAY,
                        size=body_size,
                    )


TECHNICAL_OBJECTIVES = [
    ('T1',
     'Develop a hybrid retrieval pipeline combining BM25 lexical '
     'search, ChromaDB vector search, reciprocal rank fusion, and '
     'cross-encoder reranking',
     'Hit-rate@5 of at least 0.85 on a 100-query gold test set, '
     '100% clause-level citation traceability'),
    ('T2',
     'Implement AI-driven reasoning workflows for regulation '
     'comparison, policy-coverage mapping, and gap analysis',
     'Pydantic-validated outputs, citation grounding pass rate of '
     'at least 95%, hallucination gate trigger rate of no more than '
     '5% across a 100-output validation sample'),
    ('T3',
     'Develop an AI-powered Copilot that provides reviewers with '
     'citation-backed guidance grounded in retrieved legal text',
     'Response time of no more than 5 seconds on a warm cache, '
     'active-scope respect across at least 95% of queries'),
    ('T4',
     'Design a Django-based reviewer platform with role-based '
     'workflows for analysts, reviewers, and administrators '
     'implementing a Draft -> Reviewed -> Approved validation '
     'lifecycle',
     'At least 100 concurrent active users, MFA enforced on every '
     'account, three-role RBAC'),
    ('T5',
     'Apply security-by-design principles covering authentication, '
     'access control, audit logging, and AI safety',
     'Zero high or critical residual risk after controls, mapped '
     'to all 10 categories of the OWASP Top 10 and the OWASP Top 10 '
     'for LLM Applications'),
]


GENERAL_OBJECTIVES = [
    ('G1',
     'Reduce manual cross-jurisdictional review time compared to '
     'legacy workflows',
     'At least 40% time reduction on a representative '
     'policy-to-regulation mapping task'),
    ('G2',
     'Identify compliance gaps across Bahrain, India, and Kuwait '
     'privacy regimes',
     '100% citation traceability to source clauses for every gap '
     'surfaced'),
    ('G3',
     'Support BBK\'s digital transformation strategy through '
     'AI-assisted compliance',
     'Functional reviewer platform delivered by end of project '
     'period and audit-defensible for internal deployment'),
    ('G4',
     'Scale to a growing regulatory and policy corpus without code '
     'changes',
     'Support at least 50,000 indexed chunks without retrieval '
     'response-time degradation beyond the NFR1 ceiling of '
     '2 seconds'),
    ('G5',
     'Maintain regulatory transparency and audit readiness through '
     'tamper-evident audit logs',
     '100% append-only AuditLog coverage of every security-relevant '
     'action, SHA-256 hash chain on every PDF and XLSX export'),
]


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '1_introduction.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'1_introduction_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, '1. Introduction', level=1)

    add_heading(doc, '1.1 Project Rationale', level=2)
    add_paragraph(
        doc,
        'Financial institutions increasingly operate across multiple '
        'regulatory jurisdictions, each enforcing distinct data '
        'protection frameworks. For multinational organisations like '
        'the Bank of Bahrain and Kuwait (BBK), operating under these '
        'different rules creates a serious operational challenge. '
        'Privacy regulations use different terms, impose overlapping '
        'yet non-identical obligations, and evolve at different '
        'legislative paces. Compliance teams must therefore manually '
        'interpret, compare, and map numerous regulatory texts '
        'against internal policies. This traditional approach is '
        'time-consuming, error-prone, and prone to inconsistent '
        'interpretation. In the financial sector, mistakes carry '
        'severe consequences including regulatory penalties, audit '
        'failures, and reputational damage. This project is motivated '
        'by a real gap in how organisations manage privacy risk '
        'across many jurisdictions. The Cross-Jurisdictional Privacy '
        'Compliance Analyzer (CJPCA) addresses this need through an '
        'AI-assisted decision-support platform that structures '
        'regulatory comparison, highlights coverage gaps, and '
        'maintains full citation traceability while preserving '
        'essential human oversight in final legal validation.',
    )

    add_heading(doc, '1.2 Project Objectives', level=2)
    add_paragraph(
        doc,
        'The project pursues five technical objectives addressing the '
        'system\'s core components, and five general objectives '
        'addressing organisational value. Each objective is stated in '
        'SMART form with a measurable success criterion that links '
        'directly to the evaluation in Chapter 3.4 and the discussion '
        'in Chapter 4.',
    )
    add_caption(doc, 'Table 3.', 'Technical Objectives.')
    add_table(
        doc,
        headers=['ID', 'Objective', 'Measurable success criterion'],
        rows=TECHNICAL_OBJECTIVES,
        widths_cm=[1.2, 7.0, 7.8],
        body_size=10,
    )
    add_caption(doc, 'Table 4.', 'General Objectives.')
    add_table(
        doc,
        headers=['ID', 'Objective', 'Measurable success criterion'],
        rows=GENERAL_OBJECTIVES,
        widths_cm=[1.2, 7.0, 7.8],
        body_size=10,
    )

    add_heading(doc, '1.3 Proposed Solution', level=2)
    add_paragraph(
        doc,
        'The proposed solution combines retrieval-augmented '
        'generation (RAG) with a secure web application. A Document '
        'Retrieval Layer stores regulatory documents and internal '
        'policies in a searchable database that uses both keyword '
        'and semantic search. A cross-jurisdiction terminology '
        'dictionary connects equivalent legal terms across Bahraini, '
        'Indian, and Kuwaiti privacy regulations, so vocabulary '
        'differences do not cause results to be missed. A Reasoning '
        'Layer runs workflows for regulation comparison, '
        'policy-coverage mapping, and gap analysis, alongside an AI '
        'Copilot that answers reviewer questions with '
        'citation-backed guidance. Local LLM hosting through Ollama '
        'ensures analytical content never leaves the on-premises '
        'host. Every output links back to its source clauses, '
        'reducing the risk of the AI inventing facts. Reliability '
        'is enforced through two verification methods: confirming '
        'that quoted text appears verbatim in the cited source, and '
        'using a Natural Language Inference model that checks '
        'whether the answer follows from the retrieved evidence. If '
        'verification fails, the system auto-corrects the answer, '
        'and if that fails, a safe fallback response is returned. A '
        'two-tier prompt-injection defence scans every ingested '
        'document before any content reaches the searchable index. '
        'Capabilities are delivered through a Django-based reviewer '
        'platform with role-based access control, multi-factor '
        'authentication, tamper-evident audit logging, and a Draft, '
        'Reviewed, Approved lifecycle that preserves human '
        'oversight.',
    )
    add_paragraph(
        doc,
        'The Document Retrieval Layer and terminology dictionary '
        'deliver objective T1, the Reasoning Layer delivers T2, the '
        'Copilot delivers T3, the Django-based reviewer platform '
        'with RBAC and MFA delivers T4, and the two-tier injection '
        'defence with audit logging delivers T5. The same components '
        'deliver the general objectives in Table 4 by reducing '
        'manual review time (G1), surfacing gaps with full citation '
        'traceability (G2 and G5), supporting BBK\'s digital '
        'transformation through audit-defensible AI assistance (G3), '
        'and scaling to large corpora without code change (G4).',
    )

    add_heading(doc, '1.4 Description of the Report', level=2)
    add_paragraph(
        doc,
        'This report is organised in five chapters. Chapter 1 '
        'introduces the project, its rationale, objectives, and '
        'proposed solution. Chapter 2 reviews the theoretical '
        'foundations, enabling technologies, related academic work, '
        'and existing commercial alternatives for '
        'retrieval-augmented generation and multi-jurisdictional '
        'privacy compliance. Chapter 3 presents the methodology in '
        'four parts covering requirements elicitation, system '
        'design, implementation, and testing. Chapter 4 reflects on '
        'system functionality, achieved objectives, project issues, '
        'legal, ethical, social, and professional considerations, '
        'future work, and the student experience. Chapter 5 '
        'concludes the thesis. The references and supporting '
        'appendices follow.',
    )

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
