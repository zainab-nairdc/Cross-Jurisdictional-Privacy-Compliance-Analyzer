"""Generate Appendix 2 (Solution Design Supplement) as a standalone docx
with plain black text and Word's "Plain Table 1" table style.

Output: thesis_docs/appendix_2_solution_design.docx

Reuses the data constants from generate_3_2_solution_design.py so the
content stays in sync, but rewrites the styling helpers to produce
plain black text and Word "Plain Table 1" tables to match the main
body screenshot the user is working from.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BLACK = RGBColor(0x00, 0x00, 0x00)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HEADER_FILL = 'D9D9D9'        # light grey header (Plain Table 1 look)
ROW_BORDER = 'BFBFBF'         # subtle grey between body rows
PLAIN_TABLE_STYLE = 'Plain Table 1'


def _load_main_generator():
    """Import the main §3.2 generator so we reuse its data constants."""
    here = Path(__file__).resolve().parent
    path = here / 'generate_3_2_solution_design.py'
    spec = importlib.util.spec_from_file_location('mg32', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['mg32'] = module
    spec.loader.exec_module(module)
    return module


MG = _load_main_generator()


# -------------------------------------------------------------------------
# Plain styling helpers
# -------------------------------------------------------------------------

def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def set_run(run, *, bold=False, italic=False, size=11, color=BLACK):
    run.font.bold = bold
    run.font.italic = italic
    run.font.size = Pt(size)
    run.font.color.rgb = color


def add_heading(doc, text, *, level=1):
    style_map = {1: 'Heading 1', 2: 'Heading 2', 3: 'Heading 3',
                 4: 'Heading 4'}
    size_map = {1: 16, 2: 14, 3: 12, 4: 11}
    h = doc.add_paragraph(style=style_map[level])
    run = h.add_run(text)
    run.font.color.rgb = BLACK
    run.font.bold = True
    run.font.size = Pt(size_map[level])
    return h


def add_paragraph(doc, text, *, bold=False, italic=False, size=11,
                  align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=8):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    set_run(run, bold=bold, italic=italic, size=size, color=BLACK)
    return p


def add_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    r1 = p.add_run(label + ' ')
    set_run(r1, bold=True, size=10, color=BLACK)
    r2 = p.add_run(caption)
    set_run(r2, italic=True, size=10, color=BLACK)


def add_figure_placeholder(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(f'[INSERT FIGURE: {label}]')
    set_run(run, bold=True, italic=True, size=10, color=BLACK)
    add_caption(doc, label + '.', caption)


def _set_cell_borders(cell, top=None, bottom=None, left=None,
                       right=None):
    """Apply per-side borders to a table cell.

    Each argument is either None (no change) or a dict with
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


def add_table(doc, headers, rows, widths_cm, body_size=10,
              bold_first=True):
    """Dark navy header, horizontal-only row borders, no vertical
    grid lines.  Matches the screenshot styling."""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    # No built-in style — borders applied manually below
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)

    n_rows = len(rows) + 1
    last_idx = n_rows - 1

    # Header row
    header_row = table.rows[0]
    for i, h in enumerate(headers):
        cell = header_row.cells[i]
        cell.text = h
        shade_cell(cell, HEADER_FILL)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        para.paragraph_format.space_before = Pt(2)
        para.paragraph_format.space_after = Pt(2)
        for run in para.runs:
            set_run(run, bold=True, size=body_size, color=BLACK)
        # Thin grey rule under the header; no verticals
        _set_cell_borders(
            cell,
            top={'val': 'single', 'sz': 4, 'color': ROW_BORDER},
            bottom={'val': 'single', 'sz': 4, 'color': ROW_BORDER},
            left=None, right=None,
        )

    # Body rows
    for r_idx, row_values in enumerate(rows, start=1):
        row = table.rows[r_idx]
        for c_idx, value in enumerate(row_values):
            cell = row.cells[c_idx]
            cell.text = str(value)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            for para in cell.paragraphs:
                para.paragraph_format.space_before = Pt(2)
                para.paragraph_format.space_after = Pt(2)
                for run in para.runs:
                    set_run(
                        run,
                        bold=(bold_first and c_idx == 0),
                        size=body_size,
                        color=BLACK,
                    )
            is_last = (r_idx == last_idx)
            _set_cell_borders(
                cell,
                top=None,
                bottom={
                    'val': 'single',
                    'sz': 4,
                    'color': ROW_BORDER,
                },
                left=None, right=None,
            )


# -------------------------------------------------------------------------
# Section writers — content reused from MG, restyled
# -------------------------------------------------------------------------

def write_intro(doc):
    add_heading(doc, 'Appendix 2: Solution Design Supplement',
                level=1)
    add_paragraph(
        doc,
        'This appendix contains the detailed design artefacts '
        'that support §3.2: the requirements traceability '
        'matrix, the key data structures in detail, per-phase '
        'sequence and activity diagrams, lifecycle state '
        'machines, the algorithm reference with pseudocode for '
        'auxiliary and integration algorithms, and the '
        'algorithm constants and lookup tables. The '
        'cybersecurity supplement covers the risk register, '
        'the security policies, the logs and detection worked '
        'examples, the login and multi-factor authentication '
        'flow, the security architecture implementation detail, '
        'the secure development practices, the prompt injection '
        'defence flow, the GeoFence middleware flow, and the '
        'audit and hash chain flow.',
    )


def write_a21_traceability(doc):
    add_heading(doc, 'A2.1 Requirements Traceability Matrix', level=2)
    add_paragraph(
        doc,
        'The matrix below maps every requirement from §3.1 to '
        'its design element in §3.2. Three tables cover '
        'functional requirements, non-functional requirements, '
        'and constraints.',
    )
    add_caption(doc, 'Table.',
                'Functional requirement traceability.')
    add_table(
        doc,
        headers=['FR ID', 'Requirement (short)',
                 'Design element(s) covering it'],
        rows=MG.TRACE_FR,
        widths_cm=[1.6, 5.4, 9.0],
        body_size=9,
    )
    add_caption(doc, 'Table.',
                'Non-functional requirement traceability.')
    add_table(
        doc,
        headers=['NFR ID', 'Requirement (short)',
                 'Design element(s) covering it'],
        rows=MG.TRACE_NFR,
        widths_cm=[1.6, 5.4, 9.0],
        body_size=9,
    )
    add_caption(doc, 'Table.', 'Constraint traceability.')
    add_table(
        doc,
        headers=['CON ID', 'Constraint (short)',
                 'Design element(s) covering it'],
        rows=MG.TRACE_CONSTRAINTS,
        widths_cm=[1.6, 5.4, 9.0],
        body_size=9,
    )


def write_a22_key_data_structures(doc):
    add_heading(doc, 'A2.2 Key data structures in detail',
                level=2)
    add_paragraph(
        doc,
        'Three structures on the core path deserve a closer '
        'look beyond the rationale given in the main body.',
    )
    add_paragraph(doc, 'LangGraph reasoning state.', bold=True,
                  space_after=2)
    add_paragraph(
        doc,
        'A small TypedDict that moves through the three '
        'reasoning steps (draft, verify, correct) and carries '
        'four fields: the query, the retrieved chunks, a '
        'reasoning trace, and a retry counter. The counter is '
        'capped at max_retries = 2; once the budget is '
        'exhausted, the state machine returns the deterministic '
        'SafeFallback answer rather than looping indefinitely.',
    )
    add_paragraph(doc, 'Reciprocal Rank Fusion (RRF).', bold=True,
                  space_after=2)
    add_paragraph(
        doc,
        'Two parallel searches run over the corpus: BM25 over '
        'SQLite FTS5 (keyword) and HNSW over ChromaDB '
        '(semantic). Each returns its own ranked list. RRF '
        'merges them with score(c) = sum over lists of '
        '1 / (60 + rank(c)). The constant k = 60 is the '
        'published RRF default and removes the need to calibrate '
        'between two different score scales.',
    )
    add_paragraph(doc, 'Audit-hash chain.', bold=True, space_after=2)
    add_paragraph(
        doc,
        'Each PDF and XLSX export carries a 16-character '
        'SHA-256 prefix computed over an identity tuple bound '
        'to the prior export. The tuple is the class name, '
        'primary key, status, completed_at, submitted_at, and '
        'created_by id. The hash is stamped into the export '
        'footer and recorded in the AuditLog, achieving '
        'audit-defensibility without the operational cost of a '
        'full digital-signature system.',
    )


def write_a23(doc):
    add_heading(doc, 'A2.3 Per-phase mechanics', level=2)
    add_paragraph(
        doc,
        'The figures below expand each phase introduced in '
        '§3.2.2. Sequence diagrams trace one user journey from '
        'start to end; activity diagrams trace the internal '
        'steps of one phase.',
    )
    for _label, caption in MG.A23_FIGURES:
        add_figure_placeholder(doc, 'Figure', '')
        add_paragraph(doc, caption, italic=True, size=10,
                      space_after=10)


def write_a25(doc):
    add_heading(doc, 'A2.5 Lifecycle states', level=2)
    add_paragraph(
        doc,
        'The state machines below show the lifecycle of the '
        'three workflow records the system tracks. Every '
        'transition is a controlled action.',
    )
    for _label, caption in MG.A25_FIGURES:
        add_figure_placeholder(doc, 'Figure', '')
        add_paragraph(doc, caption, italic=True, size=10,
                      space_after=10)


def write_a27(doc):
    add_heading(doc, 'A2.7 Algorithm reference', level=2)
    add_paragraph(
        doc,
        'This appendix expands the algorithms named but not '
        'boxed in §3.2.3. Section A2.7.1 covers auxiliary '
        'procedures inside the AI pipeline. Section A2.7.2 '
        'covers the three Django integration algorithms.',
    )
    add_heading(doc, 'A2.7.1 Auxiliary algorithms', level=3)
    add_paragraph(
        doc,
        'Nine procedures expanded here as numbered pseudocode '
        'figures. Weights, thresholds, and lookup tables are in '
        'Appendix A2.8.',
    )
    aux = [
        'StrictnessScore.', 'DivergenceRanking.', 'RiskScore.',
        'QueryRouter.', 'TermDictionaryExpand.', 'AutoRouteScope.',
        'ChunkClassify.', 'SafeFallback.', 'InvokeLocalLLM.',
    ]
    for caption in aux:
        add_figure_placeholder(doc, 'Algorithm', caption)

    add_heading(doc, 'A2.7.2 Django integration algorithms', level=3)
    add_paragraph(
        doc,
        'Three patterns that glue the AI pipeline to the Django '
        'web layer.',
    )
    integ = ['SyncGapOnApproval.', 'LaunchSubprocess.',
             'CascadeApproval.']
    for caption in integ:
        add_figure_placeholder(doc, 'Algorithm', caption)


def write_a28(doc):
    add_heading(doc, 'A2.8 Algorithm constants and lookup tables',
                level=2)
    add_paragraph(
        doc,
        'Lookup tables, weights, and configuration constants '
        'that the algorithms in §3.2.3 and Appendix A2.7 read '
        'from.',
    )
    add_heading(doc, 'A.8.1 chunk_tags taxonomy', level=3)
    add_caption(doc, 'Table.',
                'chunk_tags taxonomy used by ChunkClassify and '
                'AutoRouteScope.')
    add_table(
        doc,
        headers=['Topic tag', 'Label', 'Subcategories'],
        rows=MG.TAXONOMY_ROWS,
        widths_cm=[3.0, 5.0, 8.0],
        body_size=9,
    )
    add_heading(doc, 'A.8.2 Per-jurisdiction risk weights', level=3)
    add_caption(doc, 'Table.',
                'Penalty and enforcement weights per jurisdiction '
                '(used by RiskScore).')
    add_table(
        doc,
        headers=['Jurisdiction', 'Penalty weight',
                 'Enforcement weight', 'Rationale'],
        rows=MG.RISK_WEIGHTS,
        widths_cm=[4.0, 2.4, 2.6, 7.0],
        body_size=9,
    )
    add_heading(doc, 'A.8.3 Per-topic impact weights', level=3)
    add_caption(doc, 'Table.',
                'Impact weight per topic (used by RiskScore).')
    add_table(
        doc,
        headers=['Topic', 'Impact weight'],
        rows=MG.IMPACT_WEIGHTS,
        widths_cm=[5.0, 3.0],
        body_size=9,
    )
    add_heading(doc, 'A.8.4 Coverage factor by status', level=3)
    add_caption(doc, 'Table.',
                'Coverage factor per ObligationMapping status '
                '(RiskScore multiplier).')
    add_table(
        doc,
        headers=['Coverage status', 'Factor', 'Meaning'],
        rows=MG.COVERAGE_FACTOR,
        widths_cm=[3.5, 1.8, 9.7],
        body_size=9,
    )
    add_heading(doc, 'A.8.5 Severity-to-due-date buckets', level=3)
    add_caption(doc, 'Table.',
                'Severity bucket to default due-date offset.')
    add_table(
        doc,
        headers=['Severity bucket', 'Default due offset',
                 'Trigger condition'],
        rows=MG.SEVERITY_BUCKETS,
        widths_cm=[3.0, 3.0, 9.0],
        body_size=9,
    )


def write_a29_risk_assessment(doc):
    add_heading(doc, 'A2.9 Risk Assessment', level=2)
    add_paragraph(
        doc,
        'The risk register below catalogues every threat '
        'surfaced by the data flow diagram in §3.2.6. Each row '
        'names the asset, STRIDE category, threat scenario, '
        'inherent severity, mitigating control, and residual '
        'severity.',
    )
    add_caption(doc, 'Table.',
                'CJPCA risk register, scored before and after '
                'controls.')
    add_table(
        doc,
        headers=['ID', 'Asset', 'STRIDE', 'Threat scenario',
                 'L', 'I', 'Inherent', 'Mitigating control (Tier)',
                 'Residual'],
        rows=MG.RISK_ROWS,
        widths_cm=[0.9, 2.0, 1.2, 3.5, 0.5, 0.5, 1.5, 5.4, 1.5],
        body_size=8,
    )
    add_paragraph(
        doc,
        'After controls, 17 of 20 risks reduce to LOW, three '
        'remain at MEDIUM, and zero remain HIGH or CRITICAL. '
        'The three residual MEDIUM risks are R07 prompt '
        'injection, R08 LLM hallucination, and the related '
        'LLM-side risks, acknowledged as the irreducible '
        'residual risk of retrieval-augmented generation.',
    )


def write_a210_security_policies(doc):
    add_heading(doc, 'A2.10 Security Policies', level=2)
    add_paragraph(
        doc,
        'The nine policies below govern day-to-day operation of '
        'CJPCA on the BBK on-premises host. Each entry names '
        'the policy, the enforcement point in the code, and the '
        'review cadence.',
    )
    rows = [
        (name.split(' ', 1)[1] if ' ' in name else name,
         enforcement.rstrip('.'), review.rstrip('.'))
        for name, _statement, enforcement, review in MG.POLICIES
    ]
    add_caption(doc, 'Table.', 'Security policies.')
    add_table(
        doc,
        headers=['Policy', 'Enforcement point', 'Review'],
        rows=rows,
        widths_cm=[5.0, 8.0, 4.0],
        body_size=9,
    )


def write_a211_logs_detection(doc):
    add_heading(doc, 'A2.11 Logs and Detection Flow', level=2)
    add_paragraph(
        doc,
        'Security events travel through five stages: trigger, '
        'middleware, application handler, AuditLog write, and '
        'per-job log file. Three independent stores (append-only '
        'AuditLog table, write-once per-job log file, and the '
        'SHA-256 hash chain footer on exports) cross-validate '
        'one another. The table below traces three worked '
        'examples.',
    )
    add_caption(doc, 'Table.',
                'Worked examples of logging and detection.')
    add_table(
        doc,
        headers=['Event', 'Trigger and detection chain',
                 'AuditLog action'],
        rows=[
            ('Login failure',
             'Bad password → axes increments counter → 5 fails '
             'in 30 min triggers lockout → Django returns 401',
             'auth.failure (IP, UA, role=anonymous)'),
            ('Prompt injection',
             'Upload PDF with hidden override → Tier-A regex '
             'flags chunk → Tier-B LLM judge classifies '
             '(fail-closed) → QuarantinedChunk row created',
             'ingest.quarantine (doc id, chunk id)'),
            ('Export integrity',
             'Click export → view renders from verified '
             'citations → SHA-256 over identity tuple → first '
             '16 chars stamped in footer',
             'export.create (new hash, prior hash)'),
        ],
        widths_cm=[3.2, 9.0, 4.8],
        body_size=9,
    )


def write_a212_mfa_flow(doc):
    add_heading(doc, 'A2.12 Login and Multi-Factor Authentication '
                'Flow', level=2)
    add_paragraph(
        doc,
        'The figure below traces an account across four swim '
        'lanes: admin provisioning with a temporary password '
        'and the force_password_change and mfa_required flags; '
        'first login with password reset and TOTP enrolment; '
        'steady-state login (axes check → PBKDF2 → TOTP via '
        'django-otp → 1800-second idle timer); and failed-login '
        'lockout on the fifth failure within 30 minutes.',
    )
    add_figure_placeholder(
        doc, 'Figure',
        'CJPCA login and multi-factor authentication flow.')


def write_a213_security_arch_detail(doc):
    add_heading(doc,
                'A2.13 Security Architecture Implementation Details',
                level=2)
    add_paragraph(
        doc,
        'Main body §3.2.5 enumerates controls by OSI tier. This '
        'appendix carries the implementation detail at the '
        'level a maintainer needs to reproduce the configuration.',
    )
    add_caption(doc, 'Table.',
                'Security architecture implementation detail.')
    add_table(
        doc,
        headers=['Control surface', 'Implementation detail'],
        rows=MG.SECURITY_ARCH_ROWS,
        widths_cm=[4.2, 12.8],
        body_size=9,
    )


def write_a214_secure_dev_practices(doc):
    add_heading(doc, 'A2.14 Secure Development Practices', level=2)
    add_paragraph(
        doc,
        'CJPCA applies DevSecOps practices across dependencies, '
        'secrets, CI/CD, logging, monitoring, patching, error '
        'handling, security testing, and incident response.',
    )
    add_caption(doc, 'Table.',
                'Secure development practices applied in CJPCA.')
    add_table(
        doc,
        headers=['Practice area', 'Current state and next step'],
        rows=MG.SEC_DEV_ROWS,
        widths_cm=[4.2, 12.8],
        body_size=9,
    )


def write_a215_prompt_injection_flow(doc):
    add_heading(doc, 'A2.15 Prompt Injection Defence Flow', level=2)
    add_paragraph(
        doc,
        'The figure below traces an uploaded chunk through the '
        'two-tier injection defence. Tier-A runs nine '
        'deterministic regex rule groups; clean chunks go '
        'straight to embedding and indexing. Flagged chunks '
        'cross to Tier-B, the LLM judge with spotlight '
        'delimiters and fail-closed behaviour; an injection '
        'verdict routes the chunk to QuarantinedChunk.',
    )
    add_figure_placeholder(
        doc, 'Figure',
        'CJPCA two-tier prompt injection defence flow.')


def write_a216_geofence_flow(doc):
    add_heading(doc, 'A2.16 GeoFence Middleware Flow', level=2)
    add_paragraph(
        doc,
        'The figure below traces a request through '
        'GeoFenceMiddleware: read forwarded IP, look up country '
        'via MaxMind GeoLite2, compare against the '
        'env-controlled allowlist. Disallowed countries return '
        '403; private and loopback IPs always pass; the '
        'middleware fails open if GeoLite2 is unavailable.',
    )
    add_figure_placeholder(
        doc, 'Figure',
        'CJPCA GeoFence middleware flow.')


def write_a217_audit_hash_chain_flow(doc):
    add_heading(doc, 'A2.17 Audit and Hash Chain Flow', level=2)
    add_paragraph(
        doc,
        'The figure below traces a mutating action: log_event '
        'fires a signal with actor, action, target, and '
        'payload; the sanitiser strips '
        'key/token/secret/password fields; the handler writes '
        'the AuditLog row with user_role_at_time; the per-job '
        'log file captures context; any export chains a '
        'SHA-256 over the row identity tuple and stamps the '
        '16-character prefix into the footer.',
    )
    add_figure_placeholder(
        doc, 'Figure',
        'CJPCA audit log and SHA-256 export hash chain flow.')


# -------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------

def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'appendix_2_solution_design.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = (out_dir /
                             f'appendix_2_solution_design_v{n}.docx')
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    write_intro(doc)
    write_a21_traceability(doc)
    write_a22_key_data_structures(doc)
    write_a23(doc)
    write_a25(doc)
    write_a27(doc)
    write_a28(doc)
    write_a29_risk_assessment(doc)
    write_a210_security_policies(doc)
    write_a211_logs_detection(doc)
    write_a212_mfa_flow(doc)
    write_a213_security_arch_detail(doc)
    write_a214_secure_dev_practices(doc)
    write_a215_prompt_injection_flow(doc)
    write_a216_geofence_flow(doc)
    write_a217_audit_hash_chain_flow(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
