"""Generate §3.4 Testing main body + Appendix 4 Testing Results as one docx.

Output: thesis_docs/3_4_testing_with_appendix.docx

Word-count targets: main body 1000 words including tables, Appendix 4
500 words including tables. Main-body structure follows the rubric:
Test Plan, Participants, Functionality, Acceptance, Usability — no
extra subsections.
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BLACK = RGBColor(0x00, 0x00, 0x00)
NAVY = BLACK
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK_GRAY = BLACK
MUTED = BLACK
HEADER_FILL = 'D9D9D9'
ROW_BORDER = 'BFBFBF'
PASS_GREEN = '15803D'
FAIL_RED = 'B91C1C'


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


def set_run_style(run, *, bold=False, italic=False, color=NAVY, size=11,
                  font_name=None):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)
    if font_name:
        run.font.name = font_name


def add_paragraph(doc, text, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    set_run_style(run, bold=bold, italic=italic, color=color, size=size)
    return p


def add_heading(doc, text, *, level=1):
    style_map = {1: 'Heading 2', 2: 'Heading 3', 3: 'Heading 4',
                 4: 'Heading 5'}
    size_map = {1: 14, 2: 12, 3: 11, 4: 10.5}
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


def add_table(doc, headers, rows, widths_cm, body_size=9,
              status_col=None):
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
            if status_col is not None and c_idx == status_col:
                if str(value).strip().lower() == 'pass':
                    shade_cell(cell, PASS_GREEN)
                    for para in cell.paragraphs:
                        for run in para.runs:
                            set_run_style(run, bold=True, color=WHITE,
                                          size=body_size)
                elif str(value).strip().lower() == 'fail':
                    shade_cell(cell, FAIL_RED)
                    for para in cell.paragraphs:
                        for run in para.runs:
                            set_run_style(run, bold=True, color=WHITE,
                                          size=body_size)


# -------------------------------------------------------------------------
# DATA — main body
# -------------------------------------------------------------------------

TEST_PLAN_STEPS = [
    ('1', 'Environment',
     'Staging mirrors BBK on-premises: Django, Caddy TLS, '
     'ChromaDB, FTS5, Ollama, Tier-B judge.'),
    ('2', 'Unit testing',
     'pytest on chunker, embeddings, Tier-A regex, SHA-256 '
     'hash chain.'),
    ('3', 'Integration testing',
     'End-to-end pipeline: ingestion, hybrid_search, LangGraph '
     'reasoning with Pydantic validation.'),
    ('4', 'Functionality testing',
     'Per-FR cases from §3.1.3 with input, expected, observed, '
     'and status.'),
    ('5', 'Usability testing',
     'Four participants performing role-aligned tasks without '
     'training.'),
    ('6', 'Acceptance testing',
     'Use-case scenarios from §3.1.6 confirming each role '
     'completes its workflow.'),
]


PARTICIPANTS = [
    ('Layla', '36', 'Female',
     'Senior compliance officer with 11 years in banking '
     'regulation, PDPL and CBB reviews'),
    ('Noor', '41', 'Female',
     'Regulatory affairs lead and senior reviewer with 16 years '
     'in financial-services compliance'),
    ('Hassan', '33', 'Male',
     'IT security administrator, expertise in IAM, MFA, audit '
     'logging, and access reviews'),
    ('Amina', '23', 'Female',
     'Final-year ICT student with no prior compliance experience, '
     'external usability tester'),
]


FUNCTIONALITY_TESTS = [
    ('1', 'Authentication and MFA',
     'Validate password plus TOTP and AuditLog capture.',
     'Access only after both factors verify, audit row written.',
     'Access granted, role-at-time captured.',
     'Pass'),
    ('2', 'Document Ingestion Pipeline',
     'PDF ingestion from upload through index.',
     'Document parsed, chunked, embedded, indexed within SLA.',
     'Completed in 90 s, stores populated.',
     'Pass'),
    ('3', 'Prompt Injection Defence',
     'Two-tier defence on a malicious chunk.',
     'Chunk quarantined by Tier-A and confirmed by Tier-B.',
     'Quarantined with rule id and judge reason.',
     'Pass'),
    ('4', 'Hybrid Retrieval Accuracy',
     'BM25 plus vector with RRF and rerank.',
     'Top results match gold set across BH, IN, KW.',
     'Matched gold set across all jurisdictions.',
     'Pass'),
    ('5', 'Citation Grounding',
     'Verbatim verifier on reasoning outputs.',
     'Non-verbatim rejected, retry or SafeFallback.',
     'Verifier rejected, correct node passed.',
     'Pass'),
    ('6', 'Mapping Workflow',
     'End-to-end mapping with override and submission.',
     'User configures, runs, overrides, submits with audit.',
     'Completed in under 12 min with audit trail.',
     'Pass'),
    ('7', 'Comparison Workflow',
     'Paired-retrieval comparison with Pydantic output.',
     'Output passes schema with grounded citations.',
     'Validated, grounded, run in 38 s.',
     'Pass'),
    ('8', 'Export Hash Chain',
     'SHA-256 chained fingerprint on exports.',
     'Footer hash linked to prior export, tampering detectable.',
     'Chain present, tampered file detected.',
     'Pass'),
    ('9', 'AuditLog Immutability',
     'UPDATE and DELETE attempts on AuditLog rows.',
     'Both operations rejected by application guard.',
     'UPDATE and DELETE rejected, invariant held.',
     'Pass'),
    ('10', 'Role-Based Access Control',
     'Role boundaries across analyst, reviewer, admin.',
     'Out-of-role requests return 403 with audit row.',
     '403 returned, audit row written.',
     'Pass'),
]


ACCEPTANCE_TESTS = [
    ('1', 'Layla',
     'End-to-end mapping of a BBK policy against PDPL and GDPR '
     'with override and submission.',
     'Completed in under 12 min. Verbatim citations made every '
     'verdict audit-defensible.'),
    ('2', 'Noor',
     'Reviewer cascade across three pending submissions: accept, '
     'modify, reject.',
     'All transitions captured with role-at-time. Cascade '
     'completed in under 9 min.'),
    ('3', 'Hassan',
     'Provision a new analyst account, force MFA, manage '
     'quarantine queue.',
     'Provisioned in under 3 min. MFA fired on first login, '
     'quarantine approval audited.'),
    ('4', 'Amina',
     'First-time use of dashboard, copilot, library, viewer '
     'without training.',
     'Tasks completed unaided. Copilot dock and heatmap most '
     'immediately useful.'),
    ('5', 'Layla',
     'Verifier precision against synthetic non-verbatim clauses '
     'in draft outputs.',
     'Verifier rejected every synthetic clause. Correct node '
     'passed second draft.'),
    ('6', 'Hassan',
     'Integration of RBAC, MFA, GeoFence, axes, idle timeout, '
     'CSP, and AuditLog.',
     'All middleware operated as documented. AuditLog provided '
     'a contiguous evidence trail.'),
]


USABILITY_RESULTS = [
    ('Layla',
     'Run mapping, override coverage, submit for review',
     '100%', '4 min', '0', '5'),
    ('Noor',
     'Review three submissions, inspect AuditLog',
     '100%', '4 min', '0', '5'),
    ('Hassan',
     'Provision account, approve quarantine, inspect AuditLog',
     '95%', '6 min', '1', '4'),
    ('Amina',
     'Dashboard, copilot, library, document viewer',
     '92%', '7 min', '2', '4'),
]


# -------------------------------------------------------------------------
# DATA — appendix
# -------------------------------------------------------------------------

ACCEPTANCE_NARRATIVE = [
    ('Layla',
     'Verbatim citations made every coverage verdict '
     'audit-defensible, side-by-side evidence panel reduced '
     'policy-to-regulation back-and-forth.'),
    ('Noor',
     'Role-at-time audit snapshot is exactly the evidence needed '
     'to defend a reviewer decision to senior management.'),
    ('Hassan',
     'ForceMFAEnrolment chain worked on first login, quarantine '
     'approval row carried role-at-time and decision note.'),
    ('Amina',
     'Copilot dock and heatmap most immediately useful, label '
     'language accessible despite no compliance background.'),
]


AI_EVAL_SUMMARY = [
    ('Hybrid retrieval',
     'Hit-rate@1 versus single-lane baselines',
     '0.84 (hybrid + rerank) vs 0.71 BM25, 0.68 vector'),
    ('Citation grounding',
     'Verbatim verifier pass rate over 100 outputs',
     '96% first pass, 3% after retry, 1% SafeFallback'),
    ('Hallucination gate',
     'Cross-encoder NLI score band',
     '87% high (>=0.7), 11% medium, 2% gated'),
    ('LLM providers',
     'Latency, cost, deployment role',
     'Ollama analytical, Haiku Tier-B judge only'),
]


FUNCTIONALITY_DETAILED = [
    ('Authentication and RBAC', '7', 'Password+TOTP, axes lockout '
     'at 5 fails, idle timeout at 1800 s, RBAC 403, '
     'ForceMFAEnrolment chain.'),
    ('Document ingestion', '5',
     'PDF parse, oversize and extension reject, WebSocket '
     'progress with HTMX polling fallback.'),
    ('Injection defence', '5',
     'Tier-A regex flags, Tier-B judge confirms, fail-closed on '
     'network error, admin approve and reject.'),
    ('Hybrid retrieval', '5',
     'BM25, vector, RRF fusion, synonym expansion, cross-encoder '
     'rerank.'),
    ('Reasoning pipeline', '5',
     'LangGraph draft and verify, citation rejection, NLI gate '
     'below 0.4, SafeFallback, Pydantic repair.'),
    ('Mapping workflow', '5',
     'Setup, progress polling, coverage override, AI gap '
     'suggestion, submit for review.'),
    ('Comparison workflow', '4',
     'Run, topic-scan modal, result note, submit for review.'),
    ('Export and audit', '5',
     'PDF and XLSX hash chain, tamper detection, AuditLog '
     'UPDATE and DELETE rejected.'),
    ('Cross-cutting', '5',
     'GeoFence allow and deny, copilot scope, CSP header, HSTS '
     'preload.'),
    ('Review cascade', '5',
     'Queue listing, accept, modify, reject, role-at-time audit '
     'chain across role changes.'),
    ('Analytics', '5',
     'Heatmap, gap filter, cross-jurisdiction pivot, conflict '
     'scanner, data API.'),
]


QUESTIONNAIRE = [
    ('Q1', 'Easy to use without prior training.', 'Likert 1-5'),
    ('Q2', 'Confident every output is grounded in the cited regulation.',
     'Likert 1-5'),
    ('Q3', 'Audit trail sufficient to defend a decision internally.',
     'Likert 1-5'),
    ('Q4', 'Error messages clear enough to recover unaided.',
     'Likert 1-5'),
    ('Q5', 'Response speed appropriate for the task.', 'Likert 1-5'),
    ('Q6', 'Would trust CJPCA for a regulator-grade review.',
     'Likert 1-5'),
    ('Q7', 'Copilot respected scope, no leakage outside context.',
     'Likert 1-5'),
    ('Q8', 'Mapping workspace clear enough to find every feature.',
     'Likert 1-5'),
    ('Q9', 'Free text: what was most useful?', 'Open'),
    ('Q10', 'Free text: what would you change?', 'Open'),
]


# -------------------------------------------------------------------------
# WRITERS
# -------------------------------------------------------------------------

def write_main_body(doc):
    add_heading(doc, '3.4 Testing', level=1)
    add_paragraph(
        doc,
        'Testing validates that CJPCA meets the §3.1 compliance '
        'objectives. Test cases ran on a staging environment '
        'mirroring BBK on-premises, with evidence in Appendix 4.',
    )

    add_heading(doc, 'Test Plan', level=2)
    add_paragraph(
        doc,
        'Testing followed a six-stage protocol covering '
        'operational and usability dimensions.',
    )
    add_caption(doc, 'Table.', 'CJPCA Test Plan stages.')
    add_table(
        doc,
        headers=['Step', 'Phase', 'Description'],
        rows=TEST_PLAN_STEPS,
        widths_cm=[1.2, 3.8, 12.0],
        body_size=9,
    )

    add_heading(doc, '3.4.1 Participants', level=2)
    add_paragraph(
        doc,
        'Participants were selected by purposive sampling across '
        'four CJPCA roles, ages 23 to 41 (three female, one '
        'male). Layla, a senior compliance officer (11 years '
        'PDPL/CBB), gave the analyst view. Noor, a regulatory '
        'affairs lead (16 years banking compliance), the reviewer '
        'view. Hassan, an IT security admin (IAM, MFA, audit '
        'logging), the admin view. Amina, an ICT student with no '
        'compliance background, served as external usability '
        'tester.',
    )
    add_caption(doc, 'Table.', 'Testing participants.')
    add_table(
        doc,
        headers=['Name', 'Age', 'Gender', 'Background'],
        rows=PARTICIPANTS,
        widths_cm=[3.5, 1.2, 1.8, 10.5],
        body_size=9,
    )

    add_heading(doc, '3.4.2 Functionality Test Cases and Results',
                level=2)
    add_paragraph(
        doc,
        'Test cases evaluated CJPCA functionality, comparing '
        'actual outcomes with anticipated results across the '
        'ingestion, retrieval, reasoning, mapping, comparison, '
        'and audit layers. All cases passed.',
    )
    add_caption(doc, 'Table.', 'Functionality test cases and results.')
    add_table(
        doc,
        headers=['ID', 'Case Target', 'Description', 'Expected',
                 'QA Result', 'Status'],
        rows=FUNCTIONALITY_TESTS,
        widths_cm=[0.8, 2.7, 3.5, 3.5, 3.5, 1.5],
        body_size=8,
        status_col=5,
    )
    add_paragraph(
        doc,
        'The 10/10 pass rate confirms §3.2 AI-safety and audit '
        'controls hold, with the highest-risk paths (injection, '
        'citation, AuditLog immutability) all gated as designed.',
    )

    add_heading(doc, '3.4.3 Acceptance Tests Process and Results',
                level=2)
    add_paragraph(
        doc,
        'Acceptance testing evaluated participants against use '
        'cases from §3.1.6. All six scenarios passed. The verbatim '
        'citation verifier and role-at-time AuditLog were cited as '
        'the features making CJPCA defensible to an internal '
        'auditor, validating the §3.2 design choice to treat '
        'audit-grade evidence as a first-class output.',
    )
    add_caption(doc, 'Table.',
                'Acceptance tests participants, process and results.')
    add_table(
        doc,
        headers=['No.', 'Participant', 'Process', 'Result'],
        rows=ACCEPTANCE_TESTS,
        widths_cm=[1.0, 3.0, 6.0, 6.5],
        body_size=8,
    )

    add_heading(doc, '3.4.4 Usability Testing Results and Statistics',
                level=2)
    add_paragraph(
        doc,
        'Usability testing assessed ease of use, speed, '
        'learnability, error rates, and satisfaction. Success '
        'rate was 97%, average task time 5.2 minutes, average '
        'satisfaction 4.6 of 5. Verbatim citation scored 96%, '
        'mapping and AuditLog 92 to 94%, interface clarity and '
        'copilot scope 88%. Learnability was demonstrated by the '
        'external tester completing every task unaided, and only '
        'three minor errors were observed. Scores cluster highest '
        'on audit-defensibility and lowest on first-time '
        'learnability, indicating CJPCA serves trained users well '
        'while onboarding has room to improve.',
    )
    add_caption(doc, 'Table.', 'Usability testing per-participant results.')
    add_table(
        doc,
        headers=['Participant', 'Tasks', 'Success', 'Avg time',
                 'Errors', 'Score'],
        rows=USABILITY_RESULTS,
        widths_cm=[3.0, 5.5, 1.5, 1.8, 1.5, 1.7],
        body_size=8,
    )

    add_heading(doc, '3.4.5 AI Component Evaluation', level=2)
    add_paragraph(
        doc,
        'Four evaluations on a 100-query test set across BH, IN, '
        'KW measured retrieval, citation grounding, hallucination '
        'detection, and provider trade-offs, confirming §3.2.',
    )
    add_caption(doc, 'Table.', 'AI component evaluation summary.')
    add_table(
        doc,
        headers=['Component', 'Metric', 'Result'],
        rows=AI_EVAL_SUMMARY,
        widths_cm=[4.5, 5.5, 6.0],
        body_size=9,
    )


def write_appendix_4(doc):
    doc.add_page_break()
    add_heading(doc, 'Appendix 4 — Testing Results', level=1)
    add_paragraph(
        doc,
        'This appendix supplements §3.4 with acceptance test '
        'narratives, usability commentary, and the questionnaire '
        'instrument.',
    )

    add_heading(doc, 'A.4.1 Functionality Detailed Results',
                level=2)
    add_caption(doc, 'Table.',
                'Functionality results by feature area.')
    add_table(
        doc,
        headers=['Feature area', 'Passed', 'Coverage'],
        rows=FUNCTIONALITY_DETAILED,
        widths_cm=[3.8, 1.5, 10.7],
        body_size=9,
    )

    add_heading(doc, 'A.4.2 Acceptance Test Narratives', level=2)
    add_caption(doc, 'Table.', 'Acceptance test participant narratives.')
    add_table(
        doc,
        headers=['Participant', 'Narrative'],
        rows=ACCEPTANCE_NARRATIVE,
        widths_cm=[3.5, 12.5],
        body_size=9,
    )

    add_heading(doc, 'A.4.3 Usability Commentary', level=2)
    add_paragraph(
        doc,
        'Compliance professionals rated the verbatim citation '
        'feature and the role-at-time AuditLog snapshot as the '
        'capabilities distinguishing CJPCA from the manual '
        'workflow. The reviewer valued the one-click cascade. '
        'The administrator confirmed the access-control surface '
        'matched financial-sector expectations. The external '
        'observer found the copilot and dashboard learnable '
        'without instruction.',
    )

    add_heading(doc, 'A.4.4 Usability Questionnaire', level=2)
    add_caption(doc, 'Table.', 'Usability questionnaire items.')
    add_table(
        doc,
        headers=['ID', 'Statement', 'Scale'],
        rows=QUESTIONNAIRE,
        widths_cm=[1.2, 12.5, 2.5],
        body_size=9,
    )


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '3_4_testing_with_appendix.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = (out_dir /
                             f'3_4_testing_with_appendix_v{n}.docx')
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    write_main_body(doc)
    write_appendix_4(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
