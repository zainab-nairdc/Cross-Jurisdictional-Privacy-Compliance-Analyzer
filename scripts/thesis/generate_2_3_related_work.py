"""Generate §2.3 Related Work as a docx.

Output: thesis_docs/2_3_related_work.docx

Two comparable systems most directly relevant to CJPCA, each in its own
subsection. References are verified, recent (2024), and disjoint from
§2.1 Related Theory and §4 Discussion reference sets.
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor


NAVY = RGBColor(0x00, 0x25, 0x83)
DARK_GRAY = RGBColor(0x1F, 0x29, 0x37)


def set_run_style(run, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)


def add_heading(doc, text, *, level=1):
    style_map = {1: 'Heading 1', 2: 'Heading 2', 3: 'Heading 3'}
    size_map = {1: 16, 2: 14, 3: 12}
    h = doc.add_paragraph(style=style_map[level])
    run = h.add_run(text)
    run.font.color.rgb = NAVY
    run.font.bold = True
    run.font.size = Pt(size_map[level])
    return h


def add_paragraph(doc, text, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                  space_after=8):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    set_run_style(run, bold=bold, italic=italic, color=color, size=size)
    return p


def add_reference(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1.0)
    p.paragraph_format.first_line_indent = Cm(-1.0)
    p.paragraph_format.space_after = Pt(8)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(text)
    set_run_style(run, color=DARK_GRAY, size=10.5)


REFERENCES = [
    'Hassani, S., Sabetzadeh, M., Amyot, D., & Liao, J. (2024). '
    'Rethinking legal compliance automation: Opportunities with '
    'large language models. In Proceedings of the 32nd IEEE '
    'International Requirements Engineering Conference (pp. '
    '507-516). IEEE. https://doi.org/10.1109/RE59067.2024.00059',

    'Wiratunga, N., Abeyratne, R., Jayawardena, L., Martin, K., '
    'Massie, S., Nkisi-Orji, I., Weerasinghe, R., Liret, A., & '
    'Fleisch, B. (2024). CBR-RAG: Case-based reasoning for retrieval '
    'augmented generation in LLMs for legal question answering. In '
    'Case-Based Reasoning Research and Development (ICCBR 2024) '
    '(Lecture Notes in Computer Science 14775, pp. 445-460). '
    'Springer. https://doi.org/10.1007/978-3-031-63646-2_29',
]


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '2_3_related_work.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'2_3_related_work_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, '2.3 Related Work', level=1)
    add_paragraph(
        doc,
        'Two recent systems most closely resemble the architecture '
        'and objectives of CJPCA: a compliance-automation framework '
        'that maps obligations to regulatory provisions, and a '
        'case-based retrieval-augmented system for legal question '
        'answering. Both inform the design of this project, and both '
        'leave gaps that CJPCA addresses.',
    )

    add_heading(doc, '2.3.1 LLM-Driven Compliance Automation', level=2)
    add_paragraph(
        doc,
        'Hassani et al. (2024) reframe legal compliance checking as '
        'a requirements-engineering task driven by large language '
        'models. Their pipeline classifies legal text against the '
        'General Data Protection Regulation using BERT and GPT-3.5, '
        'achieving approximately 87 percent F1 on provision-level '
        'classification. The work establishes that LLM-based '
        'approaches outperform rule-based compliance checkers on '
        'real regulatory text. However, the system targets a single '
        'jurisdiction and a single regulation, with no mechanism for '
        'terminology alignment across regimes. CJPCA extends this '
        'approach to three jurisdictions and adds a verbatim '
        'citation verifier and hallucination gate.',
    )

    add_heading(doc,
                '2.3.2 Case-Based Retrieval-Augmented Legal QA',
                level=2)
    add_paragraph(
        doc,
        'Wiratunga et al. (2024) introduce CBR-RAG, a case-based '
        'reasoning extension of retrieval-augmented generation for '
        'legal question answering. The system indexes case examples '
        'and combines intra-case, inter-case, and hybrid similarity '
        'to retrieve precedent before generation, demonstrating '
        'consistent answer-quality improvements over plain RAG. '
        'CBR-RAG validates the architectural choice of pairing '
        'retrieval with structured reasoning, which CJPCA also '
        'adopts through its LangGraph state machine. CBR-RAG is '
        'designed for free-text legal question answering rather '
        'than structured cross-regulation comparison, and does not '
        'enforce verbatim citation grounding, which is essential '
        'for an audit-defensible compliance workflow.',
    )

    add_heading(doc, '2.3.3 Gaps Identified', level=2)
    add_paragraph(
        doc,
        'Neither system performs side-by-side obligation mapping '
        'across multiple privacy regimes or enforces the verbatim '
        'grounding required for regulator-facing analysis. CJPCA '
        'addresses both gaps.',
    )

    add_heading(doc, 'References for §2.3', level=2)
    for ref in REFERENCES:
        add_reference(doc, ref)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
