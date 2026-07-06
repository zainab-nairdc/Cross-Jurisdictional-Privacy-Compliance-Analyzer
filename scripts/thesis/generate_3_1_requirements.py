"""Generate §3.1 Requirements as a docx.

Output: thesis_docs/3_1_requirements.docx

Rubric coverage:
  (1) Requirements elicitation methodology
  (2) Functional requirements (20, categorised, prioritised)
  (3) Non-functional requirements (20, categorised, prioritised)
  (4) Constraints (6)
  (5) Appendix 1 referenced for supporting evidence

Tables placed at the END of each subsection per supervisor rule.
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
    """Apply per-side borders to a table cell.

    Each argument is either None (no visible border) or a dict with
    {sz, val, color}. sz is in eighths of a point.
    """
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


def add_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def _set_cell_text(cell, text, *, bold=False, italic=False,
                   color=DARK_GRAY, size=9,
                   align=WD_ALIGN_PARAGRAPH.LEFT):
    cell.text = ''
    cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    para = cell.paragraphs[0]
    para.alignment = align
    run = para.add_run(text)
    set_run_style(run, bold=bold, italic=italic, color=color, size=size)


def _apply_plain_row_borders(cell, *, is_header=False, is_banner=False):
    """Horizontal-only borders matching the plain grey style."""
    color = ROW_BORDER
    _set_cell_borders(
        cell,
        top={'val': 'single', 'sz': 4, 'color': color}
            if is_header else None,
        bottom={'val': 'single', 'sz': 4, 'color': color},
        left=None, right=None,
    )


def add_usr_combined_table(doc, role_blocks, widths_cm):
    """Plain grey-header USR table with role banner rows."""
    n_cols = 5
    n_data_rows = sum(len(rows) for _, rows in role_blocks)
    n_rows = 1 + len(role_blocks) + n_data_rows

    table = doc.add_table(rows=n_rows, cols=n_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)

    header_labels = ['ID', 'As a...', 'I want to...', 'So that...',
                     'Measured by...']
    header_row = table.rows[0]
    for i, h in enumerate(header_labels):
        cell = header_row.cells[i]
        shade_cell(cell, HEADER_FILL)
        _set_cell_text(cell, h, bold=True, color=BLACK, size=10)
        _apply_plain_row_borders(cell, is_header=True)

    row_idx = 1
    for role_label, rows in role_blocks:
        banner_cells = table.rows[row_idx].cells
        merged = banner_cells[0]
        for c in banner_cells[1:]:
            merged = merged.merge(c)
        shade_cell(merged, HEADER_FILL)
        _set_cell_text(merged, role_label, bold=True,
                       color=BLACK, size=10)
        _apply_plain_row_borders(merged)
        row_idx += 1

        for row_values in rows:
            cells = table.rows[row_idx].cells
            for c_idx, value in enumerate(row_values):
                _set_cell_text(
                    cells[c_idx], str(value),
                    bold=(c_idx == 0),
                    color=BLACK,
                    size=8,
                )
                _apply_plain_row_borders(cells[c_idx])
            row_idx += 1


def add_table(doc, headers, rows, widths_cm, body_size=9):
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
                        bold=(c_idx == 0),
                        color=BLACK,
                        size=body_size,
                    )
            _apply_plain_row_borders(cell)


# -------------------------------------------------------------------------
# ELICITATION
# -------------------------------------------------------------------------

ELICITATION_ROWS = [
    ('1', 'Stakeholder Meetings',
     'Direct meetings with BBK as the client and NAIRDC as the '
     'project-management partner to understand compliance challenges, '
     'user workflows, and operational priorities.'),
    ('2', 'BBK Consultations',
     'Focused consultations with BBK on compliance practices, '
     'operational conventions, and audit expectations, shaping how '
     'the system organises its outputs.'),
    ('3', 'Document Analysis',
     'Review of the project brief, the bank\'s security posture, and '
     'the regulatory corpus of Bahrain, India, and Kuwait to extract '
     'methodological requirements.'),
    ('4', 'Research',
     'Research on retrieval-augmented generation, prompt-injection '
     'defence, and AI output verification to derive technical '
     'requirements not articulated by stakeholders.'),
    ('5', 'Technical Feasibility Study',
     'A short prototyping phase validating that the analytical '
     'pipeline could be implemented on the available hardware, '
     'informing performance targets and the swappable-LLM '
     'architecture.'),
    ('6', 'Requirements Prioritisation',
     'MoSCoW classification and Volere-style Data, Process, '
     'Communication tagging to ensure key features were addressed '
     'first.'),
]


# -------------------------------------------------------------------------
# USER-VOICE REQUIREMENTS
# -------------------------------------------------------------------------

USR_ANALYST = [
    ('USR-01', 'Compliance Analyst',
     'upload an internal BBK policy and receive a structured '
     'coverage analysis against the regulatory corpus of Bahrain, '
     'India, and Kuwait',
     'I can identify compliance gaps without manually reading every '
     'regulation',
     'Analysis completion within approximately 90 seconds for a '
     'typical policy document'),
    ('USR-02', 'Compliance Analyst',
     'see every finding in a generated report include a citation '
     'back to the exact regulatory clause it relies on',
     'I can verify the system\'s reasoning and present '
     'audit-defensible evidence',
     'Every finding carries a clause-level citation traceable to the '
     'source document'),
    ('USR-03', 'Compliance Analyst',
     'filter retrieval results by jurisdiction, regulator, and '
     'document type',
     'I can focus my analysis on the regulatory regime relevant to a '
     'specific compliance question',
     'Filter controls return matching results on a warm cache'),
    ('USR-04', 'Compliance Analyst',
     'run a comparison between two regulations on a chosen topic',
     'I can quickly see where the two regulations align, diverge, '
     'or conflict on that topic before opening a deeper mapping',
     'A side-by-side comparison view rendered for any two '
     'jurisdictions on the selected topic'),
]


USR_REVIEWER = [
    ('USR-05', 'Legal Reviewer',
     'see each AI-generated finding flagged with a confidence score '
     'and a list of supporting evidence chunks',
     'I can prioritise which findings require deeper human review',
     'Every finding carries a confidence value and at least one '
     'linked evidence chunk'),
    ('USR-06', 'Legal Reviewer',
     'approve, reject, or annotate AI-generated findings',
     'the system\'s outputs become an auditable record of '
     'human-validated compliance positions',
     'Reviewer actions persisted to the audit log within the same '
     'request'),
    ('USR-07', 'Legal Reviewer',
     'have findings where the AI flagged a potential hallucination '
     'or prompt-injection signal routed into a quarantine queue',
     'suspect content does not reach decision-makers without '
     'explicit review',
     'Flagged items are held until a reviewer dispositions them'),
    ('USR-08', 'Legal Reviewer',
     'export approved analyses in XLSX and PDF formats with a '
     'SHA-256 hash chain footer',
     'I can share audit-defensible reports with internal '
     'stakeholders and regulators',
     'Both export formats downloadable once the analysis status '
     'is APPROVED, each carrying a tamper-evident fingerprint'),
]


USR_ADMIN = [
    ('USR-09', 'Administrator',
     'view a system-health dashboard summarising LLM provider '
     'status, vector store size, lexical index health, active '
     'sessions, and recent reasoning failures',
     'I can spot operational issues before they impact analysts',
     'Dashboard refreshes on demand and reflects the last 24 hours '
     'of activity'),
    ('USR-10', 'Administrator',
     'assign and revoke user roles (Analyst, Reviewer, '
     'Administrator)',
     'access to sensitive analysis capabilities is bounded by the '
     'user\'s responsibility',
     'Every role change produces an audit-log entry identifying the '
     'actor, target, before-state, and after-state'),
    ('USR-11', 'Administrator',
     'swap the active LLM provider via configuration without '
     'redeploying the application',
     'the system can move between managed cloud and on-premises '
     'inference as procurement, cost, or data-sovereignty '
     'constraints change',
     'Change takes effect after a configuration reload with no code '
     'modification'),
    ('USR-12', 'Administrator',
     'review the audit log and filter entries by user, action, and '
     'date range',
     'I can investigate incidents and demonstrate regulatory '
     'compliance during audits',
     'Filtered queries return matching audit entries within a '
     'reasonable time'),
]


# -------------------------------------------------------------------------
# FUNCTIONAL REQUIREMENTS (20 total, split across 6 categories)
# -------------------------------------------------------------------------

FR_INGESTION = [
    ('FR1', 'BBK consultation',
     'The system shall ingest privacy regulations from Bahrain, '
     'India, and Kuwait.', '✔', '✔', '–', 'H', 'Closed'),
    ('FR2', 'Brief',
     'The system shall ingest BBK internal privacy policies, '
     'governance documents, and operational SOPs.',
     '✔', '✔', '–', 'H', 'Closed'),
    ('FR3', 'Research paper',
     'The system shall split ingested documents into searchable '
     'chunks that preserve section structure and metadata.',
     '✔', '✔', '–', 'H', 'Closed'),
]


FR_RETRIEVAL = [
    ('FR4', 'Research paper',
     'The system shall retrieve and rank chunks using combined '
     'semantic and keyword search with reciprocal rank fusion.',
     '✔', '✔', '–', 'H', 'Closed'),
    ('FR5', 'Research paper',
     'The system shall expand queries using equivalent legal '
     'terminology across the three supported jurisdictions.',
     '✔', '✔', '–', 'H', 'Closed'),
    ('FR6', 'Legal document analysis',
     'The system shall return citation-preserving results linked '
     'to their source documents.',
     '✔', '✔', '✔', 'H', 'Closed'),
]


FR_REASONING = [
    ('FR7', 'Meeting with BBK',
     'The system shall compare obligations between two regulations '
     'for a chosen compliance topic and classify equivalence.',
     '✔', '✔', '✔', 'H', 'Closed'),
    ('FR8', 'Meeting with BBK',
     'The system shall map an internal policy against one or more '
     'regulations and classify coverage as Fully Covered, Partially '
     'Covered, Requires Review, or Not Covered.',
     '✔', '✔', '✔', 'H', 'Closed'),
    ('FR9', 'Discussion',
     'The system shall detect compliance topics within uploaded '
     'policies and route mapping workflows to the relevant '
     'regulations.',
     '✔', '✔', '✔', 'H', 'Closed'),
    ('FR10', 'Meeting with BBK',
     'The system shall aggregate uncovered obligations from '
     'multiple jurisdictions into a unified gap analysis report '
     'with severity classification.',
     '✔', '✔', '✔', 'H', 'Closed'),
]


FR_WEB = [
    ('FR11', 'Meeting with BBK',
     'The system shall provide a compliance dashboard summarising '
     'overall coverage, gaps, and recent activity.',
     '✔', '–', '✔', 'H', 'Closed'),
    ('FR12', 'Meeting with BBK',
     'The system shall provide a library workspace for browsing '
     'regulations, internal policies, obligations, and the '
     'cross-jurisdiction terminology dictionary.',
     '✔', '✔', '✔', 'H', 'Closed'),
    ('FR13', 'Meeting with BBK',
     'The system shall provide comparison and mapping workspaces '
     'with reviewer queue, analyst override, and gap remediation '
     'capability.',
     '✔', '✔', '✔', 'H', 'Closed'),
    ('FR14', 'Meeting with BBK',
     'The system shall support export of analysis reports in '
     'XLSX and PDF formats with citation traceability.',
     '✔', '✔', '✔', 'H', 'Closed'),
]


FR_COPILOT = [
    ('FR15', 'Meeting with BBK',
     'The system shall provide a global AI Copilot that returns '
     'citation-backed answers grounded in retrieved corpus chunks.',
     '✔', '✔', '✔', 'H', 'Closed'),
    ('FR16', 'Research paper',
     'The system shall return a confidence score and a hallucination '
     'risk score alongside every Copilot answer.',
     '–', '✔', '✔', 'M', 'Closed'),
]


FR_SECURITY = [
    ('FR17', 'Existing system analysis',
     'The system shall require username, password, and time-based '
     'one-time password (TOTP) multi-factor authentication for '
     'every user account.',
     '✔', '✔', '✔', 'H', 'Closed'),
    ('FR18', 'BBK consultation',
     'The system shall enforce role-based access control with '
     'three roles (Compliance Analyst, Legal Reviewer, '
     'Administrator) and a per-row scope filter.',
     '✔', '✔', '–', 'H', 'Closed'),
    ('FR19', 'BBK consultation',
     'The system shall maintain an append-only audit log of every '
     'security-relevant action, capturing actor, role-at-time, '
     'IP address, target object, and metadata.',
     '✔', '✔', '–', 'H', 'Closed'),
    ('FR20', 'Research paper',
     'The system shall scan every ingested chunk for '
     'prompt-injection content and verify every AI-generated '
     'citation against the underlying retrieved chunks, rejecting '
     'or quarantining any failures.',
     '✔', '✔', '✔', 'H', 'Closed'),
]


# -------------------------------------------------------------------------
# NON-FUNCTIONAL REQUIREMENTS (20 total, split across 7 categories)
# -------------------------------------------------------------------------

NFR_PERFORMANCE = [
    ('NFR1', 'Technical feasibility study',
     'The system shall return retrieval results within an '
     'interactive response time on a warm cache.',
     '–', '✔', '✔', 'H', 'Closed'),
    ('NFR2', 'Technical feasibility study',
     'The system shall complete a single-topic policy mapping '
     'within approximately 90 seconds for a typical policy '
     'document.',
     '–', '✔', '✔', 'M', 'Closed'),
]


NFR_SCALABILITY = [
    ('NFR3', 'Existing system analysis',
     'The system shall support concurrent use by a typical '
     'compliance analyst team without performance degradation.',
     '✔', '✔', '–', 'M', 'Closed'),
    ('NFR4', 'Technical feasibility study',
     'The system shall support a growing regulatory and policy '
     'corpus without retrieval-time degradation, with no code '
     'changes required to add new documents.',
     '✔', '✔', '–', 'M', 'Closed'),
]


NFR_RELIABILITY = [
    ('NFR5', 'Research paper',
     'The system shall execute reasoning workflows as a bounded '
     'iterative correction process with retry limits.',
     '–', '✔', '–', 'H', 'Closed'),
    ('NFR6', 'Research paper',
     'The system shall produce a deterministic typed-empty '
     'fallback response when reasoning workflows cannot produce a '
     'verified answer.',
     '–', '✔', '✔', 'M', 'Closed'),
    ('NFR7', 'Existing system analysis',
     'The system shall support offline reasoning via local LLM '
     'inference, removing the dependency on external services for '
     'analytical content.',
     '–', '✔', '–', 'M', 'Closed'),
    ('NFR8', 'Research paper',
     'The system shall support idempotent re-ingestion of '
     'documents via content hashing, recovering from transient '
     'ingestion failures without data loss.',
     '✔', '✔', '–', 'M', 'Closed'),
]


NFR_MAINTAINABILITY = [
    ('NFR9', 'Technical feasibility study',
     'The system shall be organised into loosely coupled modules '
     'with clear interface boundaries (ingestion, retrieval, '
     'reasoning, web).',
     '–', '✔', '–', 'M', 'Closed'),
    ('NFR10', 'Existing system analysis',
     'The system shall provide an automated test suite covering '
     'authentication, access control, audit logging, retrieval '
     'quality, and reasoning workflows.',
     '✔', '✔', '–', 'H', 'Closed'),
    ('NFR11', 'Technical feasibility study',
     'The system shall support swappable LLM providers via '
     'configuration, including managed cloud and locally hosted '
     'options.',
     '–', '✔', '–', 'M', 'Closed'),
]


NFR_USABILITY = [
    ('NFR12', 'BBK consultation',
     'The system shall display live progress for any background '
     'operation expected to exceed five seconds.',
     '–', '✔', '✔', 'H', 'Closed'),
    ('NFR13', 'Existing system analysis',
     'The system shall warn users of impending idle-session '
     'timeout and allow them to extend the session without losing '
     'the current page state.',
     '–', '✔', '✔', 'M', 'Closed'),
    ('NFR14', 'Meeting with BBK',
     'The system shall provide audit-quality export of analysis '
     'reports in XLSX and PDF formats with tamper-evident '
     'hash chain.',
     '✔', '✔', '✔', 'H', 'Closed'),
]


NFR_SECURITY = [
    ('NFR15', 'Research paper',
     'The system shall enforce TLS 1.3 with HTTP Strict Transport '
     'Security (HSTS) preload at the perimeter in production.',
     '–', '✔', '✔', 'H', 'Closed'),
    ('NFR16', 'Research paper',
     'The system shall enforce a Content Security Policy with an '
     'explicit allowlist of script, style, font, image, and '
     'form-action sources.',
     '–', '✔', '✔', 'H', 'Closed'),
    ('NFR17', 'BBK consultation',
     'The system shall support geographic access control via an '
     'IP-based country allowlist with graceful failure when the '
     'lookup database is unavailable.',
     '✔', '✔', '–', 'M', 'Closed'),
]


NFR_OBSERVABILITY_AI = [
    ('NFR18', 'Technical feasibility study',
     'The system shall expose runtime configuration via '
     'environment variables for session timeout, MFA enforcement, '
     'retry limits, geo-fencing, and LLM provider selection.',
     '–', '✔', '–', 'M', 'Closed'),
    ('NFR19', 'Meeting with NAIRDC',
     'The system shall provide an administrator monitoring '
     'dashboard summarising LLM provider health, vector store '
     'statistics, lexical index statistics, active sessions, '
     'audit log volume, and recent reasoning failures.',
     '✔', '✔', '✔', 'M', 'Closed'),
    ('NFR20', 'Research paper',
     'The system shall evaluate whether AI-generated outputs are '
     'semantically supported by retrieved evidence using a '
     'Natural Language Inference grounding score.',
     '–', '✔', '–', 'M', 'Closed'),
]


# -------------------------------------------------------------------------
# CONSTRAINTS
# -------------------------------------------------------------------------

CONSTRAINTS = [
    ('CON-01', 'Hardware',
     'The system was developed on a device without an NVIDIA GPU; '
     'local LLM inference was too slow for interactive use.',
     'A managed cloud LLM (Claude Haiku 4.5) was used in '
     'development for speed; local Ollama was tested on NAIRDC\'s '
     'GPU-equipped device. Providers are swappable, so local can '
     'be the production default.'),
    ('CON-02', 'Data Access',
     'Direct access to BBK\'s internal policies, governance '
     'documents, and SOPs was not available.',
     'Twelve synthetic policy artefacts were authored to mirror '
     'typical bank compliance documents. The ingestion pipeline '
     'is corpus-agnostic; real BBK documents can be substituted '
     'without code changes.'),
    ('CON-03', 'Data Validation',
     'The regulatory document set was not validated by BBK\'s '
     'legal function.',
     'Approximately 43 documents across Bahrain, India, and '
     'Kuwait were assembled through independent research from '
     'publicly available sources. Documents can be added or '
     'replaced without code changes.'),
    ('CON-04', 'Data Quality',
     'Output quality is bounded by data quality: synthetic '
     'policies, varied regulatory document formatting, and a '
     'researcher-authored taxonomy and term dictionary.',
     'Outputs are analytical assistance subject to reviewer '
     'validation; every finding is citation-traceable to source.'),
    ('CON-05', 'Regulatory Regime',
     'The three jurisdictions are not equally mature in privacy '
     'regulation. Bahrain has a comprehensive PDPL with ten '
     'subordinate orders; India has the DPDP Act 2023 plus RBI '
     'circulars; Kuwait\'s regime is thinner and mostly sectoral.',
     'The comparison workflow uses asymmetric categories '
     '(equivalent, stronger, weaker, partial, absent), treating '
     'no analogue as a valid finding. Auto-routing dispatches '
     'comparisons only against regulations that cover the '
     'relevant topic.'),
    ('CON-06', 'Linguistic',
     'The regulatory corpus and analytical pipeline operate on '
     'English-language source material only. Several primary '
     'regulatory instruments are originally promulgated in '
     'Arabic, and authoritative English translations are not '
     'consistently available.',
     'Only English versions or published English translations of '
     'regulatory documents were ingested. The retrieval and '
     'reasoning layers are language-agnostic at the architectural '
     'level; multilingual embeddings can be introduced without '
     'changes to downstream workflows.'),
]


# -------------------------------------------------------------------------
# WRITERS
# -------------------------------------------------------------------------

def write_311(doc):
    add_heading(doc, '3.1.1 Requirements Elicitation', level=2)
    add_paragraph(
        doc,
        'Requirements for CJPCA were gathered and validated using six '
        'elicitation techniques involving BBK, NAIRDC, and legal and '
        'compliance analysts. Surveys, group workshops, and direct '
        'observation were considered but not used: the stakeholder '
        'population at BBK is small and access was mediated through '
        'NAIRDC, so direct meetings yielded richer insight per '
        'stakeholder than a survey or observation would have. A '
        'summary of the techniques applied is provided in the table below '
        'at the end of this subsection, with supporting details in '
        'Appendix 1.1.',
    )
    add_caption(doc, 'Table.',
                'Requirements elicitation approach.')
    add_table(
        doc,
        headers=['No.', 'Approach', 'Process'],
        rows=ELICITATION_ROWS,
        widths_cm=[1.2, 3.5, 11.3],
        body_size=9,
    )


def write_312(doc):
    add_heading(doc, '3.1.2 User-Voice Requirements', level=2)
    add_paragraph(
        doc,
        'User-voice requirements are grouped by the three '
        'operational roles. Each story names the user type, the '
        'action, the result, and a measurable success criterion. '
        'The three tables below present the stories by role.',
    )

    usr_sections = [
        ('Compliance Analyst', USR_ANALYST, 'Table.',
         'Compliance Analyst user-voice requirements.'),
        ('Legal Reviewer', USR_REVIEWER, 'Table.',
         'Legal Reviewer user-voice requirements.'),
        ('Administrator', USR_ADMIN, 'Table.',
         'Administrator user-voice requirements.'),
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
        )


def write_313(doc):
    add_heading(doc, '3.1.3 Functional Requirements', level=2)
    add_paragraph(
        doc,
        'This subsection presents twenty functional requirements that '
        'define the observable behaviour of the system, organised '
        'across six categories (Document Ingestion, Retrieval, '
        'Reasoning and Analysis, Web Application, Copilot Agent, '
        'Security and Access Control). Each requirement records its '
        'elicitation source, engagement with Data, Process, and '
        'Communication categories, a MoSCoW priority, and its current '
        'status. The expanded functional requirements catalogue '
        'appears in Appendix 1.5.',
    )

    fr_sections = [
        ('Document Ingestion', FR_INGESTION, 'Table.',
         'Document ingestion functional requirements.'),
        ('Retrieval', FR_RETRIEVAL, 'Table.',
         'Retrieval functional requirements.'),
        ('Reasoning and Analysis', FR_REASONING, 'Table.',
         'Reasoning and analysis functional requirements.'),
        ('Web Application', FR_WEB, 'Table.',
         'Web application functional requirements.'),
        ('Copilot Agent', FR_COPILOT, 'Table.',
         'Copilot agent functional requirements.'),
        ('Security and Access Control', FR_SECURITY, 'Table.',
         'Security and access control functional requirements.'),
    ]

    for heading_text, rows, caption_label, caption_text in fr_sections:
        add_heading(doc, heading_text, level=3)
        add_caption(doc, caption_label, caption_text)
        add_table(
            doc,
            headers=['ID', 'Source', 'Requirement', 'D', 'P', 'C',
                     'Pri', 'Status'],
            rows=rows,
            widths_cm=[1.2, 2.5, 7.3, 0.6, 0.6, 0.6, 0.8, 1.4],
            body_size=8,
        )


def write_314(doc):
    add_heading(doc, '3.1.4 Non-Functional Requirements', level=2)
    add_paragraph(
        doc,
        'This subsection presents twenty non-functional requirements '
        'that define the quality attributes of the system, organised '
        'across seven categories (Performance, Scalability, '
        'Reliability, Maintainability, Usability, Security, '
        'Observability and AI Governance). Each requirement records '
        'its elicitation source, the categories it engages, a MoSCoW '
        'priority, and its current status.',
    )

    nfr_sections = [
        ('Performance Efficiency', NFR_PERFORMANCE, 'Table.',
         'Performance efficiency non-functional requirements.'),
        ('Scalability', NFR_SCALABILITY, 'Table.',
         'Scalability non-functional requirements.'),
        ('Reliability and Availability', NFR_RELIABILITY, 'Table.',
         'Reliability and availability non-functional requirements.'),
        ('Maintainability', NFR_MAINTAINABILITY, 'Table.',
         'Maintainability non-functional requirements.'),
        ('Usability', NFR_USABILITY, 'Table.',
         'Usability non-functional requirements.'),
        ('Security', NFR_SECURITY, 'Table.',
         'Security non-functional requirements.'),
        ('Observability and AI Governance', NFR_OBSERVABILITY_AI,
         'Table.',
         'Observability and AI governance non-functional '
         'requirements.'),
    ]

    for heading_text, rows, caption_label, caption_text in nfr_sections:
        add_heading(doc, heading_text, level=3)
        add_caption(doc, caption_label, caption_text)
        add_table(
            doc,
            headers=['ID', 'Source', 'Requirement', 'D', 'P', 'C',
                     'Pri', 'Status'],
            rows=rows,
            widths_cm=[1.2, 2.5, 7.3, 0.6, 0.6, 0.6, 0.8, 1.4],
            body_size=8,
        )


def write_315(doc):
    add_heading(doc, '3.1.5 Constraints', level=2)
    add_paragraph(
        doc,
        'This subsection presents the six constraints that shaped '
        'the functionality and development of the system, organised '
        'across hardware, data access, data validation, data '
        'quality, regulatory regime, and linguistic categories. '
        'Each constraint records its type, the constraint itself, '
        'and the mitigation strategy applied. The table below '
        'lists them in full.',
    )
    add_caption(doc, 'Table.', 'Project constraints.')
    add_table(
        doc,
        headers=['ID', 'Type', 'Constraint', 'Impact / Mitigation'],
        rows=CONSTRAINTS,
        widths_cm=[1.4, 2.4, 5.6, 6.6],
        body_size=8,
    )


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '3_1_requirements.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'3_1_requirements_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, '3.1 Requirements', level=1)
    add_paragraph(
        doc,
        'This section describes the requirements gathered for CJPCA. '
        'It covers the elicitation methodology, user-voice '
        'requirements grouped by operational role, twenty functional '
        'requirements split across six categories, twenty '
        'non-functional requirements split across seven quality '
        'categories, and the six development constraints that '
        'shaped scope. Supporting evidence (meeting records, '
        'research findings, document analysis, and the technical '
        'feasibility study) appears in Appendix 1.',
    )

    write_311(doc)
    write_312(doc)
    write_313(doc)
    write_314(doc)
    write_315(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
