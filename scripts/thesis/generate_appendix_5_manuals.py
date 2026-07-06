"""Generate Appendix 5 — User Manual and System Administrator Manual.

Output: thesis_docs/appendix_5_manuals.docx

Rubric: "Select Two Manuals (User, System Administrator, Configuration,
or Operation)". This appendix delivers two: A5.1 User Manual (analyst
and reviewer flows) and A5.2 System Administrator Manual.

Each manual section has at most one figure slot, placed after the
group of steps it illustrates. Tiny UI elements (dropdowns, single
buttons, modal dialogs) do not get their own figure.
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
    style_map = {1: 'Heading 2', 2: 'Heading 3', 3: 'Heading 4'}
    size_map = {1: 14, 2: 12, 3: 11}
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


def add_step(doc, n: str, title: str, body: str):
    h = doc.add_paragraph()
    h.paragraph_format.space_before = Pt(6)
    h.paragraph_format.space_after = Pt(2)
    r1 = h.add_run(f'Step {n}. ')
    set_run_style(r1, bold=True, color=NAVY, size=11)
    r2 = h.add_run(title)
    set_run_style(r2, bold=True, color=NAVY, size=11)
    add_paragraph(doc, body, space_after=8)


def add_image_placeholder(doc, fig_label: str, caption_text: str,
                          url: str, role: str, show: str,
                          reuse: str = ''):
    p1 = doc.add_paragraph()
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p1.paragraph_format.space_before = Pt(8)
    p1.paragraph_format.space_after = Pt(2)
    r = p1.add_run(f'[ INSERT SCREENSHOT — {fig_label} ]')
    set_run_style(r, bold=True, color=BLACK, size=10)

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p2.paragraph_format.space_after = Pt(2)
    if reuse:
        instr = f'Reuse: {reuse}.  (Delete this line after pasting.)'
    else:
        instr = (f'Capture from {url} as {role}. Show: {show}.  '
                 f'(Delete this line after pasting.)')
    r2 = p2.add_run(instr)
    set_run_style(r2, italic=True, color=MUTED, size=9)

    p3 = doc.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p3.paragraph_format.space_after = Pt(10)
    r3a = p3.add_run(f'{fig_label}. ')
    set_run_style(r3a, bold=True, color=NAVY, size=10)
    r3b = p3.add_run(caption_text)
    set_run_style(r3b, italic=True, color=MUTED, size=10)


# -------------------------------------------------------------------------
# WRITERS
# -------------------------------------------------------------------------

def write_intro(doc):
    add_heading(doc, 'Appendix 5 — User and System Administrator Manuals',
                level=1)
    add_paragraph(
        doc,
        'This appendix delivers the two manuals required by the '
        'thesis rubric. A5.1 documents end-user features for '
        'compliance analysts and reviewers. A5.2 documents the '
        'system administration surface, covering account '
        'provisioning, quarantine review, audit inspection, and '
        'operational controls. Each section is structured as '
        'numbered steps so the manual can be followed from a '
        'fresh login. One screenshot accompanies each distinct '
        'screen the user reaches, placed after the steps it '
        'illustrates.',
    )


def write_user_manual(doc):
    add_heading(doc, 'A5.1 User Manual', level=2)
    add_paragraph(
        doc,
        'This manual covers the two end-user roles: the compliance '
        'analyst, who runs comparisons and mappings, and the '
        'reviewer, who signs off on AI-generated outputs. Both '
        'roles share the same login, dashboard, and Copilot '
        'features, and differ in the workflow surfaces they can '
        'access.',
    )

    add_heading(doc, 'A5.1.1 Getting Started', level=3)
    add_step(doc, '1', 'First-time login.',
             'Open the workspace URL provided by the administrator. '
             'Enter the temporary username and password issued at '
             'account creation. The system will require an '
             'immediate password change on first login.')
    add_step(doc, '2', 'Two-factor enrolment.',
             'After the password change, the workspace redirects '
             'to the TOTP enrolment page. Open an authenticator '
             'app (Microsoft Authenticator, Google Authenticator), '
             'scan the QR code shown, and enter the resulting '
             '6-digit token to confirm. Backup codes are issued '
             'and should be stored securely.')
    add_image_placeholder(doc, 'Figure A5.1',
        'Two-factor enrolment screen showing the TOTP QR code, the typeable secret fallback, and the confirmation token field.',
        url='/accounts/two_factor/setup/', role='new user, first login',
        show='QR code, secret string, token field',
        reuse='§3.3 Figure 47')
    add_step(doc, '3', 'Day-to-day login.',
             'Enter username and password, then the current TOTP '
             'token. Sessions expire after 30 minutes of '
             'inactivity. Five failed login attempts within a '
             '30-minute window lock the account, after which the '
             'administrator must reset it.')

    add_heading(doc, 'A5.1.2 Dashboard Overview', level=3)
    add_paragraph(
        doc,
        'The dashboard summarises corpus status, ingestion '
        'activity, quarantine pending counts, and active users '
        'at a glance. The Copilot dock is reachable from every '
        'page through the icon at the bottom right. The left '
        'sidebar carries shortcuts to Library, Comparison, '
        'Mapping, Review, Analytics, and History.',
    )
    add_image_placeholder(doc, 'Figure A5.2',
        'Workspace dashboard with corpus counters, recent activity, and sidebar navigation.',
        url='/', role='analyst',
        show='full landing view with the stat cards, quick actions, and sidebar')

    add_heading(doc, 'A5.1.3 Document Library', level=3)
    add_paragraph(
        doc,
        'The library lists every ingested regulation and BBK '
        'policy. Users can filter by jurisdiction (Bahrain, '
        'India, Kuwait) and document type, search across the '
        'corpus, or upload new sources. Uploads are processed '
        'in the background and tracked from the dashboard.',
    )
    add_step(doc, '1', 'Browse and search.',
             'Open Library. Filter by jurisdiction or type, or '
             'enter a query to run a hybrid keyword plus semantic '
             'search. Results include the matching chunk with its '
             'source citation.')
    add_image_placeholder(doc, 'Figure A5.3',
        'Document Library with the jurisdiction filter applied and a sample search query.',
        url='/library/regulations/?q=consent', role='analyst',
        show='filter chips, search box, and the ranked result list')
    add_step(doc, '2', 'Upload a new document.',
             'Click Upload, choose a PDF or DOCX, and complete '
             'the metadata form (title, jurisdiction, document '
             'type). The ingestion job runs in the background.')
    add_step(doc, '3', 'Watch ingestion progress.',
             'The dashboard live progress card streams the parse, '
             'chunk, embed, scan, and index stages until the '
             'document is searchable.')
    add_image_placeholder(doc, 'Figure A5.4',
        'Live ingestion progress card on the dashboard showing the document moving through stages.',
        url='/ (during an active upload)', role='analyst',
        show='the progress card with checkpoints visible',
        reuse='§3.3 Figure 29')

    add_heading(doc, 'A5.1.4 Comparing Two Regulations', level=3)
    add_step(doc, '1', 'Select a pair and topic.',
             'Open Comparison, choose the two regulations and the '
             'topic scope (for example, lawful basis, data '
             'subject rights).')
    add_image_placeholder(doc, 'Figure A5.5',
        'Comparison pair picker with regulation A, regulation B, and topic scope selectors.',
        url='/comparison/', role='analyst',
        show='both regulation dropdowns selected and the topic chips')
    add_step(doc, '2', 'Run the comparison and review results.',
             'Click Run. The system retrieves matched obligations, '
             'invokes the reasoning agent, verifies every quote, '
             'and produces a per-obligation verdict with '
             'similarity, confidence, and AI-risk chips. Each '
             'card shows the verdict, side-by-side verbatim '
             'evidence, key difference, and analyst note field.')
    add_image_placeholder(doc, 'Figure A5.6',
        'Comparison result card showing verdict chips, side-by-side regulation evidence, and the analyst note panel.',
        url='/comparison/runs/100/', role='analyst',
        show='one obligation card with sim/conf/AI-risk chips and the two evidence panels',
        reuse='§3.3 Figure 37')

    add_heading(doc, 'A5.1.5 Mapping a Policy Against Regulations',
                level=3)
    add_step(doc, '1', 'Pick a policy and configure scope.',
             'Open Mapping, select a BBK internal policy, then '
             'choose the regulations and topic scope to map '
             'against. Confirm the regulations grouped by '
             'jurisdiction and start the mapping.')
    add_image_placeholder(doc, 'Figure A5.7',
        'Policy mapping selector listing BBK policies with status indicators.',
        url='/mapping/', role='analyst',
        show='policy list with the Run buttons and status chips')
    add_step(doc, '2', 'Review per-obligation coverage.',
             'The workspace shows per-obligation verdicts '
             '(covered, partial, gap) with severity badges, '
             'citation evidence, and the AI confidence band. '
             'Use the override control to change a verdict where '
             'the AI disagrees with analyst judgment. Every '
             'override is captured in the audit log.')
    add_image_placeholder(doc, 'Figure A5.8',
        'Mapping workspace showing one obligation with coverage verdict, severity, citation evidence, and the override control.',
        url='/mapping/40/', role='analyst',
        show='obligation card with verdict, severity, citation, and Override verdict button',
        reuse='§3.3 Figure 41')

    add_heading(doc, 'A5.1.6 Working with Gaps', level=3)
    add_paragraph(
        doc,
        'The Gap Register lists every obligation rated partial '
        'or gap, with severity, AI-suggested remediation, and a '
        'suggested due date computed from severity. Analysts can '
        'request an AI suggestion for any open gap, assign '
        'owners, and add remediation notes that travel with the '
        'gap into the reviewer queue.',
    )
    add_image_placeholder(doc, 'Figure A5.9',
        'Gap Register with severity badges, AI-suggested remediations, and due-date columns.',
        url='/analytics/gaps/', role='analyst',
        show='gap table with severity, remediation, due date, and per-row controls')

    add_heading(doc, 'A5.1.7 Using the Copilot', level=3)
    add_paragraph(
        doc,
        'The Copilot dock opens from the icon at the bottom '
        'right of every page. It supports two modes: Document '
        'QA, which grounds answers in a selected regulation, '
        'and Approved, which reuses evidence from already-'
        'approved comparisons and mappings. Responses carry '
        'provenance chips for source type, confidence, and '
        'citation count, and each citation can be opened in the '
        'document viewer.',
    )
    add_image_placeholder(doc, 'Figure A5.10',
        'Copilot chat interface in Document QA mode showing the user query, the grounded response, and the provenance chips.',
        url='any page, Copilot dock open', role='analyst',
        show='the dock with mode toggle, scope selector, question, answer, and citation chips',
        reuse='§3.3 Figure 43')

    add_heading(doc, 'A5.1.8 Submitting for Review', level=3)
    add_step(doc, '1', 'Submit a completed analysis.',
             'Open the completed mapping or comparison and click '
             'Send to reviewer. The run moves to the reviewer '
             'queue with all analyst notes attached.')
    add_step(doc, '2', 'Reviewer decisions.',
             'Reviewers see pending items at Review and Validate. '
             'Each item exposes the AI verdict, rationale, '
             'side-by-side evidence, and an inline note field. '
             'Reviewers approve, modify with a note, or reject '
             'with a reason. Every transition is logged with '
             'role-at-time evidence.')
    add_image_placeholder(doc, 'Figure A5.11',
        'Reviewer queue with pending items on the left and the decision panel on the right showing approve, reject, and note controls.',
        url='/review/', role='reviewer',
        show='counters, queue items, and the inline modify form',
        reuse='§3.3 Figure 46')

    add_heading(doc, 'A5.1.9 Exporting Reports', level=3)
    add_paragraph(
        doc,
        'Approved analyses can be exported as an Executive '
        'Summary PDF or a Comparison Register XLSX from the '
        'Download package menu. Every export carries a 16-'
        'character SHA-256 audit hash prefix in the footer, '
        'allowing the recipient to verify the document has not '
        'been silently edited after sign-off.',
    )
    add_image_placeholder(doc, 'Figure A5.12',
        'Exported executive summary PDF with the Sign-off and audit block showing the SHA-256 hash prefix.',
        url='exec-summary.pdf (downloaded)', role='analyst',
        show='last page footer of the exported PDF with the audit hash visible',
        reuse='§3.3 Figure 51')

    add_heading(doc, 'A5.1.10 Troubleshooting', level=3)
    add_caption(doc, 'Table.', 'Common analyst and reviewer issues.')
    add_table(
        doc,
        headers=['Symptom', 'Likely cause', 'Action'],
        rows=[
            ('Login fails with valid credentials',
             'Account locked after 5 failed attempts in 30 min.',
             'Wait 30 minutes or ask administrator to reset.'),
            ('Page returns HTTP 403',
             'Action outside the role-based permission scope.',
             'Confirm role with administrator.'),
            ('Ingestion stuck on parse stage',
             'Image-only PDF or unrecognised format.',
             'Try a text-bearing copy of the source PDF.'),
            ('Copilot answers feel incomplete',
             'Active scope too narrow.',
             'Widen the document scope or switch to Approved mode.'),
            ('Export download fails',
             'Run is not yet approved by reviewer.',
             'Confirm status is Approved before exporting.'),
        ],
        widths_cm=[5.0, 5.5, 6.0],
        body_size=9,
    )


def write_admin_manual(doc):
    doc.add_page_break()
    add_heading(doc, 'A5.2 System Administrator Manual', level=2)
    add_paragraph(
        doc,
        'This manual covers the administrative surface available '
        'to users with the administrator role. Administrators '
        'manage accounts, review the quarantine queue, inspect '
        'the AuditLog, monitor system health, and maintain '
        'corpus and access-control configuration. Every '
        'administrative action is captured in the AuditLog with '
        'role-at-time evidence.',
    )

    add_heading(doc, 'A5.2.1 Provisioning Accounts and Roles',
                level=3)
    add_step(doc, '1', 'Open user management.',
             'Go to Accounts then Users. The page shows total, '
             'active, analyst, reviewer, and administrator '
             'counters and the full account list with per-row '
             'controls.')
    add_step(doc, '2', 'Create or modify a user.',
             'Click Add user to provision a new account with '
             'force_password_change and mfa_required flags set, '
             'so the user must rotate the password and enrol '
             'TOTP on first login. Use the row controls to '
             'change role, reset password, reset MFA, or '
             'disable the account.')
    add_image_placeholder(doc, 'Figure A5.13',
        'User Management page showing role distribution counters, the searchable user list, and the per-row reset password, reset MFA, and disable controls.',
        url='/accounts/users/', role='administrator',
        show='stat cards on top and the full table with action buttons',
        reuse='§3.3 Figure 49')
    add_paragraph(
        doc,
        'Role changes never rewrite history. The '
        'user_role_at_time field on every AuditLog row captures '
        'the role active when the action occurred.',
    )

    add_heading(doc, 'A5.2.2 Approving or Rejecting Quarantined Chunks',
                level=3)
    add_step(doc, '1', 'Open the quarantine queue.',
             'Go to Ingestion then Quarantine. The page shows '
             'pending, approved, rejected, and total-flagged '
             'counters with filter tabs.')
    add_step(doc, '2', 'Inspect and decide.',
             'Each card shows the matched rule identifier, '
             'severity, Tier-A or Tier-B origin, the matched '
             'snippet, and the LLM judge reasoning where '
             'applicable. Click Approve to release the chunk to '
             'the index, or Reject to keep it permanently '
             'quarantined. Both actions write to the AuditLog.')
    add_image_placeholder(doc, 'Figure A5.14',
        'Quarantine queue with pending flagged chunks, rule id, severity, matched snippet, and the approve/reject controls.',
        url='/ingestion/quarantine/', role='administrator',
        show='counter cards and the pending chunks list',
        reuse='§3.3 Figure 30')

    add_heading(doc, 'A5.2.3 Inspecting the AuditLog', level=3)
    add_step(doc, '1', 'Open the history view.',
             'Go to History to see the chronological event '
             'stream. The left pane lists events grouped by '
             'date and the right pane shows full event detail '
             'for the selected row.')
    add_step(doc, '2', 'Filter and drill in.',
             'Use the type filter to scope to authentication, '
             'ingestion, mapping, comparison, review, or admin '
             'actions. Use the user filter to scope to a single '
             'actor. Click any event to see timestamp, actor, '
             'role-at-time, action type, target, and the '
             'sanitised metadata payload.')
    add_image_placeholder(doc, 'Figure A5.15',
        'History and Audit Log inspector with the chronological event list, type and user filters, and the event detail panel on the right.',
        url='/history/', role='administrator',
        show='the dual-pane layout with at least one event selected',
        reuse='§3.3 Figure 48')

    add_heading(doc, 'A5.2.4 Monitoring System Health', level=3)
    add_paragraph(
        doc,
        'The System Monitoring page reports active ingestion '
        'jobs, reasoning-layer validation errors, recent '
        'quarantine activity, GeoFence denials, and middleware '
        'health. Use the page during incident triage. Each '
        'panel links into the underlying detail view for '
        'follow-up.',
    )
    add_image_placeholder(doc, 'Figure A5.16',
        'System Monitoring page with health panels for ingestion, reasoning, quarantine, and GeoFence subsystems.',
        url='/accounts/admin/monitoring/', role='administrator',
        show='full monitoring view with all panels visible')

    add_heading(doc, 'A5.2.5 GeoFence Allowlist Management', level=3)
    add_paragraph(
        doc,
        'The GeoFence middleware reads forwarded IPs, looks up '
        'country codes through MaxMind GeoLite2, and compares '
        'them against the environment-controlled allowlist '
        '(default BH, IN, KW). To add or remove a country, '
        'update the GEOFENCE_ALLOWLIST environment variable on '
        'the host and restart the workspace. Disallowed '
        'requests return HTTP 403 with a geofence.deny '
        'AuditLog row, viewable in the History inspector under '
        'the type filter.',
    )

    add_heading(doc, 'A5.2.6 Document Library Administration',
                level=3)
    add_step(doc, '1', 'Bulk-ingest the corpus.',
             'Run the full_ingest management command from the '
             'host to ingest every document under data/ in a '
             'reproducible order. This is the standard '
             'reset-and-reload procedure before a clean run.')
    add_step(doc, '2', 'Delete a document.',
             'Open the document in Library and click Delete. '
             'The Document row, its chunks, and any associated '
             'embeddings are removed from both ChromaDB and '
             'SQLite FTS5. A document.delete AuditLog row '
             'records the action.')

    add_heading(doc, 'A5.2.7 Export Hash Chain Verification', level=3)
    add_paragraph(
        doc,
        'Each PDF and XLSX export carries a 16-character '
        'SHA-256 prefix derived from the row identity tuple. '
        'To verify a received artifact, re-run the audit_hash '
        'helper on the originating row and compare prefixes. '
        'Mismatches indicate either a stale artifact or '
        'post-sign-off tampering. The original export hash is '
        'recorded under export.create in the AuditLog so the '
        'verification value is recoverable.',
    )

    add_heading(doc, 'A5.2.8 Backup and Restore Procedure', level=3)
    add_step(doc, '1', 'Stop the workspace.',
             'Shut down the Daphne ASGI process to ensure '
             'consistent on-disk state.')
    add_step(doc, '2', 'Snapshot the data stores.',
             'Copy the SQLite database file, the ChromaDB data '
             'directory, and the media folder (uploaded source '
             'documents) to the backup target. Back up the '
             '.env file alongside so a restore reproduces the '
             'same middleware order and allowlists.')
    add_step(doc, '3', 'Restore.',
             'On a fresh host, replace the SQLite file, '
             'ChromaDB directory, and media folder. Restart '
             'the workspace and run the AuditLog '
             'verification job to confirm chain integrity.')

    add_heading(doc, 'A5.2.9 Incident Response Playbook', level=3)
    add_caption(doc, 'Table.',
                'Incident triage playbook for the administrator.')
    add_table(
        doc,
        headers=['Indicator', 'Likely cause', 'First response'],
        rows=[
            ('Multiple auth.login_failed for one user',
             'Brute-force attempt or forgotten password.',
             'Confirm with the user, reset password, monitor.'),
            ('geofence.deny spike from a single country',
             'Country-level network event or misconfigured VPN.',
             'Confirm allowlist, inspect denied IPs in History.'),
            ('Quarantine queue growth',
             'Active injection attempt or new attacker pattern.',
             'Review flagged chunks, decide approve or reject.'),
            ('reasoning.validation_error rate spike',
             'LLM provider degradation or schema drift.',
             'Inspect failing parses, check provider status.'),
            ('Export verification fails',
             'Tampered artifact or stale recipient copy.',
             'Re-export from source, compare hash prefixes.'),
        ],
        widths_cm=[5.0, 5.5, 6.0],
        body_size=9,
    )


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'appendix_5_manuals.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'appendix_5_manuals_v{n}.docx'
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
    write_user_manual(doc)
    write_admin_manual(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
