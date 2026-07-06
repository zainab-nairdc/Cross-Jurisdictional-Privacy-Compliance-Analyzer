"""Generate Appendix 1 — Requirements (Supporting Evidence) as a docx.

Output: thesis_docs/appendix_1_requirements.docx

Contents:
  A1.1 Stakeholder Interview Results (BBK + NAIRDC)
  A1.2 Research Findings (with verified APA 7 citations)
  A1.3 Document Analysis Findings
  A1.4 Technical Feasibility Study Findings
  A1.5 Extended Functional Requirements Catalogue (120 FRs, split
       per category)
  References for Appendix 1

Citations verified: Rackauckas 2024, Wen et al. 2025, Tamber et al.
2025, Wallat et al. 2025, Jacovi et al. 2025, Tang et al. 2024,
Madaan et al. 2023, NIST 2024. Duplicates of references already used
in §2.1 (Y. Gao 2024) and §3.2.7 (OWASP 2025) are excluded.
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BLACK = RGBColor(0x00, 0x00, 0x00)
NAVY = BLACK          # plain styling: all text black
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK_GRAY = BLACK
MUTED = BLACK
HEADER_FILL = 'D9D9D9'    # light grey header
ROW_BORDER = 'BFBFBF'     # subtle grey between body rows


def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def _set_cell_borders(cell, top=None, bottom=None, left=None,
                       right=None):
    tc_pr = cell._tc.get_or_add_tcPr()
    tcBorders = tc_pr.find(qn('w:tcBorders'))
    if tcBorders is None:
        tcBorders = OxmlElement('w:tcBorders')
        tc_pr.append(tcBorders)
    for side, spec in (('top', top), ('bottom', bottom),
                       ('left', left), ('right', right)):
        existing = tcBorders.find(qn(f'w:{side}'))
        if existing is not None:
            tcBorders.remove(existing)
        if spec is None:
            border = OxmlElement(f'w:{side}')
            border.set(qn('w:val'), 'nil')
            tcBorders.append(border)
            continue
        border = OxmlElement(f'w:{side}')
        border.set(qn('w:val'), spec.get('val', 'single'))
        border.set(qn('w:sz'), str(spec.get('sz', 4)))
        border.set(qn('w:space'), '0')
        border.set(qn('w:color'), spec.get('color', '000000'))
        tcBorders.append(border)


def _apply_plain_row_borders(cell, *, is_header=False):
    _set_cell_borders(
        cell,
        top={'val': 'single', 'sz': 4, 'color': ROW_BORDER}
            if is_header else None,
        bottom={'val': 'single', 'sz': 4, 'color': ROW_BORDER},
        left=None, right=None,
    )


def set_run_style(run, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)


def add_heading(doc, text, *, level=1):
    style_map = {1: 'Heading 1', 2: 'Heading 2', 3: 'Heading 3',
                 4: 'Heading 4'}
    size_map = {1: 16, 2: 14, 3: 12, 4: 11}
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


def add_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_reference(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1.0)
    p.paragraph_format.first_line_indent = Cm(-1.0)
    p.paragraph_format.space_after = Pt(8)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(text)
    set_run_style(run, color=DARK_GRAY, size=10.5)


def add_table(doc, headers, rows, widths_cm, body_size=9,
              bold_first=True):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)
    header_row = table.rows[0]
    for i, h in enumerate(headers):
        cell = header_row.cells[i]
        cell.text = h
        shade_cell(cell, HEADER_FILL)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            set_run_style(run, bold=True, color=BLACK, size=10)
        _apply_plain_row_borders(cell, is_header=True)
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
                        bold=(bold_first and c_idx == 0),
                        color=BLACK,
                        size=body_size,
                    )
            _apply_plain_row_borders(cell)


def add_meta_table(doc, rows):
    """Two-column metadata table for meeting headers (plain style)."""
    table = doc.add_table(rows=len(rows), cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for col_idx, w in enumerate([3.5, 4.5, 3.5, 4.5]):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)
    for r_idx, (k1, v1, k2, v2) in enumerate(rows):
        row = table.rows[r_idx]
        for c_idx, (val, bold) in enumerate([(k1, True), (v1, False),
                                              (k2, True), (v2, False)]):
            cell = row.cells[c_idx]
            cell.text = val
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            for para in cell.paragraphs:
                for run in para.runs:
                    set_run_style(run, bold=bold, color=BLACK,
                                  size=9)
            _apply_plain_row_borders(cell)


def _set_cell_text(cell, text, *, bold=False, italic=False,
                   color=DARK_GRAY, size=9,
                   align=WD_ALIGN_PARAGRAPH.LEFT):
    cell.text = ''
    cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    para = cell.paragraphs[0]
    para.alignment = align
    run = para.add_run(text)
    set_run_style(run, bold=bold, italic=italic, color=color, size=size)


def add_interview_combined_table(doc, meta_rows, theme_blocks):
    """Build one combined table per interview containing metadata,
    Interview Gatherings header, and per-theme Q/A blocks.

    Column layout (4 cols):
      Metadata rows: 4 cells (label, value, label, value)
      Q/A rows: col 0 (Question), cols 1-2 merged (Answer),
                col 3 (Requirement)
      Banner / theme rows: all 4 cells merged
    """
    n_rows = len(meta_rows) + 1  # +1 for "Interview Gatherings"
    for _label, qa_rows in theme_blocks:
        n_rows += 2 + len(qa_rows)  # theme row + Q/A header + data

    table = doc.add_table(rows=n_rows, cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    widths_cm = [3.2, 4.0, 4.0, 4.0]
    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)

    row_idx = 0

    # Metadata rows
    for k1, v1, k2, v2 in meta_rows:
        cells = table.rows[row_idx].cells
        _set_cell_text(cells[0], k1, bold=True, color=BLACK)
        _set_cell_text(cells[1], v1, color=BLACK)
        _set_cell_text(cells[2], k2, bold=True, color=BLACK)
        _set_cell_text(cells[3], v2, color=BLACK)
        for c in cells:
            _apply_plain_row_borders(c)
        row_idx += 1

    # "Meeting Notes" banner row
    cells = table.rows[row_idx].cells
    merged = cells[0].merge(cells[1]).merge(cells[2]).merge(cells[3])
    shade_cell(merged, HEADER_FILL)
    _set_cell_text(merged, 'Meeting Notes',
                   bold=True, color=BLACK, size=10,
                   align=WD_ALIGN_PARAGRAPH.CENTER)
    _apply_plain_row_borders(merged, is_header=True)
    row_idx += 1

    for theme_label, qa_rows in theme_blocks:
        # Theme banner row (merged, grey shade)
        cells = table.rows[row_idx].cells
        merged = (cells[0].merge(cells[1])
                  .merge(cells[2]).merge(cells[3]))
        shade_cell(merged, HEADER_FILL)
        _set_cell_text(merged, f'Theme: {theme_label}',
                       bold=True, color=BLACK, size=9,
                       align=WD_ALIGN_PARAGRAPH.LEFT)
        _apply_plain_row_borders(merged, is_header=True)
        row_idx += 1

        # Q/A column header row
        cells = table.rows[row_idx].cells
        ans_cell = cells[1].merge(cells[2])
        shade_cell(cells[0], HEADER_FILL)
        shade_cell(ans_cell, HEADER_FILL)
        shade_cell(cells[3], HEADER_FILL)
        _set_cell_text(cells[0], 'Question', bold=True, size=9,
                       color=BLACK)
        _set_cell_text(ans_cell, 'Answer', bold=True, size=9,
                       color=BLACK)
        _set_cell_text(cells[3], 'Requirement', bold=True, size=9,
                       color=BLACK)
        for c in (cells[0], ans_cell, cells[3]):
            _apply_plain_row_borders(c, is_header=True)
        row_idx += 1

        # Data rows
        for q, a, req in qa_rows:
            cells = table.rows[row_idx].cells
            ans_cell = cells[1].merge(cells[2])
            _set_cell_text(cells[0], q, size=9, color=BLACK)
            _set_cell_text(ans_cell, a, size=9, color=BLACK)
            _set_cell_text(cells[3], req, size=9, color=BLACK)
            for c in (cells[0], ans_cell, cells[3]):
                _apply_plain_row_borders(c)
            row_idx += 1


# -------------------------------------------------------------------------
# DATA - Interviews
# -------------------------------------------------------------------------

BBK_THEME_1 = [
    ('What is the primary compliance workflow the system should '
     'automate?',
     'Comparing requirements across our three jurisdictional regimes '
     '(Bahrain, India, Kuwait) when assessing whether a single '
     'internal policy is compliant. Currently this is done manually, '
     'which takes weeks per topic.',
     'Two-regulation comparison workflow with cross-jurisdictional '
     'support'),
    ('What document types should the system ingest?',
     'Both external regulations and our own internal policies, '
     'governance documents, and operational SOPs. The system should '
     'treat them as one searchable corpus.',
     'Ingest regulatory corpus and internal BBK policy artefacts'),
    ('How granular should the comparison be?',
     'Each regulation has multiple obligations. We need them compared '
     'one by one, not as a whole document. Otherwise the output is '
     'too vague to be useful.',
     'Per-obligation comparison rather than document-level'),
    ('Should comparisons treat all regimes equally?',
     'No. Some regimes are thinner than others. If a topic is absent '
     'from one jurisdiction, that is still useful information for us. '
     'We need that flagged, not hidden.',
     'Asymmetric equivalence categories including absent as a valid '
     'finding'),
]


BBK_THEME_2 = [
    ('What vocabulary do you currently use for coverage?',
     'Four states: Fully Covered, Partially Covered, Requires Review, '
     'and Not Covered. These align with how our auditors expect to '
     'see findings.',
     'Four-state coverage classification'),
    ('How do you triage compliance gaps?',
     'High, Medium, and Low severity, same as our existing risk '
     'register, so the output integrates with our current workflow.',
     'Three-tier severity vocabulary'),
    ('Who should be allowed to do what in the system?',
     'Three roles: an analyst who does the initial mapping, a '
     'reviewer who validates findings, and an administrator for '
     'system management. Each must only see what their role permits.',
     'Three-role RBAC'),
]


BBK_THEME_3 = [
    ('Should AI-generated findings be auto-approved?',
     'Absolutely not. Every AI finding must go through a reviewer '
     'queue before being treated as authoritative. We need full '
     'human oversight before anything goes to a compliance '
     'committee.',
     'Reviewer validation queue with explicit approval workflow'),
    ('What actions should the reviewer be able to take on each '
     'finding?',
     'Approve, reject, or modify the finding, with a note explaining '
     'the decision. The note becomes part of the audit record.',
     'Approve, reject, or modify actions per finding, with reviewer '
     'notes'),
    ('What export formats are needed for downstream audit?',
     'XLSX for spreadsheet handover to risk teams and PDF for '
     'archival. Both are required.',
     'Multi-format export: XLSX and PDF'),
]


NAIRDC_THEME_1 = [
    ('How should the system handle the handoff between analysts and '
     'reviewers?',
     'Once an analyst completes a mapping or comparison, the work '
     'should be queued for the reviewer\'s attention. Reviewers need '
     'to see what is pending, who created it, and when.',
     'Workflow handoff with a reviewer validation queue'),
    ('How should completed analyses be tracked?',
     'We need a clear status for each item (pending, under review, '
     'approved, rejected) and a way to see the history of who changed '
     'what.',
     'Status lifecycle tracking with auditable transitions'),
]


NAIRDC_THEME_2 = [
    ('What outputs do compliance teams expect from analyses?',
     'Reports they can share with auditors and management, in '
     'standard formats they already use.',
     'Multi-format export (XLSX and PDF)'),
    ('How important is traceability in the final output?',
     'Very. Every finding must be traceable back to its source. '
     'Examiners and auditors will ask where a particular conclusion '
     'came from.',
     'Citation-traceable outputs linked to source documents'),
]


NAIRDC_THEME_3 = [
    ('Who should have access to the system?',
     'Analysts and reviewers as day-to-day users. An administrator '
     'should manage accounts. Self-registration should not be '
     'allowed.',
     'Role-based access with administrator-managed user lifecycle'),
    ('Should AI findings be released without human review?',
     'No. The system should support the analyst\'s work, not replace '
     'the human review. Every finding goes through a reviewer before '
     'being treated as final.',
     'Mandatory human review before AI findings are treated as '
     'authoritative'),
]


# -------------------------------------------------------------------------
# DATA - Research, Document Analysis, Feasibility
# -------------------------------------------------------------------------

RESEARCH_ROWS = [
    ('Hybrid retrieval for RAG',
     'Hybrid retrieval combining dense (semantic) search with sparse '
     '(BM25) search and fusing the ranked lists via reciprocal rank '
     'fusion outperforms either component alone, especially for '
     'legal and technical text where exact terms and identifiers '
     'matter (Rackauckas, 2024).',
     'Hybrid retrieval combining semantic and keyword search with '
     'reciprocal rank fusion'),
    ('Prompt-injection defence for RAG',
     'Documents in the retrieved context can contain hidden '
     'instructions targeting the LLM. Indirect prompt injection '
     'through retrieved content is a documented attack class; recent '
     'defences include instruction-detection classifiers and '
     'isolation of untrusted content within structured prompts '
     '(Wen et al., 2025).',
     'Two-tier prompt-injection scanner with quarantine queue'),
    ('Citation faithfulness for RAG outputs',
     'Fabricated citations are the most common hallucination mode in '
     'retrieval-augmented systems. Verifying that an LLM\'s quoted '
     'text actually appears in a retrieved chunk catches the majority '
     'of fabricated citations (Tamber et al., 2025). Recent work '
     'further distinguishes citation correctness from citation '
     'faithfulness, arguing that an answer can be technically correct '
     'yet not genuinely supported by its cited sources (Wallat et '
     'al., 2025).',
     'Citation verification of every AI-generated quote against '
     'retrieved chunks'),
    ('Grounding evaluation for AI outputs',
     'Beyond binary citation checks, a continuous grounding score '
     'quantifies how well an AI\'s answer is semantically supported '
     'by retrieved evidence (Jacovi et al., 2025). Recent benchmarks '
     'demonstrate that small specialised models reach state-of-the-art '
     'accuracy on grounding evaluation at a fraction of the cost of '
     'large LLM-as-judge approaches (Tang et al., 2024).',
     'Per-output hallucination risk score using a grounding '
     'evaluation model'),
    ('Iterative verify-correct loops in LLM workflows',
     'Iterative agentic orchestration, with draft, verify, correct, '
     'finalise, and fallback phases bounded by retry limits, produces '
     'more reliable structured outputs than single-shot prompting '
     '(Madaan et al., 2023).',
     'Verify-and-correct state-machine orchestration with bounded '
     'retries'),
    ('AI risk governance for regulated industries',
     'Banking systems operating generative AI require risk-management '
     'controls specific to LLM behaviour: confabulation, data '
     'leakage, information-integrity erosion, harmful bias, and '
     'value-chain dependencies. The Generative AI Profile of the '
     'NIST AI Risk Management Framework catalogues twelve risk areas '
     'and over two hundred suggested actions tailored to generative '
     'AI, providing a structured baseline for compliance-driven '
     'deployment (NIST, 2024).',
     'Confabulation control, data-leakage controls, bias monitoring, '
     'and audit logging consistent with NIST AI 600-1 guidance'),
]


DOC_ANALYSIS_ROWS = [
    ('Bahrain Personal Data Protection Law',
     'Bahrain has a comprehensive primary privacy law (PDPL Law 30 '
     'of 2018) supported by ten subordinate orders covering '
     'technical and organisational measures, consent, sensitive data, '
     'DPO, notifications, complaints, and criminal proceedings.',
     'Ingest Bahrain primary law plus all ten subordinate orders'),
    ('India Digital Personal Data Protection regime',
     'India combines a primary statute (DPDP Act 2023) with '
     'supporting rules (DPDP Rules 2025) and operational-circular '
     'RBI directives such as the Cybersecurity Framework, KYC Master '
     'Direction, and Payment Data Localisation Circular.',
     'Ingest DPDP Act, DPDP Rules, and supporting RBI directives'),
    ('Kuwait sectoral privacy regulations',
     'Kuwait\'s privacy regime is comparatively thinner. It is '
     'delivered through sector-specific regulations (CBK for '
     'banking, CITRA for telecoms) rather than a single comprehensive '
     'national privacy law. Documents are materially shorter and '
     'narrower in scope.',
     'Ingest Kuwait sectoral instruments and flag thinner coverage'),
    ('Terminology variation across regimes',
     'Bahrain uses data subject, India\'s DPDP uses data principal, '
     'and Kuwait\'s CBK regulation uses customer or natural person. '
     'The same legal concept appears under different terms.',
     'Cross-jurisdictional term dictionary mapping equivalent terms'),
    ('BBK existing security posture',
     'BBK\'s current authentication practice uses multi-factor '
     'authentication, password rotation, and role-based access. '
     'Audit logs are kept for all privileged actions. These '
     'conventions should be inherited rather than redesigned.',
     'TOTP MFA, password complexity, RBAC, audit logging consistent '
     'with BBK practice'),
]


FEASIBILITY_ROWS = [
    ('Local LLM inference on commodity hardware',
     'Local inference using Ollama (llama3.2:1b) on a laptop without '
     'GPU acceleration took several minutes per single-topic '
     'comparison, making interactive workflows infeasible. A managed '
     'cloud LLM (Claude Haiku 4.5) returned answers in under five '
     'seconds.',
     'Swappable LLM providers: managed cloud as development default, '
     'local as production fallback on GPU hardware'),
    ('Hybrid retrieval accuracy',
     'Hybrid retrieval (BGE-small semantic plus SQLite FTS5 keyword) '
     'achieved hit-rate-at-5 of 0.95 on the evaluation set, versus '
     '0.875 for in-memory BM25 alone. The persistent BM25 store also '
     'enabled metadata filter pushdown.',
     'Persistent SQLite FTS5 plus BGE-small for hybrid retrieval'),
    ('Chunking strategy for legal documents',
     'Header-aware splitting at 512 tokens with 60-token overlap '
     'preserved section structure across all three corpora without '
     'exceeding the embedding model context window. Oversized '
     'articles were kept as parent records for context expansion.',
     '512-token chunks with overlap and parent-child relationship '
     'preservation'),
    ('Cross-encoder reranker selection',
     'The ms-marco-MiniLM-L-6-v2 reranker (approximately 80 MB) '
     'outperformed bge-reranker-large on the project corpus while '
     'being much smaller, supporting commodity-hardware deployment.',
     'Cross-encoder reranking using ms-marco-MiniLM-L-6-v2'),
    ('End-to-end workflow timing',
     'Single-topic comparison ran end-to-end (retrieval, reasoning, '
     'citation verification, structured-output parsing) in under '
     '60 seconds on a typical regulation pair. Single-topic policy '
     'mapping completed in under 90 seconds.',
     'Performance targets: 60 s for comparison, 90 s for mapping'),
]


# -------------------------------------------------------------------------
# DATA - Extended FR catalogue (120 FRs, by category)
# -------------------------------------------------------------------------

EXT_INGESTION = [
    ('1', 'H', 'BBK consultation',
     'The system shall ingest privacy regulations from Bahrain, '
     'India, and Kuwait.'),
    ('2', 'H', 'Brief',
     'The system shall ingest BBK internal privacy policies, '
     'governance documents, and operational SOPs.'),
    ('3', 'H', 'Legal document analysis',
     'The system shall store metadata for every document, including '
     'jurisdiction, version, publication date, and source.'),
    ('4', 'H', 'Technical feasibility study',
     'The system shall convert PDF, DOCX, and HTML documents into '
     'clean text for processing.'),
    ('5', 'H', 'Research paper',
     'The system shall split documents into searchable chunks that '
     'preserve their section structure.'),
    ('6', 'M', 'Technical feasibility study',
     'The system shall tag each chunk by its legal-text type '
     '(operative rule, definition, preamble, or general).'),
    ('7', 'H', 'Research paper',
     'The system shall make every chunk searchable by meaning '
     '(semantic) and by keyword (full-text).'),
    ('8', 'M', 'Discussion',
     'The system shall process ingestion in the background with '
     'live progress reporting.'),
    ('9', 'H', 'Brief',
     'The system shall provide an administrative interface for '
     'document uploads.'),
]


EXT_RETRIEVAL = [
    ('10', 'H', 'Research paper',
     'The system shall retrieve and rank chunks using combined '
     'semantic and keyword search.'),
    ('11', 'M', 'Research paper',
     'The system shall rerank retrieved results to improve relevance '
     'before analysis.'),
    ('12', 'H', 'Research paper',
     'The system shall expand queries using equivalent legal '
     'terminology across jurisdictions.'),
    ('13', 'M', 'Discussion',
     'The system shall filter retrieval results by jurisdiction, '
     'topic, subcategory, and document title.'),
    ('14', 'M', 'Technical feasibility study',
     'The system shall preserve parent-child chunk relationships '
     'during retrieval.'),
    ('15', 'H', 'Legal document analysis',
     'The system shall return citation-preserving results linked to '
     'their source documents.'),
]


EXT_REASONING = [
    ('16', 'H', 'Meeting with BBK',
     'The system shall compare obligations between two selected '
     'regulatory frameworks for a chosen compliance topic.'),
    ('17', 'H', 'Legal document analysis',
     'The system shall identify similarities, differences, and '
     'conflicts between compared regulatory obligations.'),
    ('18', 'H', 'Legal document analysis',
     'The system shall determine equivalence levels between '
     'obligations across jurisdictions.'),
    ('19', 'M', 'Legal document analysis',
     'The system shall assess comparative strictness between '
     'regulatory frameworks across procedural, substantive, and '
     'enforcement dimensions.'),
    ('20', 'H', 'Meeting with BBK',
     'The system shall map internal policy documents against one or '
     'more regulations.'),
    ('21', 'H', 'BBK consultation',
     'The system shall classify policy coverage as Fully Covered, '
     'Partially Covered, Requires Review, or Not Covered.'),
    ('22', 'M', 'Meeting with NAIRDC',
     'The system shall generate remediation recommendations for '
     'uncovered obligations and identified compliance gaps.'),
    ('23', 'M', 'Legal document analysis',
     'The system shall detect compliance topics contained within '
     'uploaded policy documents.'),
    ('24', 'M', 'Legal document analysis',
     'The system shall classify document chunks into predefined '
     'compliance topics at ingest time and on demand during '
     'workflow execution.'),
    ('25', 'H', 'Discussion',
     'The system shall automatically route policy mapping workflows '
     'to relevant regulations based on detected compliance topics.'),
    ('26', 'H', 'Meeting with BBK',
     'The system shall aggregate uncovered obligations from multiple '
     'jurisdictions into a unified gap analysis report.'),
    ('27', 'H', 'BBK consultation',
     'The system shall prioritise compliance gaps using severity '
     'levels of High, Medium, and Low.'),
    ('28', 'M', 'Discussion',
     'The system shall return partially verified results when full '
     'citation verification cannot be completed.'),
    ('29', 'M', 'Legal document analysis',
     'The system shall maintain a dictionary of equivalent legal '
     'terminology across supported jurisdictions.'),
    ('30', 'H', 'Meeting with BBK',
     'The system shall support a strict evidence mode that restricts '
     'reasoning to analyst-selected documents only.'),
    ('31', 'M', 'Discussion',
     'The system shall support an open evidence mode that augments '
     'selected documents with related chunks from the broader '
     'corpus.'),
]


EXT_WEB = [
    ('32', 'H', 'Meeting with BBK',
     'The system shall provide a home dashboard summarising overall '
     'compliance posture.'),
    ('33', 'H', 'BBK consultation',
     'The system shall display overall compliance coverage '
     'percentages.'),
    ('34', 'H', 'BBK consultation',
     'The system shall display compliance coverage breakdowns by '
     'jurisdiction.'),
    ('35', 'M', 'Meeting with NAIRDC',
     'The system shall display pending compliance actions and '
     'workflow prompts.'),
    ('36', 'M', 'Discussion',
     'The system shall display recent analyses and document '
     'ingestion activities.'),
    ('37', 'H', 'Meeting with BBK',
     'The system shall provide a library workspace for browsing '
     'regulations, internal policies, obligations, and legal '
     'terminology dictionaries.'),
    ('38', 'H', 'Meeting with BBK',
     'The system shall support cross-reference search across the '
     'document corpus.'),
    ('39', 'M', 'Discussion',
     'The system shall support user-defined document tagging.'),
    ('40', 'H', 'Meeting with BBK',
     'The system shall support analyst-driven document uploads.'),
    ('41', 'M', 'Technical feasibility study',
     'The system shall display document metadata previews before '
     'ingestion.'),
    ('42', 'M', 'BBK consultation',
     'The system shall display live ingestion progress during '
     'document processing.'),
    ('43', 'M', 'Meeting with NAIRDC',
     'The system shall support document deletion.'),
    ('44', 'H', 'BBK consultation',
     'The system shall provide full-text document viewing with '
     'citation labels.'),
    ('45', 'H', 'Meeting with BBK',
     'The system shall provide a comparison workspace for '
     'configuring cross-regulation comparisons.'),
    ('46', 'M', 'BBK consultation',
     'The system shall display live workflow progress during '
     'comparison analysis.'),
    ('47', 'H', 'Meeting with BBK',
     'The system shall provide comparison results through overview, '
     'clauses, equivalency graph, relationship map, topic map, and '
     'insights views.'),
    ('48', 'M', 'Legal document analysis',
     'The system shall display strictness indicators for compared '
     'regulatory frameworks.'),
    ('49', 'M', 'Meeting with NAIRDC',
     'The system shall allow reviewers to transition per-clause '
     'statuses and record reviewer notes.'),
    ('50', 'H', 'Meeting with BBK',
     'The system shall provide a policy mapping workspace for '
     'configuring policy-to-regulation mapping workflows.'),
    ('51', 'M', 'BBK consultation',
     'The system shall display live workflow progress during policy '
     'mapping analysis.'),
    ('52', 'L', 'Discussion',
     'The system shall allow analysts to cancel running policy '
     'mapping workflows.'),
    ('53', 'H', 'Meeting with BBK',
     'The system shall provide per-obligation mapping results with '
     'supporting evidence panels.'),
    ('54', 'M', 'Meeting with NAIRDC',
     'The system shall allow analysts to manually override '
     'obligation coverage classifications.'),
    ('55', 'M', 'Meeting with NAIRDC',
     'The system shall allow reviewers to transition per-obligation '
     'statuses and record reviewer notes.'),
    ('56', 'M', 'Meeting with BBK',
     'The system shall allow analysts to record manual remediation '
     'recommendations for identified compliance gaps.'),
    ('57', 'M', 'BBK consultation',
     'The system shall provide a dual-mapping view for comparing '
     'one policy against two regulations simultaneously.'),
    ('58', 'H', 'BBK consultation',
     'The system shall support workflow handoff from analysts to '
     'reviewers.'),
    ('59', 'H', 'BBK consultation',
     'The system shall provide reviewer approval workflows for '
     'completed analyses.'),
    ('60', 'H', 'BBK consultation',
     'The system shall provide a reviewer validation queue for '
     'reviewing AI-generated findings.'),
    ('61', 'H', 'BBK consultation',
     'The system shall allow reviewers to approve, reject, or modify '
     'AI-generated findings.'),
    ('62', 'H', 'Meeting with BBK',
     'The system shall support export of analysis reports in XLSX '
     'and PDF formats.'),
    ('63', 'H', 'Meeting with BBK',
     'The system shall provide a cross-jurisdiction gap analysis '
     'workspace.'),
    ('64', 'H', 'BBK consultation',
     'The system shall provide a unified compliance gap register.'),
    ('65', 'M', 'Legal document analysis',
     'The system shall provide a regulatory conflict analysis '
     'workspace.'),
    ('66', 'M', 'Discussion',
     'The system shall allow reviewers and administrators to assign '
     'compliance gaps to users with due dates.'),
    ('67', 'M', 'Existing system analysis',
     'The system shall provide a role-based analytics dashboard '
     'summarising compliance coverage, gaps, conflicts, and reviewer '
     'activity.'),
    ('68', 'M', 'Existing system analysis',
     'The system shall provide interactive compliance coverage '
     'heatmaps.'),
    ('69', 'H', 'BBK consultation',
     'The system shall maintain an audit history of all mutating '
     'system actions.'),
    ('70', 'M', 'BBK consultation',
     'The system shall provide detailed audit event views.'),
    ('71', 'H', 'Legal document analysis',
     'The system shall support citation click-through navigation to '
     'source documents with highlighted evidence excerpts.'),
    ('72', 'M', 'Legal document analysis',
     'The system shall provide inline legal terminology translation '
     'across jurisdictions.'),
]


EXT_COPILOT = [
    ('73', 'H', 'Meeting with BBK',
     'The system shall provide a global AI Copilot chat overlay '
     'accessible from every page.'),
    ('74', 'M', 'Discussion',
     'The system shall classify each Copilot query by intent and '
     'select the appropriate retrieval source.'),
    ('75', 'H', 'Research paper',
     'The system shall ground every Copilot answer in retrieved '
     'corpus chunks before responding.'),
    ('76', 'M', 'Legal document analysis',
     'The system shall preferentially ground Copilot answers in '
     'reviewer-approved analyses, falling back to indexed regulatory '
     'text otherwise.'),
    ('77', 'L', 'BBK consultation',
     'The system shall allow users to opt in to draft (unreviewed) '
     'analyses as a grounding source via a per-session toggle.'),
    ('78', 'M', 'Meeting with BBK',
     'The system shall allow users to constrain Copilot retrieval '
     'to a single selected document.'),
    ('79', 'H', 'Research paper',
     'The system shall route Copilot queries through the same '
     'verification pipeline used by structured reasoning workflows.'),
    ('80', 'H', 'Research paper',
     'The system shall return Copilot answers with regulation-name, '
     'article-reference, and excerpt-level citations.'),
    ('81', 'M', 'Research paper',
     'The system shall report a confidence score and a hallucination '
     'risk score alongside every Copilot answer.'),
    ('82', 'M', 'Meeting with NAIRDC',
     'The system shall compute and surface a Copilot readiness state '
     'based on the availability of regulations, internal policies, '
     'approved comparisons, and approved mappings.'),
    ('83', 'L', 'Discussion',
     'The system shall display a fallback explanation message when '
     'Copilot answers from raw regulatory text instead of approved '
     'analyses.'),
    ('84', 'L', 'Technical feasibility study',
     'The system shall maintain per-user Copilot conversation '
     'history across page navigation, retaining the most recent '
     'twenty messages.'),
    ('85', 'L', 'Discussion',
     'The system shall allow users to clear Copilot conversation '
     'history.'),
    ('86', 'M', 'Research paper',
     'The system shall degrade gracefully when no relevant chunks '
     'are retrieved or when the AI provider is unavailable.'),
]


EXT_SECURITY = [
    ('87', 'H', 'Existing system analysis',
     'The system shall require username and password authentication '
     'for every user account.'),
    ('88', 'H', 'Existing system analysis',
     'The system shall require time-based one-time password (TOTP) '
     'multi-factor authentication for every user account.'),
    ('89', 'H', 'Existing system analysis',
     'The system shall enforce TOTP enrolment before any user can '
     'access business functionality after first login.'),
    ('90', 'M', 'Existing system analysis',
     'The system shall apply multi-factor authentication to the '
     'Django administrative interface.'),
    ('91', 'H', 'Existing system analysis',
     'The system shall enforce password complexity requirements of '
     'minimum twelve characters, including uppercase, lowercase, '
     'digit, and symbol classes.'),
    ('92', 'M', 'Existing system analysis',
     'The system shall reject passwords that contain the user\'s '
     'username or email substring.'),
    ('93', 'H', 'Existing system analysis',
     'The system shall require users to change temporary passwords '
     'on first login or after an administrator-initiated reset.'),
    ('94', 'H', 'Existing system analysis',
     'The system shall lock user accounts after a configurable '
     'threshold of failed login attempts, keyed on both username and '
     'source IP address.'),
    ('95', 'H', 'Existing system analysis',
     'The system shall log users out automatically after a '
     'configurable period of inactivity.'),
    ('96', 'M', 'Existing system analysis',
     'The system shall enforce an absolute session lifetime '
     'independent of activity.'),
    ('97', 'H', 'Research paper',
     'The system shall harden session and CSRF cookies with '
     'HttpOnly, SameSite, and Secure flags in production.'),
    ('98', 'H', 'Existing system analysis',
     'The system shall terminate all active sessions of a user when '
     'their role, password, or MFA configuration is changed by an '
     'administrator.'),
    ('99', 'L', 'Meeting with BBK',
     'The system shall optionally restrict access to a configurable '
     'country allowlist using GeoIP lookups.'),
    ('100', 'H', 'BBK consultation',
     'The system shall enforce role-based access control with three '
     'roles: Compliance Analyst, Legal Reviewer, and Administrator.'),
    ('101', 'H', 'Existing system analysis',
     'The system shall enforce role checks at every authenticated '
     'route and on every privileged action.'),
    ('102', 'H', 'Existing system analysis',
     'The system shall not provide self-registration; user accounts '
     'shall be created by administrators only.'),
    ('103', 'H', 'Existing system analysis',
     'The system shall allow administrators to create user accounts '
     'and assign one of the three roles.'),
    ('104', 'H', 'Existing system analysis',
     'The system shall allow administrators to change user roles, '
     'disable accounts, reset passwords, and reset MFA devices.'),
    ('105', 'M', 'Existing system analysis',
     'The system shall deliver temporary credentials to new users '
     'by email and require them to change the password on first '
     'login.'),
    ('106', 'M', 'Technical feasibility study',
     'The system shall support SMTP-based email delivery for '
     'credential and notification messages.'),
    ('107', 'H', 'Research paper',
     'The system shall enforce Cross-Site Request Forgery (CSRF) '
     'protection on every state-changing request.'),
    ('108', 'H', 'Research paper',
     'The system shall set hardened HTTP security headers including '
     'HSTS, X-Frame-Options, X-Content-Type-Options, and '
     'Referrer-Policy.'),
    ('109', 'H', 'Research paper',
     'The system shall automatically redirect HTTP requests to '
     'HTTPS in production and enforce a one-year HSTS policy with '
     'subdomain coverage.'),
    ('110', 'M', 'Research paper',
     'The system shall enforce a Content Security Policy with an '
     'explicit allowlist of script, style, font, image, and '
     'form-action sources.'),
    ('111', 'H', 'BBK consultation',
     'The system shall maintain a global audit log of every '
     'security-relevant action, capturing actor, role at time of '
     'action, IP address, target object, and metadata.'),
    ('112', 'H', 'Existing system analysis',
     'The system shall automatically log authentication events '
     '(login, logout, login failure, MFA enrolment, idle timeout) '
     'without requiring per-view instrumentation.'),
    ('113', 'M', 'BBK consultation',
     'The system shall maintain a per-result lifecycle audit trail '
     'recording every status transition with actor, from-state, '
     'to-state, and JSON diff.'),
    ('114', 'M', 'BBK consultation',
     'The system shall provide an administrator-only audit log '
     'viewer with filtering by category, user, and date range.'),
    ('115', 'H', 'Research paper',
     'The system shall scan every ingested chunk for prompt-injection '
     'content using a catalogue of known attack patterns.'),
    ('116', 'M', 'Research paper',
     'The system shall escalate borderline chunks to a second-tier '
     'classifier with hardened prompting.'),
    ('117', 'H', 'Meeting with NAIRDC',
     'The system shall quarantine flagged chunks until an '
     'administrator approves or rejects them, recording every '
     'decision in the audit log.'),
    ('118', 'H', 'Research paper',
     'The system shall verify every AI-generated citation against '
     'the underlying retrieved chunks before returning results, '
     'rejecting any citation whose quoted text does not appear in '
     'source.'),
    ('119', 'H', 'Research paper',
     'The system shall constrain AI outputs to a strict structured '
     'schema, automatically repairing and rejecting malformed '
     'responses.'),
    ('120', 'H', 'Technical feasibility study',
     'The system shall enforce document-scope filtering at the '
     'database layer so the language model cannot access chunks '
     'outside the analyst-selected scope.'),
]


EXT_USR_ANALYST = [
    ('USR-01', 'Compliance Analyst',
     'upload an internal BBK policy and receive a structured '
     'coverage analysis against Bahrain, India, and Kuwait',
     'I can identify compliance gaps without manually reading every '
     'regulation',
     'Analysis completion within approximately 90 seconds'),
    ('USR-02', 'Compliance Analyst',
     'see every finding include a citation back to the exact '
     'regulatory clause it relies on',
     'I can present audit-defensible evidence',
     'Every finding carries a clause-level citation'),
    ('USR-03', 'Compliance Analyst',
     'filter retrieval results by jurisdiction, regulator, and '
     'document type',
     'I can focus on the regime relevant to a specific question',
     'Filter controls return matching results on a warm cache'),
    ('USR-04', 'Compliance Analyst',
     'export analysis reports in XLSX and PDF formats',
     'I can share findings using stakeholders\' preferred formats',
     'Both formats downloadable from a single view'),
    ('USR-05', 'Compliance Analyst',
     'run a comparison between two regulations on a chosen topic',
     'I can see how obligations differ between regimes',
     'Comparison completes for a typical regulation pair within a '
     'reasonable interactive window'),
    ('USR-06', 'Compliance Analyst',
     'search the library workspace across regulations, internal '
     'policies, and the term dictionary',
     'I can find relevant material quickly during analysis',
     'Cross-corpus search returns ranked results on a warm cache'),
    ('USR-07', 'Compliance Analyst',
     'browse the cross-jurisdiction term dictionary',
     'I can resolve terminology differences when interpreting '
     'clauses',
     'Every term maps to its equivalents across all supported '
     'jurisdictions'),
    ('USR-08', 'Compliance Analyst',
     'manually override an AI-generated coverage classification '
     'with a written reason',
     'my expert judgement supersedes machine output when needed',
     'Override and reason persisted to the audit log'),
    ('USR-09', 'Compliance Analyst',
     'view a document with its citation-labelled excerpts '
     'highlighted',
     'I can verify findings against the source text',
     'Highlighted span matches the cited clause'),
    ('USR-10', 'Compliance Analyst',
     'use the AI Copilot to ask grounded questions scoped to a '
     'single document or run',
     'I can clarify specific findings without leaving my workspace',
     'Every Copilot answer carries a citation to retrieved chunks'),
    ('USR-11', 'Compliance Analyst',
     'see live progress for long-running mapping or comparison '
     'workflows',
     'I know whether to wait or come back later',
     'Progress updates appear at regular intervals during execution'),
    ('USR-12', 'Compliance Analyst',
     'add a remediation note to each compliance gap',
     'the reviewer sees my suggested fix',
     'Note persisted with the gap record'),
]


EXT_USR_REVIEWER = [
    ('USR-13', 'Legal Reviewer',
     'see each AI-generated finding flagged with a confidence score '
     'and a list of supporting evidence chunks',
     'I can prioritise which findings require deeper human review',
     'Every finding carries a confidence value and at least one '
     'linked evidence chunk'),
    ('USR-14', 'Legal Reviewer',
     'approve, reject, or annotate AI-generated findings',
     'outputs become an auditable record of human-validated '
     'compliance positions',
     'Reviewer actions persisted to the audit log within the same '
     'request'),
    ('USR-15', 'Legal Reviewer',
     'have findings flagged with hallucination or injection signals '
     'routed into a quarantine queue',
     'suspect content does not reach decision-makers without review',
     'Flagged items held until a reviewer dispositions them'),
    ('USR-16', 'Legal Reviewer',
     'compare a policy clause side-by-side against equivalent '
     'clauses across all three jurisdictions',
     'I can defensibly decide whether coverage is equivalent, '
     'stronger, weaker, partial, or absent',
     'Comparison view renders all available analogues in a single '
     'screen'),
    ('USR-17', 'Legal Reviewer',
     'see a prioritised queue of pending analyst submissions',
     'I can address the most urgent first',
     'Queue shows pending count, submitter, and submission '
     'timestamp'),
    ('USR-18', 'Legal Reviewer',
     'filter the pending queue by submitter, jurisdiction, and '
     'submission date',
     'I can focus on a specific analyst or topic area',
     'Filtered queue returns matching items'),
    ('USR-19', 'Legal Reviewer',
     'see the full audit trail of an analysis before deciding',
     'I understand the analyst\'s reasoning',
     'Every status transition and note appears in chronological '
     'order'),
    ('USR-20', 'Legal Reviewer',
     'export approved analyses with the SHA-256 hash chain footer '
     'for audit handover',
     'downstream auditors can verify integrity',
     'Every exported PDF and XLSX carries the hash chain'),
    ('USR-21', 'Legal Reviewer',
     'assign compliance gaps to specific users with due dates',
     'remediation tasks have clear ownership and timelines',
     'Every gap record carries assignee and due-date fields'),
    ('USR-22', 'Legal Reviewer',
     'view comparison topic-scan results showing equivalence '
     'verdicts per cluster',
     'I can review at a higher abstraction level than per-clause',
     'Every topic cluster carries an equivalence verdict'),
    ('USR-23', 'Legal Reviewer',
     'transition per-clause statuses with notes',
     'review state is captured at the right granularity',
     'Audit trail records every transition with reviewer notes'),
    ('USR-24', 'Legal Reviewer',
     'see strictness indicators between compared regulatory '
     'frameworks',
     'I can assess which regime imposes the higher bar',
     'Strictness indicator appears on every comparison view'),
]


EXT_USR_ADMIN = [
    ('USR-25', 'Administrator',
     'view a system-health dashboard summarising LLM provider '
     'status, vector store size, lexical index health, active '
     'sessions, and recent reasoning failures',
     'I can spot operational issues before they impact analysts',
     'Dashboard refreshes on demand and reflects the last 24 hours'),
    ('USR-26', 'Administrator',
     'assign and revoke user roles (Analyst, Reviewer, '
     'Administrator)',
     'access is bounded by responsibility',
     'Every role change produces an audit-log entry'),
    ('USR-27', 'Administrator',
     'swap the active LLM provider via configuration without '
     'redeploying the application',
     'the system can move between managed cloud and on-premises '
     'inference',
     'Change takes effect after a configuration reload with no code '
     'modification'),
    ('USR-28', 'Administrator',
     'review the audit log and filter entries by user, action, and '
     'date range',
     'I can investigate incidents and demonstrate compliance during '
     'audits',
     'Filtered queries return matching entries within a reasonable '
     'time'),
    ('USR-29', 'Administrator',
     'create new analyst, reviewer, and administrator accounts with '
     'temporary credentials',
     'new staff can be onboarded',
     'Every account creation produces an audit log entry'),
    ('USR-30', 'Administrator',
     'reset MFA devices for locked-out users after identity '
     'verification',
     'legitimate users can regain access without compromising '
     'security',
     'Every MFA reset produces an audit log entry'),
    ('USR-31', 'Administrator',
     'force a password rotation for flagged accounts',
     'compromised credentials are invalidated immediately',
     'Next login enforces the password change'),
    ('USR-32', 'Administrator',
     'review the quarantine queue of flagged ingested chunks and '
     'approve or reject each',
     'the corpus remains free of injection attacks',
     'Every chunk decision produces an audit log entry'),
    ('USR-33', 'Administrator',
     'configure session timeout, MFA enforcement, and geo-fencing '
     'via environment variables',
     'security policies can be tightened without code changes',
     'Configuration reload takes effect without redeployment'),
    ('USR-34', 'Administrator',
     'monitor failed-login attempts and account lockouts',
     'I can spot brute-force activity early',
     'Failure counts surface on the monitoring dashboard'),
    ('USR-35', 'Administrator',
     'verify the hash chain integrity of exported reports',
     'I can detect tampering or substitution of audit artefacts',
     'Nightly verification job reports chain completeness'),
    ('USR-36', 'Administrator',
     'monitor the document ingestion queue and retry failed jobs',
     'all uploaded documents successfully reach the index',
     'Every retry attempt is logged with success or failure status'),
]


REFERENCES = [
    'Jacovi, A., Wang, A., Alberti, C., Tao, C., Lipovetz, J., '
    'Olszewska, K., Haas, L., Liu, M., Keating, N., Bloniarz, A., '
    'Saroufim, C., Fry, C., Marcus, D., Kukliansky, D., Tomar, G. S., '
    'Swirhun, J., Xing, J., Wang, L., Gurumurthy, M., ... Das, D. '
    '(2025). The FACTS Grounding Leaderboard: Benchmarking LLMs\' '
    'ability to ground responses to long-form input '
    '(arXiv:2501.03200). arXiv. '
    'https://arxiv.org/abs/2501.03200',

    'Madaan, A., Tandon, N., Gupta, P., Hallinan, S., Gao, L., '
    'Wiegreffe, S., Alon, U., Dziri, N., Prabhumoye, S., Yang, Y., '
    'Gupta, S., Majumder, B. P., Hermann, K., Welleck, S., '
    'Yazdanbakhsh, A., & Clark, P. (2023). Self-Refine: Iterative '
    'refinement with self-feedback. In Advances in Neural '
    'Information Processing Systems 36. '
    'https://arxiv.org/abs/2303.17651',

    'National Institute of Standards and Technology. (2024). '
    'Artificial intelligence risk management framework: Generative '
    'artificial intelligence profile (NIST AI 600-1). U.S. '
    'Department of Commerce. https://doi.org/10.6028/NIST.AI.600-1',

    'Rackauckas, Z. (2024). RAG-Fusion: A new take on '
    'retrieval-augmented generation. International Journal on '
    'Natural Language Computing, 13(1), 37-47. '
    'https://arxiv.org/abs/2402.03367',

    'Tamber, M. S., Bao, F. S., Xu, C., Luo, G., Kazi, S., Bae, M., '
    'Li, M., Mendelevitch, O., Qu, R., & Lin, J. (2025). '
    'Benchmarking LLM faithfulness in RAG with evolving '
    'leaderboards. In Findings of the Association for Computational '
    'Linguistics: EMNLP 2025 Industry Track. '
    'https://arxiv.org/abs/2505.04847',

    'Tang, L., Laban, P., & Durrett, G. (2024). MiniCheck: '
    'Efficient fact-checking of LLMs on grounding documents. In '
    'Proceedings of the 2024 Conference on Empirical Methods in '
    'Natural Language Processing (pp. 8818-8847). Association for '
    'Computational Linguistics. '
    'https://aclanthology.org/2024.emnlp-main.499/',

    'Wallat, J., Lange, T., Anand, A., & de Rijke, M. (2025). '
    'Correctness is not faithfulness in retrieval-augmented '
    'generation attributions. In Proceedings of the 2025 '
    'International ACM SIGIR Conference on Innovative Concepts and '
    'Theories in Information Retrieval. '
    'https://doi.org/10.1145/3731120.3744592',

    'Wen, T., Wang, C., Yang, X., Tang, H., Xie, Y., Lyu, L., Dou, '
    'Z., & Wu, F. (2025). Defending against indirect prompt '
    'injection by instruction detection. In Findings of the '
    'Association for Computational Linguistics: EMNLP 2025. '
    'https://aclanthology.org/2025.findings-emnlp.1060/',
]


# -------------------------------------------------------------------------
# WRITERS
# -------------------------------------------------------------------------

def write_interview_qa(doc, theme_label, rows):
    add_paragraph(doc, theme_label, bold=True, color=NAVY,
                  space_after=4)
    add_table(
        doc,
        headers=['Question', 'Answer', 'Derived requirement'],
        rows=rows,
        widths_cm=[4.5, 7.0, 4.5],
        body_size=8,
        bold_first=False,
    )


def write_a11(doc):
    add_heading(doc, 'A1.1 Stakeholder Meeting Records', level=2)
    add_paragraph(
        doc,
        'Two structured stakeholder meetings were held with the '
        'project sponsors. Each meeting is recorded below in a '
        'single combined table containing the meeting metadata, '
        'the "Meeting Notes" banner, and the per-theme question, '
        'answer, and derived requirement.',
    )

    add_heading(doc,
                'A1.1.1 BBK Stakeholder Meeting: Project Scope '
                'and Compliance Conventions', level=3)
    add_caption(doc, 'Table.',
                'BBK stakeholder meeting record.')
    bbk_meta = [
        ('Project title', 'Cross-Jurisdictional Privacy Compliance '
         'Analyzer', 'Project manager', 'Zainab Hammad'),
        ('Date created', '15 March 2026', 'Last updated',
         '16 March 2026'),
        ('Meeting date', '15 March 2026, 10:00 AM',
         'Participant', 'BBK Compliance Lead (via NAIRDC PM proxy)'),
    ]
    bbk_themes = [
        ('Project scope and workflow coverage', BBK_THEME_1),
        ('Compliance vocabulary and coverage classification',
         BBK_THEME_2),
        ('Reviewer workflow and export', BBK_THEME_3),
    ]
    add_interview_combined_table(doc, bbk_meta, bbk_themes)

    add_heading(doc,
                'A1.1.2 NAIRDC Consultation: Workflow Coordination '
                'and Reporting', level=3)
    add_caption(doc, 'Table.',
                'NAIRDC stakeholder consultation record.')
    nairdc_meta = [
        ('Project title', 'Cross-Jurisdictional Privacy Compliance '
         'Analyzer', 'Project manager', 'Zainab Hammad'),
        ('Date created', '20 March 2025', 'Last updated',
         '25 March 2026'),
        ('Meeting date', '12 February 2026, 2:00 PM',
         'Participant', 'NAIRDC Project Manager'),
    ]
    nairdc_themes = [
        ('Workflow coordination between analysts and reviewers',
         NAIRDC_THEME_1),
        ('Reporting and auditability', NAIRDC_THEME_2),
        ('Access and role management', NAIRDC_THEME_3),
    ]
    add_interview_combined_table(doc, nairdc_meta, nairdc_themes)


def write_a12(doc):
    add_heading(doc, 'A1.2 Research Findings', level=2)
    add_paragraph(
        doc,
        'The following research areas informed the technical '
        'requirements that no stakeholder articulated directly. Each '
        'finding cites a recent peer-reviewed or pre-print source.',
    )
    add_caption(doc, 'Table.',
                'Research findings and derived requirements.')
    add_table(
        doc,
        headers=['Research topic', 'Findings', 'Derived requirement'],
        rows=RESEARCH_ROWS,
        widths_cm=[3.5, 8.5, 4.0],
        body_size=8,
        bold_first=True,
    )


def write_a13(doc):
    add_heading(doc, 'A1.3 Document Analysis Findings', level=2)
    add_paragraph(
        doc,
        'The following observations emerged from analysis of the '
        'project brief, the regulatory corpus of the three target '
        'jurisdictions, and BBK\'s existing security posture.',
    )
    add_caption(doc, 'Table.',
                'Document analysis findings and derived requirements.')
    add_table(
        doc,
        headers=['Reference', 'Notes', 'Derived requirement'],
        rows=DOC_ANALYSIS_ROWS,
        widths_cm=[3.5, 8.5, 4.0],
        body_size=8,
        bold_first=True,
    )


def write_a14(doc):
    add_heading(doc, 'A1.4 Technical Feasibility Study Findings',
                level=2)
    add_paragraph(
        doc,
        'A short prototyping phase produced the following findings, '
        'which became performance targets and architecture '
        'requirements.',
    )
    add_caption(doc, 'Table.',
                'Technical feasibility study findings and derived '
                'requirements.')
    add_table(
        doc,
        headers=['Topic', 'Findings', 'Derived requirement'],
        rows=FEASIBILITY_ROWS,
        widths_cm=[3.5, 8.5, 4.0],
        body_size=8,
        bold_first=True,
    )


def write_a15(doc):
    add_heading(doc, 'A1.5 Extended Functional Requirements Catalogue',
                level=2)
    add_paragraph(
        doc,
        'This subsection presents the complete catalogue of 120 '
        'functional requirements organised across six categories. '
        'The 20 highest-priority requirements appear in main-body '
        '§3.1.3 as FR1-FR20. The full catalogue here records every '
        'observable behaviour the system supports, with elicitation '
        'source and MoSCoW priority. Each category is presented in '
        'its own table at the end of this subsection.',
    )

    sections = [
        ('A1.5.1 Document Ingestion', EXT_INGESTION,
         'Table.',
         'Document ingestion functional requirements (extended).'),
        ('A1.5.2 Retrieval Layer', EXT_RETRIEVAL,
         'Table.',
         'Retrieval layer functional requirements (extended).'),
        ('A1.5.3 Reasoning and Analysis', EXT_REASONING,
         'Table.',
         'Reasoning and analysis functional requirements (extended).'),
        ('A1.5.4 Web Application', EXT_WEB,
         'Table.',
         'Web application functional requirements (extended).'),
        ('A1.5.5 Copilot Agent', EXT_COPILOT,
         'Table.',
         'Copilot agent functional requirements (extended).'),
        ('A1.5.6 Security and Access Control', EXT_SECURITY,
         'Table.',
         'Security and access control functional requirements '
         '(extended).'),
    ]

    for heading_text, rows, caption_label, caption_text in sections:
        add_heading(doc, heading_text, level=3)
        add_caption(doc, caption_label, caption_text)
        add_table(
            doc,
            headers=['ID', 'Pri', 'Source', 'Requirement'],
            rows=rows,
            widths_cm=[1.0, 0.8, 2.5, 11.7],
            body_size=8,
            bold_first=True,
        )


def write_a16(doc):
    add_heading(doc, 'A1.6 Extended User-Voice Requirements Catalogue',
                level=2)
    add_paragraph(
        doc,
        'This subsection presents the complete user-voice '
        'requirements catalogue of 36 stories, twelve per role. '
        'The 12 highest-priority stories appear in main-body '
        '§3.1.2 as a representative subset. Each story records '
        'the user type, the action, the result, and a '
        'measurable success criterion. The three tables below '
        'present the stories grouped by role.',
    )

    usr_sections = [
        ('Compliance Analyst', EXT_USR_ANALYST, 'Table.',
         'Extended Compliance Analyst user-voice requirements.'),
        ('Legal Reviewer', EXT_USR_REVIEWER, 'Table.',
         'Extended Legal Reviewer user-voice requirements.'),
        ('Administrator', EXT_USR_ADMIN, 'Table.',
         'Extended Administrator user-voice requirements.'),
    ]

    for role_label, rows, caption_label, caption_text in usr_sections:
        add_heading(doc, role_label, level=3)
        add_caption(doc, caption_label, caption_text)
        add_table(
            doc,
            headers=['ID', 'As a...', 'I want to...', 'So that...',
                     'Measured by...'],
            rows=rows,
            widths_cm=[1.4, 2.8, 4.2, 4.2, 3.4],
            body_size=8,
            bold_first=True,
        )


def write_references(doc):
    add_heading(doc, 'References for Appendix 1', level=2)
    add_paragraph(
        doc,
        'The following references support the research findings in '
        'A1.2. Sources already cited in main-body sections (§2.1 '
        'Related Theory, §3.2.7 OWASP Coverage) are not duplicated '
        'here.',
    )
    for ref in REFERENCES:
        add_reference(doc, ref)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'appendix_1_requirements.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = (out_dir /
                             f'appendix_1_requirements_v{n}.docx')
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, 'Appendix 1 — Requirements', level=1)
    add_paragraph(
        doc,
        'This appendix records the underlying evidence gathered '
        'during the requirements-elicitation phase referenced in '
        '§3.1, organised by elicitation technique (stakeholder '
        'meetings, research, document analysis, technical '
        'feasibility study), and concludes with the extended '
        'functional requirements catalogue.',
    )

    write_a11(doc)
    write_a12(doc)
    write_a13(doc)
    write_a14(doc)
    write_a15(doc)
    write_references(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
