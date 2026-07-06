"""Generate the web-focused Appendix 3 implementation doc.

Output: thesis_docs/appendix_3_implementation_v3.docx

Narrative framing: §3.3 main body explains the AI pipeline conceptually.
This appendix shows HOW the web layer was wrapped around that pipeline.
Part A is the deep web-layer dive (~70%), Part B is lean AI-pipeline
evidence (~20%), Part C is cross-cutting reference (~10%).

All data is grounded in the actual repository: real apps, real URL
patterns, real middleware chain, real management commands, real models.
No invented detail.
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
CODE_BG = 'F3F4F6'


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


def add_code(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.space_before = Pt(2)
    run = p.add_run(text)
    set_run_style(run, color=DARK_GRAY, size=9, font_name='Consolas')


def add_heading(doc, text, *, level=1):
    style_map = {1: 'Heading 2', 2: 'Heading 3', 3: 'Heading 4', 4: 'Heading 5'}
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


def add_table(doc, headers, rows, widths_cm, body_size=9, mono_cols=None):
    mono_cols = mono_cols or set()
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
                        font_name='Consolas' if c_idx in mono_cols else None,
                    )
            _apply_plain_row_borders(cell)


# -------------------------------------------------------------------------
# DATA
# -------------------------------------------------------------------------

APP_INVENTORY = [
    ('accounts', '3,645',
     'User authentication, RBAC, MFA enrolment, password reset'),
    ('analytics', '1,685',
     'Compliance gap analysis, heatmap, conflict detection'),
    ('comparison', '3,709',
     'Regulation-to-regulation clause comparison and equivalence detection'),
    ('core', '1,023',
     'Copilot LLM integration, document viewer, scope management'),
    ('history', '577',
     'Audit logging (AuditLog), user action timeline'),
    ('home', '243',
     'Role-specific dashboards and coverage statistics'),
    ('ingestion', '1,881',
     'Document upload pipeline, quarantine queue, WebSocket log stream'),
    ('library', '2,249',
     'Document management, term dictionary, obligation register'),
    ('mapping', '2,099',
     'Policy-to-regulation obligation mapping and gap remediation'),
    ('review', '1,475',
     'Reviewer queue, review item lifecycle, PDF/XLSX export'),
]


URL_ACCOUNTS = [
    ('GET/POST', '/accounts/logout/', 'GetAwareLogoutView', '(public)'),
    ('GET/POST', '/accounts/users/', 'UserManagementView', 'admin'),
    ('POST', '/accounts/users/new/', 'create_user', 'admin'),
    ('POST', '/accounts/users/<pk>/role/', 'change_role', 'admin'),
    ('POST', '/accounts/users/<pk>/disable/', 'toggle_active', 'admin'),
    ('POST', '/accounts/users/<pk>/reset-password/', 'reset_password',
     'admin'),
    ('POST', '/accounts/users/<pk>/reset-mfa/', 'reset_mfa', 'admin'),
    ('POST', '/accounts/password_change/', 'ForcedPasswordChangeView',
     'login'),
    ('GET', '/accounts/profile/', 'ProfileView', 'login'),
    ('POST', '/accounts/profile/password/', 'ChangePasswordView', 'login'),
    ('POST', '/accounts/profile/backup-codes/',
     'RegenerateBackupCodesView', 'login'),
    ('GET', '/accounts/admin/monitoring/', 'SystemMonitoringView', 'admin'),
    ('POST', '/accounts/heartbeat/', 'heartbeat', 'login'),
]


URL_ANALYTICS = [
    ('GET', '/analytics/', 'AnalyticsView', 'login'),
    ('GET', '/analytics/data/', 'AnalyticsDataView', 'login'),
    ('GET', '/analytics/heatmap/', 'HeatmapPartialView', 'login'),
    ('GET', '/analytics/heatmap/data/', 'HeatmapDataView', 'login'),
    ('GET', '/analytics/gaps/', 'GapRegisterView', 'login'),
    ('GET', '/analytics/cross-gap/', 'CrossJurisdictionGapView', 'login'),
    ('GET', '/analytics/conflicts/', 'ConflictScannerView', 'login'),
]


URL_COMPARISON = [
    ('GET', '/comparison/', 'PairPickerView', 'login'),
    ('POST', '/comparison/run/', 'RunComparisonView', 'login'),
    ('GET', '/comparison/runs/<pk>/', 'ComparisonWorkspaceView', 'login'),
    ('POST', '/comparison/runs/<pk>/submit-review/',
     'SubmitForReviewView', 'login'),
    ('GET', '/comparison/api/pairs/', 'AvailablePairsView', 'login'),
    ('GET', '/comparison/api/topic-scan/', 'TopicScanView', 'login'),
    ('GET', '/comparison/api/documents/<pk>/strictness/',
     'DocumentStrictnessView', 'login'),
    ('GET', '/comparison/runs/<pk>/status/', 'RunStatusView', 'login'),
    ('GET', '/comparison/runs/<pk>/overview/', 'RunOverviewView', 'login'),
    ('GET', '/comparison/runs/<pk>/arcs/', 'RunArcsView', 'login'),
    ('POST', '/comparison/results/<pk>/note/', 'ResultNoteView', 'login'),
    ('GET', '/comparison/runs/<pk>/exports/exec-summary.pdf',
     'ComparisonExecSummaryView', 'login'),
    ('GET', '/comparison/runs/<pk>/exports/comparison-register.xlsx',
     'ComparisonRegisterView', 'login'),
]


URL_CORE = [
    ('POST', '/copilot/message/', 'CopilotMessageView', 'login'),
    ('POST', '/copilot/clear/', 'CopilotClearView', 'login'),
    ('GET', '/copilot/scope/', 'ScopeStateView', 'login'),
    ('PATCH', '/copilot/scope/preferences/', 'ScopePreferencesView',
     'login'),
    ('GET', '/viewer/<doc_id>/<article_id>/', 'DocViewerView', 'login'),
]


URL_HISTORY = [
    ('GET', '/history/', 'HistoryView', 'login'),
    ('GET', '/history/<pk>/', 'EventDetailView', 'login'),
]


URL_HOME = [
    ('GET', '/', 'HomeView', 'login + role'),
]


URL_INGESTION = [
    ('GET', '/ingestion/widget/', 'IngestionWidgetView', 'login'),
    ('GET', '/ingestion/quarantine/', 'QuarantineQueueView', 'login'),
    ('POST', '/ingestion/quarantine/<pk>/<action>/',
     'QuarantineDecideView', 'login'),
]


URL_LIBRARY = [
    ('GET', '/library/regulations/', 'RegulationsView', 'login'),
    ('GET', '/library/policies/', 'PoliciesView', 'login'),
    ('GET', '/library/terms/', 'TermDictionaryView', 'login'),
    ('GET', '/library/search/', 'CrossReferenceSearchView', 'login'),
    ('GET', '/library/obligations/', 'ObligationRegisterView', 'login'),
    ('POST', '/library/upload/', 'DocumentUploadView', 'login'),
    ('GET', '/library/upload/preview/',
     'UploadMetadataPreviewView', 'login'),
    ('POST', '/library/delete/<pk>/', 'DocumentDeleteView', 'login'),
    ('GET', '/library/view/<pk>/', 'DocumentViewerView', 'login'),
    ('POST', '/library/<pk>/tags/', 'DocumentTagView', 'login'),
]


URL_MAPPING = [
    ('GET', '/mapping/', 'PolicySelectView', 'login'),
    ('GET', '/mapping/setup/<pk>/', 'MappingSetupView', 'login'),
    ('POST', '/mapping/setup/<pk>/run/', 'MappingRunView', 'login'),
    ('GET', '/mapping/<pk>/running/', 'MappingRunningView', 'login'),
    ('POST', '/mapping/<pk>/cancel/', 'MappingCancelView', 'login'),
    ('GET', '/mapping/<pk>/progress/', 'MappingProgressAPIView', 'login'),
    ('GET', '/mapping/<pk>/', 'MappingWorkspaceView', 'login'),
    ('GET', '/mapping/evidence/<pk>/', 'EvidencePanelView', 'login'),
    ('POST', '/mapping/obligation/<pk>/override/',
     'CoverageOverrideView', 'login'),
    ('POST', '/mapping/obligation/<pk>/severity/',
     'ObligationSeverityOverrideView', 'login'),
    ('POST', '/mapping/gap/<pk>/save/', 'GapRemediationSaveView', 'login'),
    ('POST', '/mapping/gap/<pk>/suggest/', 'GapAISuggestView', 'login'),
    ('POST', '/mapping/<pk>/send-to-review/', 'SendToReviewView', 'login'),
    ('POST', '/mapping/<pk>/validate/', 'ValidateAnalysisView', 'login'),
    ('POST', '/mapping/gap/<pk>/assign/', 'GapAssignView', 'login'),
    ('GET', '/mapping/<pk>/exports/exec-summary.pdf',
     'MappingExecSummaryView', 'login'),
    ('GET', '/mapping/<pk>/exports/gap-register.xlsx',
     'MappingGapRegisterView', 'login'),
]


URL_REVIEW = [
    ('GET', '/review/', 'ReviewQueueView', 'login'),
    ('GET', '/review/item/<pk>/', 'ReviewItemDetailView', 'login'),
    ('GET', '/review/export/<format>/', 'ReviewExportView', 'login'),
]


URL_TABLES = [
    ('accounts', URL_ACCOUNTS),
    ('analytics', URL_ANALYTICS),
    ('comparison', URL_COMPARISON),
    ('core', URL_CORE),
    ('history', URL_HISTORY),
    ('home', URL_HOME),
    ('ingestion', URL_INGESTION),
    ('library', URL_LIBRARY),
    ('mapping', URL_MAPPING),
    ('review', URL_REVIEW),
]


MIDDLEWARE_CHAIN = [
    ('1', 'SecurityMiddleware', 'Django built-in',
     'TLS upgrade, secure headers, HSTS'),
    ('2', 'WhiteNoiseMiddleware', 'whitenoise',
     'Compressed manifest static file serving'),
    ('3', 'GeoFenceMiddleware', 'CJPCA custom',
     'MaxMind GeoLite2 allowlist (BH, IN, KW)'),
    ('4', 'CSPMiddleware', 'django-csp',
     'Content Security Policy headers'),
    ('5', 'SessionMiddleware', 'Django built-in',
     'Signed session cookie management'),
    ('6', 'CommonMiddleware', 'Django built-in',
     'URL normalisation, ALLOWED_HOSTS check'),
    ('7', 'CsrfViewMiddleware', 'Django built-in',
     'CSRF token verification'),
    ('8', 'AuthenticationMiddleware', 'Django built-in',
     'Attach request.user from session'),
    ('9', 'OTPMiddleware', 'django-otp',
     'Attach verified TOTP device to request'),
    ('10', 'IdleSessionTimeoutMiddleware', 'CJPCA custom',
     '1800 s idle logout, writes auth.idle_timeout'),
    ('11', 'ForcePasswordChangeMiddleware', 'CJPCA custom',
     'Redirect to password change if flagged'),
    ('12', 'ForceMFAEnrollmentMiddleware', 'CJPCA custom',
     'Redirect to MFA setup before any view'),
    ('13', 'MessageMiddleware', 'Django built-in',
     'Flash-message framework'),
    ('14', 'XFrameOptionsMiddleware', 'Django built-in',
     'X-Frame-Options DENY clickjacking guard'),
    ('15', 'HtmxMiddleware', 'django-htmx',
     'Detect HTMX requests, attach request.htmx'),
    ('16', 'AxesMiddleware', 'django-axes',
     'Brute-force lockout (5 fails / 30 min)'),
]


MANAGEMENT_COMMANDS = [
    ('run_comparison_job', 'comparison',
     'Execute a ComparisonRun by PK (subprocess launcher)',
     'run_pk, --include-orphans, --articles-a, --articles-b'),
    ('cleanup_failed', 'core', 'Cleanup stale failed jobs', 'none'),
    ('demo_injection_doc', 'ingestion',
     'Seed a demo document with injection payloads for testing', 'none'),
    ('full_ingest', 'ingestion',
     'Bulk ingest all documents from data/metadata.csv', 'none'),
    ('process_queued_jobs', 'ingestion',
     'Launch background pipeline for queued IngestionJobs',
     '--job-id (optional), --wait'),
    ('seed_demo', 'ingestion', 'Seed demo documents and regulations',
     'none'),
    ('classify_chunks', 'library', 'Batch-classify chunks by topic',
     'none'),
    ('classify_doc_topics', 'library',
     'Classify entire documents by topic', 'none'),
    ('reconcile_library', 'library',
     'Sync library state (dedupe, reindex)', 'none'),
    ('restore_from_chunks', 'library',
     'Rebuild documents from indexed chunks', 'none'),
    ('sync_documents', 'library', 'Sync document metadata', 'none'),
    ('run_mapping_job', 'mapping',
     'Execute a MappingAnalysis by PK (subprocess launcher)',
     'analysis_id'),
    ('seed_review_samples', 'review', 'Populate demo review items',
     'none'),
]


MIGRATIONS_SUMMARY = [
    ('accounts', '2',
     '0002_userprofile_must_change_password',
     'Add must_change_password BooleanField'),
    ('comparison', '7',
     '0007_comparisonrun_analyst_note_and_more',
     'Add analyst_note and review submission fields'),
    ('history', '2',
     '0002_auditlog_ip_address_auditlog_user_role_at_time_and_more',
     'Add IP address and role-at-time snapshot fields'),
    ('ingestion', '4',
     '0004_quarantinedchunk',
     'Create QuarantinedChunk model'),
    ('library', '6',
     '0006_document_applicable_sector_document_concept_tags_csv_and_more',
     'Add sector, concept tags, regulation metadata'),
    ('mapping', '9',
     '0009_mappinganalysis_analyst_note_and_more',
     'Add analyst_note and review submission fields'),
    ('review', '1', '0001_initial',
     'Initial ReviewItem model'),
]


AUDITLOG_ACTIONS = [
    ('Authentication', 'auth.login', 'Successful login'),
    ('Authentication', 'auth.login_failed', 'Failed login attempt'),
    ('Authentication', 'auth.logout', 'User logout'),
    ('Authentication', 'auth.idle_timeout',
     'Forced logout after idle window'),
    ('Authentication', 'auth.mfa_enrolled',
     'TOTP device enrolled'),
    ('Authentication', 'auth.mfa_reset', 'TOTP device reset by admin'),
    ('Authentication', 'auth.backup_codes_regenerated',
     'Backup codes regenerated'),
    ('Authentication', 'auth.sessions_terminated',
     'Admin invalidated user sessions'),
    ('Analyst flow', 'comparison.run', 'Comparison job launched'),
    ('Analyst flow', 'comparison.complete', 'Comparison job completed'),
    ('Analyst flow', 'comparison.failed', 'Comparison job failed'),
    ('Analyst flow', 'mapping.run', 'Mapping job launched'),
    ('Analyst flow', 'mapping.complete', 'Mapping job completed'),
    ('Analyst flow', 'mapping.failed', 'Mapping job failed'),
    ('Reviewer flow', 'review.submit', 'Item submitted for review'),
    ('Reviewer flow', 'review.accept', 'Reviewer accepted'),
    ('Reviewer flow', 'review.reject', 'Reviewer rejected'),
    ('Reviewer flow', 'review.modify', 'Reviewer modified before accept'),
    ('Corpus', 'document.upload', 'Document uploaded'),
    ('Corpus', 'document.delete', 'Document deleted'),
    ('Corpus', 'ingestion.complete', 'Ingestion pipeline succeeded'),
    ('Corpus', 'ingestion.failed', 'Ingestion pipeline failed'),
    ('System', 'reasoning.validation_error',
     'Pydantic schema validation failed'),
    ('System', 'quarantine.flagged',
     'Chunk flagged by Tier-A or Tier-B'),
    ('System', 'quarantine.approved', 'Quarantine cleared by admin'),
    ('System', 'quarantine.rejected', 'Quarantine confirmed by admin'),
    ('Admin', 'user.created', 'New user created'),
    ('Admin', 'user.role_changed', 'User role changed'),
    ('Admin', 'user.disabled', 'User disabled or re-enabled'),
    ('Admin', 'user.password_reset', 'Admin reset user password'),
    ('Admin', 'user.password_changed',
     'User changed own password'),
]


ENV_VARS = [
    ('DEBUG', 'false', 'Production mode toggles SSL redirect, HSTS, '
     'secure cookies'),
    ('DJANGO_ALLOWED_HOSTS', 'cjpca.example.com',
     'Comma-separated host allowlist'),
    ('OPENROUTER_API_KEY', 'sk-or-v1-...',
     'External LLM key for Claude Haiku judge fallback'),
    ('SESSION_IDLE_TIMEOUT', '1800',
     'Idle logout in seconds, default 30 min'),
    ('GEOFENCE_ENABLED', 'false',
     'Toggle the MaxMind country allowlist'),
    ('GEOFENCE_ALLOWED_COUNTRIES', 'BH,IN,KW',
     'ISO 3166-1 alpha-2 country codes'),
    ('REQUIRE_MFA', 'true',
     'Force TOTP enrolment before any view loads'),
    ('EMAIL_BACKEND',
     'django.core.mail.backends.console.EmailBackend',
     'Use SMTP backend in production'),
    ('EMAIL_HOST', 'smtp.gmail.com', 'SMTP relay host'),
    ('EMAIL_PORT', '587', 'SMTP TLS port'),
    ('EMAIL_USE_TLS', 'true', 'STARTTLS handshake'),
    ('EMAIL_HOST_USER', 'your-email@gmail.com', 'SMTP login'),
    ('EMAIL_HOST_PASSWORD', '<16-char app password>', 'Gmail app password'),
    ('DEFAULT_FROM_EMAIL', 'your-email@gmail.com',
     'From: address on outgoing mail'),
]


SETTINGS_KEYS = [
    ('SESSION_COOKIE_AGE', '60 * 60 * 8 (28800 s, 8 h)',
     'Absolute session lifetime'),
    ('SESSION_IDLE_TIMEOUT', '60 * 30 (1800 s, 30 min)',
     'Custom middleware enforces idle window'),
    ('SESSION_COOKIE_SECURE', 'True in production',
     'Cookie sent over HTTPS only'),
    ('SESSION_COOKIE_HTTPONLY', 'True',
     'JavaScript cannot read session cookie'),
    ('SESSION_COOKIE_SAMESITE', "'Lax'", 'CSRF mitigation'),
    ('AXES_FAILURE_LIMIT', '5',
     'Failed logins before lockout'),
    ('AXES_COOLOFF_TIME', '0.5 (30 min)',
     'Lockout duration in hours'),
    ('AUTH_PASSWORD_VALIDATORS', '6 validators',
     'UserAttributeSimilarity (0.5), MinimumLength (12), CommonPassword, '
     'NumericPassword, ComplexityValidator (custom), '
     'NoUsernameValidator (custom)'),
    ('ALLOWED_HOSTS', 'env-driven',
     'localhost in dev, FQDN in production'),
    ('SECURE_HSTS_SECONDS', '31,536,000 in production',
     '1-year HSTS, includeSubDomains, preload'),
    ('SECURE_SSL_REDIRECT', 'True in production',
     'HTTP requests upgraded to HTTPS'),
    ('CSP_DEFAULT_SRC', "('self',)",
     'Default-src self-origin only'),
    ('CSP_SCRIPT_SRC',
     "('self', 'unsafe-inline', 'unsafe-eval', unpkg, jsdelivr)",
     'HTMX, Alpine.js, Chart.js sources'),
    ('CSP_STYLE_SRC',
     "('self', 'unsafe-inline', fontshare, fonts.googleapis)",
     'Tailwind inline plus font CDNs'),
    ('CSP_FONT_SRC',
     "('self', 'data:', fontshare, fonts.gstatic)",
     'Satoshi and Google Fonts'),
    ('CSP_IMG_SRC',
     "('self', 'data:', 'blob:', flagcdn, fontshare)",
     'Inline images and flag CDN'),
]


# -------------------------------------------------------------------------
# WRITERS
# -------------------------------------------------------------------------

def write_intro(doc):
    add_heading(doc, 'Appendix 3 — Implementation Evidence', level=1)
    add_paragraph(
        doc,
        'This appendix carries the code- and configuration-level '
        'evidence behind §3.3. Part A documents the Django web '
        'layer (apps, routes, views, templates, HTMX/Alpine '
        'patterns, page deep dives). Part B is a reference to '
        'the AI-pipeline code outlines. Part C collects '
        'cross-cutting tables. All extracted from the live '
        'repository.',
    )


def write_part_a(doc):
    doc.add_page_break()
    add_heading(doc, 'Part A — Web Layer Build', level=1)

    add_heading(doc, 'A.1 Why a web layer on top of the AI pipeline',
                level=2)
    add_paragraph(
        doc,
        'The AI pipeline could in principle run from a REPL, but '
        'analysts need authentication, RBAC, structured forms, '
        'live progress, evidence panels, review workflows, and '
        'signed exports. The web layer is Django 5 + HTMX 2 + '
        'Alpine.js 3. HTMX (rather than an SPA) keeps the '
        'security boundary server-side and avoids shipping '
        'reasoning prompts or chunk content to the browser.',
    )

    add_heading(doc, 'A.2 Django app inventory', level=2)
    add_caption(
        doc, 'Table.',
        'CJPCA Django app inventory. Line counts exclude migrations.')
    add_table(
        doc,
        headers=['App', 'Lines', 'Purpose'],
        rows=APP_INVENTORY,
        widths_cm=[2.5, 1.5, 12.5],
        body_size=9,
    )

    add_heading(doc, 'A.3 URL routing per app', level=2)
    add_paragraph(
        doc,
        'Every URL pattern is listed below with its view and '
        'access requirement. login = @login_required or '
        'LoginRequiredMixin; admin = @role_required(\'admin\'); '
        '(public) reaches only the logout endpoint.',
    )
    for app_name, rows in URL_TABLES:
        add_heading(doc, f'A.3.{app_name}', level=3)
        add_caption(
            doc, f'the table below.{app_name}.',
            f'URL patterns in cjpca/apps/{app_name}/urls.py.')
        add_table(
            doc,
            headers=['Method', 'Path', 'View', 'Access'],
            rows=rows,
            widths_cm=[1.8, 6.5, 5.7, 2.5],
            body_size=8,
            mono_cols={1, 2},
        )

    add_heading(doc, 'A.4 View architecture', level=2)
    add_paragraph(
        doc,
        'Class-based views handle multi-phase workflows (Mapping, '
        'Comparison, Library, Analytics); function views handle '
        'short admin actions. All views inherit '
        'LoginRequiredMixin; role-gated views add RoleRequiredMixin '
        '(or the @role_required decorator on function views), '
        'which checks request.user.profile.role and writes an '
        'auth.forbidden AuditLog row on rejection.',
    )

    add_heading(doc, 'A.5 Template inheritance', level=2)
    add_paragraph(
        doc,
        '75 HTML files inherit from base.html (Tailwind, HTMX, '
        'Alpine, navigation chrome, copilot dock, idle-timeout '
        'modal). Page templates extend base.html and override '
        'block content; partials under cjpca/templates/partials/ '
        'render through HTMX swaps. The heaviest templates are '
        'comparison_workspace.html and mapping_workspace.html '
        '(73 HTMX + Alpine attributes each).',
    )

    add_heading(doc, 'A.6 HTMX patterns', level=2)
    add_paragraph(
        doc,
        'HTMX 2 drives every server-side update without a page '
        'reload (132 attributes across the codebase). Six '
        'attributes are used systematically: hx-get/hx-post, '
        'hx-target, hx-trigger (including "every 2s" polling), '
        'hx-swap (innerHTML/outerHTML/beforeend), and hx-vals. '
        'Four hot paths use HTMX: ingestion-widget progress '
        'polling, quarantine queue row swaps, mapping evidence '
        'panel updates, and comparison relationship-note edits.',
    )

    add_heading(doc, 'A.7 Alpine.js patterns', level=2)
    add_paragraph(
        doc,
        'Alpine.js 3 (336 attributes) carries client-side state '
        'that needs no server round trip: modals, tab switching, '
        'conditional filters, dropdowns, validation hints, and '
        'the idle countdown. Five directives are used (x-data, '
        'x-show, x-on, x-bind, x-model). Alpine never issues '
        'network calls; all data fetches go through HTMX, keeping '
        'the security boundary server-side.',
    )

    add_heading(doc, 'A.8 Forms layer', level=2)
    add_paragraph(
        doc,
        'Forms are deliberately minimal: only RegistrationForm '
        'subclasses Django UserCreationForm. Every other view '
        'validates request.POST inline, since HTMX submits small '
        'known field sets. Sensitive inputs (passwords, TOTP '
        'codes) still go through Django PasswordChangeForm and '
        'django-otp confirmation, retaining the framework '
        'validators.',
    )

    add_heading(doc, 'A.9 Real-time progress via Django Channels', level=2)
    add_paragraph(
        doc,
        'Ingestion is the only workflow that pushes '
        'server-initiated updates. The pipeline subprocess writes '
        'log entries to a Redis channel keyed by job_id; '
        'IngestionConsumer (apps/ingestion/consumers.py) forwards '
        'them to subscribed WebSocket clients. Comparison and '
        'mapping use HTMX polling instead. If the WebSocket drops, '
        'the widget falls back to 2-second HTMX polling.',
    )
    add_code(
        doc,
        "# cjpca/routing.py\n"
        "from django.urls import re_path\n"
        "from apps.ingestion import consumers\n\n"
        "websocket_urlpatterns = [\n"
        "    re_path(\n"
        "        r'^ws/ingestion/(?P<job_id>[^/]+)/$',\n"
        "        consumers.IngestionConsumer.as_asgi(),\n"
        "    ),\n"
        "]\n",
    )

    add_heading(doc, 'A.10 Library page deep dive', level=2)
    add_paragraph(
        doc,
        'Library views: RegulationsView and PoliciesView render '
        'Document querysets filtered by jurisdiction (BH, IN, KW) '
        'with HTMX filter chips. DocumentUploadView validates '
        'file extension/size, saves to media/uploads/, creates '
        'Document and IngestionJob rows (status=queued); the '
        'pipeline runs in a separate subprocess. '
        'DocumentViewerView renders the article tree with HTMX '
        'panel swaps. TermDictionaryView paginates the 200-entry '
        'synonym dictionary with equivalence overlays. '
        'CrossReferenceSearchView wraps retrieval.hybrid_search '
        'within library scope.',
    )

    add_heading(doc, 'A.11 Comparison page deep dive', level=2)
    add_paragraph(
        doc,
        'PairPickerView selects two regulations and a topic. '
        'RunComparisonView creates the ComparisonRun row, writes '
        'a comparison.run AuditLog entry, and launches '
        'run_comparison_job as a subprocess. '
        'ComparisonWorkspaceView renders the shell; HTMX '
        'endpoints (RunStatusView, RunOverviewView, RunArcsView, '
        'RunInsightsView) progressively fill in tabs. Export '
        'endpoints stream comparison-register.xlsx and '
        'exec-summary.pdf with the SHA-256 hash chain footer.',
    )

    add_heading(doc, 'A.12 Mapping page deep dive', level=2)
    add_paragraph(
        doc,
        'Mapping is the largest workspace (17 URL patterns). '
        'PolicySelectView lists policies; MappingSetupView '
        'configures regulations, topic, and scope mode; '
        'MappingRunView writes the MappingAnalysis row and '
        'launches run_mapping_job. MappingRunningView polls '
        'MappingProgressAPIView every 2 s. On completion, '
        'MappingWorkspaceView renders the obligation grid with '
        'HTMX evidence panels. Override views '
        '(CoverageOverrideView, ObligationSeverityOverrideView, '
        'GapRemediationSaveView, GapAISuggestView) plus '
        'SendToReviewView and ValidateAnalysisView close the '
        'workflow.',
    )

    add_heading(doc, 'A.13 Copilot deep dive', level=2)
    add_paragraph(
        doc,
        'CopilotMessageView accepts a JSON body with the user '
        'message and scope context (active document, '
        'obligation, comparison run); forwards to '
        'reasoning.orchestrator with scope as system context; '
        'streams the response via HTMX server-sent partials. '
        'ScopeStateView, ScopePreferencesView, and '
        'CopilotClearView handle scope reporting, preferences, '
        'and conversation reset (the AuditLog is never wiped).',
    )

    add_heading(doc, 'A.14 Analytics deep dive', level=2)
    add_paragraph(
        doc,
        'AnalyticsView renders the dashboard shell; '
        'AnalyticsDataView serves top-level KPIs (coverage, gap '
        'severity, mapping count). HeatmapPartialView and '
        'HeatmapDataView render the jurisdiction-by-topic '
        'heatmap. GapRegisterView, CrossJurisdictionGapView, and '
        'ConflictScannerView surface gap-level views.',
    )

    add_heading(doc, 'A.15 Admin and RBAC management', level=2)
    add_paragraph(
        doc,
        'The accounts app replaces the default Django admin. '
        'UserManagementView lists users with role, MFA status, '
        'last login, and lockout state. create_user, '
        'change_role, toggle_active, reset_password, and '
        'reset_mfa are @role_required(\'admin\')-guarded views '
        'that write user.* AuditLog actions. SystemMonitoringView '
        'shows failed-login counts, axes lockouts, and quarantine '
        'depth. ProfileView, ChangePasswordView, and '
        'RegenerateBackupCodesView cover the self-service '
        'surface.',
    )


def write_part_b(doc):
    doc.add_page_break()
    add_heading(doc, 'Part B — AI Pipeline Evidence', level=1)
    add_paragraph(
        doc,
        'Part B is a lean reference to the AI-pipeline code outlines '
        'that back the main-body §3.3.7 (Ingestion), §3.3.8 (Retrieval), '
        'and §3.3.9 (Reasoning) descriptions. The full NDA-safe outline '
        'files (function signatures plus step comments with pass bodies) '
        'are in thesis_docs/code_3_3_outlines/. Only the public API of '
        'each module is summarised here.',
    )

    add_heading(doc, 'B.1 Ingestion package', level=2)
    add_table(
        doc,
        headers=['File', 'Public functions / classes',
                 'Purpose (1 line)'],
        rows=[
            ('ingestion/loaders.py',
             'load_pdf, load_docx, load_html',
             'Docling-backed document parsers'),
            ('ingestion/chunker.py',
             'chunk_document, estimate_tokens, _classify',
             'Section-aware splitter with rule-based tag pass'),
            ('ingestion/embedder.py',
             'embed_chunks, embed_text, get_model',
             'BGE-small-en-v1.5 embedder (384 dims)'),
            ('ingestion/indexer.py',
             'index_chunks, index_bm25',
             'Writes to ChromaDB HNSW and SQLite FTS5'),
            ('ingestion/injection_scanner.py',
             'tier_a_scan, tier_b_judge, scan_chunk',
             '9-rule regex plus Claude Haiku LLM judge'),
            ('ingestion/pipeline.py',
             'run_pipeline',
             'Orchestrates load, chunk, embed, scan, index'),
        ],
        widths_cm=[4.5, 5.5, 6.5],
        body_size=8,
        mono_cols={0, 1},
    )
    add_paragraph(doc,
                  'Ingestion pipeline orchestrator.',
                  italic=True, color=MUTED, size=10, space_after=2)
    add_code(
        doc,
        "# ingestion/pipeline.py\n"
        "def run_pipeline(job_id: int) -> None:\n"
        "    \"\"\"End-to-end ingestion for one queued document.\"\"\"\n"
        "    # 1. Load the IngestionJob and mark status='running'.\n"
        "    # 2. Dispatch on file extension to the matching loader\n"
        "    #    (PDF, DOCX, HTML) via the Docling-backed loaders.\n"
        "    # 3. Call chunk_document() to produce section-aware chunks\n"
        "    #    with the rule-based classifier pass.\n"
        "    # 4. Run tier_a_scan() on every chunk. Suspect chunks go\n"
        "    #    to tier_b_judge() for a Claude Haiku verdict.\n"
        "    # 5. Insert flagged chunks into QuarantinedChunk and skip\n"
        "    #    them from indexing.\n"
        "    # 6. Call embed_chunks() on the clean chunks and write to\n"
        "    #    ChromaDB via index_chunks().\n"
        "    # 7. Mirror the clean chunks into the SQLite FTS5 store\n"
        "    #    via index_bm25().\n"
        "    # 8. Update the IngestionJob: status='complete',\n"
        "    #    progress_pct=100, log_entries tail.\n"
        "    # 9. Write ingestion.complete AuditLog row.\n"
        "    # 10. On any exception, mark status='failed', write\n"
        "    #     ingestion.failed AuditLog row, and re-raise.\n"
        "    pass\n"
    )
    add_paragraph(doc,
                  'Two-tier prompt-injection scanner.',
                  italic=True, color=MUTED, size=10, space_after=2)
    add_code(
        doc,
        "# ingestion/injection_scanner.py\n"
        "def scan_chunk(chunk_text: str) -> ScanVerdict:\n"
        "    \"\"\"Return the combined Tier-A and Tier-B verdict.\"\"\"\n"
        "    # 1. Run tier_a_scan(): 9 regex rule groups for known\n"
        "    #    instruction-override patterns. Each match records\n"
        "    #    rule_id, severity, matched_snippet.\n"
        "    # 2. If Tier-A returns clean, the chunk is cleared.\n"
        "    # 3. If Tier-A fires, call tier_b_judge() with the chunk\n"
        "    #    wrapped in spotlight delimiters.\n"
        "    # 4. tier_b_judge() calls Claude Haiku 4.5 with a strict\n"
        "    #    JSON schema response. Network or parse failure falls\n"
        "    #    back to Ollama. Any error short-circuits to 'block'.\n"
        "    # 5. Return ScanVerdict with verdict in {allow, quarantine,\n"
        "    #    block}, the firing rule, and the judge reason.\n"
        "    pass\n"
    )

    add_heading(doc, 'B.2 Retrieval package', level=2)
    add_table(
        doc,
        headers=['File', 'Public functions / classes',
                 'Purpose (1 line)'],
        rows=[
            ('retrieval/retriever.py',
             'hybrid_search, search_comparative, '
             'RetrievalService, _SQLiteBM25Retriever, _rerank_candidates',
             'Hybrid orchestrator (BM25 + Chroma + RRF + rerank)'),
            ('retrieval/bm25_store.py',
             'create_fts_table, insert_chunk, search',
             'SQLite FTS5 virtual table CRUD'),
        ],
        widths_cm=[4.5, 5.5, 6.5],
        body_size=8,
        mono_cols={0, 1},
    )
    add_paragraph(doc, 'hybrid_search entry point.',
                  italic=True, color=MUTED, size=10, space_after=2)
    add_code(
        doc,
        "# retrieval/retriever.py\n"
        "def hybrid_search(query, jurisdictions=None,\n"
        "                  doc_types=None, top_k=5):\n"
        "    \"\"\"Top entry point used by every reasoning workflow.\"\"\"\n"
        "    # 1. Expand the query via term_dictionary.synonyms_for_query.\n"
        "    # 2. Embed the expanded query with the BGE query prefix.\n"
        "    # 3. Construct two retrievers: a Chroma vector retriever\n"
        "    #    and a _SQLiteBM25Retriever filtered by jurisdictions\n"
        "    #    and doc_types.\n"
        "    # 4. Wrap them in QueryFusionRetriever(\n"
        "    #         mode='reciprocal_rerank', k=60).\n"
        "    # 5. Pull a candidate pool of size 20.\n"
        "    # 6. Rerank against the ORIGINAL query (not expanded)\n"
        "    #    with an ms-marco MiniLM cross-encoder.\n"
        "    # 7. Truncate to top_k and return the ranked list.\n"
        "    pass\n"
    )

    add_heading(doc, 'B.3 Reasoning package', level=2)
    add_table(
        doc,
        headers=['File', 'Public functions / classes',
                 'Purpose (1 line)'],
        rows=[
            ('reasoning/schemas.py',
             'ChunkTag, Citation, ReasoningOutput, ComparisonOutput, '
             'MappingOutput, GapOutput',
             'Pydantic v2 schemas for every reasoning artefact'),
            ('reasoning/classifier.py',
             'classify_chunk, classify_chunk_async',
             'Taxonomy classifier with OutputFixingParser'),
            ('reasoning/generator.py',
             'draft_answer, draft_comparison, draft_mapping',
             'Initial reasoning draft from retrieved context'),
            ('reasoning/validators.py',
             'verify_citations, score_hallucination',
             'Verbatim citation verifier and NLI score'),
            ('reasoning/fallback.py',
             'SafeFallback, safe_fallback_for',
             'Typed-empty report when reasoning fails'),
            ('reasoning/workflows.py',
             'comparison_workflow, mapping_workflow, '
             'gap_suggestion_workflow',
             'LangGraph state machines (draft, verify, correct, '
             'finalize, fallback)'),
            ('reasoning/orchestrator.py',
             'orchestrate_mapping, orchestrate_comparison, '
             'orchestrate_copilot',
             'Top-level entry points called by views'),
            ('reasoning/term_dictionary.py',
             'synonyms_for_query, expand_query, all_terms, '
             'by_category, lookup',
             'Jurisdictional synonym dictionary (200 terms)'),
        ],
        widths_cm=[4.5, 5.5, 6.5],
        body_size=8,
        mono_cols={0, 1},
    )
    add_paragraph(doc,
                  'comparison_workflow LangGraph state '
                  'machine.',
                  italic=True, color=MUTED, size=10, space_after=2)
    add_code(
        doc,
        "# reasoning/workflows.py\n"
        "def comparison_workflow(reg_a_id: int, reg_b_id: int,\n"
        "                        topic: str) -> ComparisonOutput:\n"
        "    \"\"\"LangGraph state machine for clause comparison.\"\"\"\n"
        "    # Nodes: draft -> verify -> correct -> finalize -> fallback.\n"
        "    # 1. draft: retrieve clauses with hybrid_search for both\n"
        "    #    regulations, prompt the LLM for a structured draft\n"
        "    #    that fits ComparisonOutput.\n"
        "    # 2. verify: run verify_citations() against the draft.\n"
        "    #    Each clause must be a verbatim span of a retrieved\n"
        "    #    chunk. Run score_hallucination() (cross-encoder NLI).\n"
        "    # 3. correct: if citations fail or NLI score is below the\n"
        "    #    threshold, prompt the LLM with the failures and try\n"
        "    #    once more (OutputFixingParser bounded retry).\n"
        "    # 4. finalize: validate against the Pydantic schema, write\n"
        "    #    the ComparisonRun.report_json field.\n"
        "    # 5. fallback: on any unrecoverable failure return\n"
        "    #    safe_fallback_for(ComparisonOutput), a typed-empty\n"
        "    #    report with reason_code and audit row.\n"
        "    pass\n"
    )
    add_paragraph(doc,
                  'Citation verifier enforcing verbatim '
                  'grounding.',
                  italic=True, color=MUTED, size=10, space_after=2)
    add_code(
        doc,
        "# reasoning/validators.py\n"
        "def verify_citations(\n"
        "    draft: ReasoningOutput,\n"
        "    retrieved_chunks: list[Chunk],\n"
        ") -> list[CitationError]:\n"
        "    \"\"\"Reject any clause that is not a verbatim chunk span.\"\"\"\n"
        "    # 1. For each clause in the draft, locate the cited\n"
        "    #    chunk_id in retrieved_chunks.\n"
        "    # 2. Normalise whitespace and lowercase both strings.\n"
        "    # 3. Check that the clause substring exists verbatim in\n"
        "    #    the chunk text.\n"
        "    # 4. Record a CitationError(clause_id, chunk_id, reason)\n"
        "    #    for any mismatch.\n"
        "    # 5. Return the list of errors. Empty list means draft\n"
        "    #    passes verification.\n"
        "    pass\n"
    )

    add_heading(doc, 'B.4 Environment variable reference', level=2)
    add_caption(
        doc, 'Table.',
        'Required and optional environment variables (excerpt from '
        '.env.example).')
    add_table(
        doc,
        headers=['Variable', 'Example value', 'Purpose'],
        rows=ENV_VARS,
        widths_cm=[5.0, 5.0, 6.5],
        body_size=8,
        mono_cols={0, 1},
    )

    add_heading(doc, 'B.5 Settings highlights', level=2)
    add_caption(
        doc, 'Table.',
        'Selected settings keys, the configured value, and the security '
        'or operational role each plays.')
    add_table(
        doc,
        headers=['Setting', 'Value', 'Purpose'],
        rows=SETTINGS_KEYS,
        widths_cm=[4.8, 4.5, 7.2],
        body_size=8,
        mono_cols={0, 1},
    )

    add_heading(doc, 'B.6 Deployment configuration', level=2)
    add_paragraph(
        doc,
        'Daphne ASGI behind Caddy reverse proxy with TLS 1.3 '
        'termination; WhiteNoise serves static assets. The three '
        'listings below cover the minimum config (ASGI entry '
        'point, requirements pins, Caddyfile).',
    )

    add_paragraph(doc, 'cjpca/asgi.py (verbatim).',
                  italic=True, color=MUTED, size=10, space_after=2)
    add_code(
        doc,
        "# cjpca/cjpca/asgi.py\n"
        "import os\n\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE',\n"
        "                      'cjpca.settings')\n\n"
        "from django.core.asgi import get_asgi_application\n\n"
        "# Initialise the Django ASGI application early so the app\n"
        "# registry is populated before the channels routing module\n"
        "# imports app code.\n"
        "django_asgi_app = get_asgi_application()\n\n"
        "from channels.routing import ProtocolTypeRouter, URLRouter\n"
        "from channels.auth import AuthMiddlewareStack\n"
        "import cjpca.routing\n\n"
        "application = ProtocolTypeRouter({\n"
        "    'http': django_asgi_app,\n"
        "    'websocket': AuthMiddlewareStack(\n"
        "        URLRouter(cjpca.routing.websocket_urlpatterns)\n"
        "    ),\n"
        "})\n"
    )

    add_paragraph(
        doc,
        'requirements.txt excerpt (key load-bearing '
        'dependencies, version constraints as pinned in the repo).',
        italic=True, color=MUTED, size=10, space_after=2)
    add_code(
        doc,
        "# Core framework\n"
        "Django>=5.0,<6.0\n"
        "channels>=4.0\n"
        "daphne>=4.0\n"
        "django-htmx>=1.17\n"
        "django-widget-tweaks>=1.5\n"
        "whitenoise>=6.6\n\n"
        "# Identity and multi-factor authentication\n"
        "django-otp>=1.5\n"
        "django-two-factor-auth>=1.17\n"
        "qrcode>=7.4\n\n"
        "# Reasoning layer (LangChain 1.x phase)\n"
        "langchain>=1.0\n"
        "langchain-core>=1.0\n"
        "langchain-ollama>=1.0\n"
        "pydantic>=2.0\n\n"
        "# Retrieval-augmented generation\n"
        "chromadb\n"
        "llama-index-core\n"
        "llama-index-vector-stores-chroma\n"
        "llama-index-embeddings-huggingface\n"
        "sentence-transformers\n"
        "rank-bm25\n"
        "langchain-text-splitters\n"
        "tiktoken\n\n"
        "# Document loading\n"
        "docling\n"
        "pymupdf\n"
        "python-docx\n"
        "beautifulsoup4\n\n"
        "# Data and export\n"
        "pandas\n"
        "openpyxl\n"
        "reportlab\n"
    )

    add_paragraph(
        doc,
        'Representative Caddyfile for the production '
        'reverse proxy (TLS termination, HSTS preload, WebSocket '
        'upgrade, CDN passthrough).',
        italic=True, color=MUTED, size=10, space_after=2)
    add_code(
        doc,
        "# /etc/caddy/Caddyfile\n"
        "cjpca.example.com {\n"
        "    encode zstd gzip\n\n"
        "    # TLS 1.3 enforced by Caddy default automation.\n"
        "    tls admin@example.com {\n"
        "        protocols tls1.3 tls1.3\n"
        "    }\n\n"
        "    # HSTS preload (1 year, includeSubDomains).\n"
        "    header Strict-Transport-Security \\\n"
        "        \"max-age=31536000; includeSubDomains; preload\"\n"
        "    header X-Frame-Options DENY\n"
        "    header X-Content-Type-Options nosniff\n"
        "    header Referrer-Policy same-origin\n\n"
        "    # WebSocket upgrade for Channels.\n"
        "    @websockets {\n"
        "        header Connection *Upgrade*\n"
        "        header Upgrade websocket\n"
        "    }\n"
        "    reverse_proxy @websockets 127.0.0.1:8001\n\n"
        "    # HTTP routes to Daphne.\n"
        "    reverse_proxy 127.0.0.1:8001\n\n"
        "    # Rate limit unauthenticated POST traffic.\n"
        "    rate_limit {\n"
        "        zone login {\n"
        "            match {\n"
        "                method POST\n"
        "                path /accounts/login/*\n"
        "            }\n"
        "            key {remote_host}\n"
        "            events 10\n"
        "            window 1m\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def write_part_c(doc):
    doc.add_page_break()
    add_heading(doc, 'Part C — Cross-cutting Reference', level=1)

    add_heading(doc, 'C.1 Middleware chain', level=2)
    add_caption(
        doc, 'Table.',
        'CJPCA middleware chain in registration order. Django built-in, '
        'third-party, or CJPCA custom is shown per row.')
    add_table(
        doc,
        headers=['#', 'Middleware', 'Source', 'Role'],
        rows=MIDDLEWARE_CHAIN,
        widths_cm=[0.8, 5.5, 3.2, 7.0],
        body_size=8,
        mono_cols={1},
    )
    add_paragraph(
        doc,
        'Order matters: SecurityMiddleware (HSTS, TLS upgrade) '
        'first; WhiteNoise before GeoFence so static assets stay '
        'cheap; Session before Auth so request.session exists; '
        'OTP after Auth so it can attach a verified device; the '
        'three custom middlewares (Idle, ForcePasswordChange, '
        'ForceMFAEnrollment) after OTP; AxesMiddleware last.',
    )

    add_heading(doc, 'C.2 Management commands', level=2)
    add_caption(
        doc, 'Table.',
        'Django management commands shipped with CJPCA. Run as '
        '`python manage.py <command>`.')
    add_table(
        doc,
        headers=['Command', 'App', 'Purpose', 'Args'],
        rows=MANAGEMENT_COMMANDS,
        widths_cm=[3.8, 1.8, 7.5, 3.4],
        body_size=8,
        mono_cols={0, 3},
    )

    add_heading(doc, 'C.3 Migration history', level=2)
    add_caption(
        doc, 'Table.',
        'Latest migration per app and the schema change it introduced.')
    add_table(
        doc,
        headers=['App', 'Count', 'Latest migration', 'Operation'],
        rows=MIGRATIONS_SUMMARY,
        widths_cm=[2.0, 1.2, 6.8, 6.5],
        body_size=8,
        mono_cols={2},
    )

    add_heading(doc, 'C.4 AuditLog action constants', level=2)
    add_caption(
        doc, 'Table.',
        'Every action constant defined on cjpca/apps/history/audit.py '
        'Actions, grouped by domain.')
    add_table(
        doc,
        headers=['Group', 'Action', 'Trigger'],
        rows=AUDITLOG_ACTIONS,
        widths_cm=[2.5, 4.5, 9.5],
        body_size=8,
        mono_cols={1},
    )

    add_heading(doc, 'C.5 Database schema', level=2)
    add_paragraph(
        doc,
        'The condensed model inventory below names every model class '
        'and its primary fields. Indexes are noted where they exceed '
        'the implicit primary key. Full field lists with type '
        'constraints live in the per-app models.py files.',
    )

    add_heading(doc, 'C.5.1 accounts', level=3)
    add_table(
        doc,
        headers=['Model', 'Primary fields', 'Indexes'],
        rows=[
            ('UserProfile',
             'user (1-to-1 User), role (CharField), require_mfa_setup '
             '(Bool), must_change_password (Bool), created_at, updated_at',
             '1 (user)'),
        ],
        widths_cm=[3.2, 11.0, 2.3],
        body_size=8,
        mono_cols={0},
    )

    add_heading(doc, 'C.5.2 library', level=3)
    add_table(
        doc,
        headers=['Model', 'Primary fields', 'Indexes'],
        rows=[
            ('Document',
             'name, full_name, doc_type, jurisdiction, version, '
             'issuing_authority, effective_date, source_url, notes, '
             'status, upload_date, chunk_count, token_count, file, '
             'tags (JSON), cached_topics (JSON), applicable_sector, '
             'concept_tags_csv (JSON), document_id, parent_regulation',
             '1 (document_id)'),
        ],
        widths_cm=[3.2, 11.0, 2.3],
        body_size=8,
        mono_cols={0},
    )

    add_heading(doc, 'C.5.3 ingestion', level=3)
    add_table(
        doc,
        headers=['Model', 'Primary fields', 'Indexes'],
        rows=[
            ('IngestionJob',
             'document (FK), current_stage, progress_pct, status, '
             'error_message, celery_task_id, log_entries (JSON), '
             'created_by (FK User), created_at, updated_at',
             '1 (status)'),
            ('QuarantinedChunk',
             'job (FK), document (FK), chunk_index, node_id, '
             'section_title, content, rule_id, severity, tier, '
             'rule_description, matched_snippet, judge_reason, '
             'all_detections (JSON), status, decided_by (FK User), '
             'decided_at, decision_note, chunk_metadata (JSON), '
             'created_at',
             '3 (node_id, rule_id, status)'),
        ],
        widths_cm=[3.2, 11.0, 2.3],
        body_size=8,
        mono_cols={0},
    )

    add_heading(doc, 'C.5.4 mapping', level=3)
    add_table(
        doc,
        headers=['Model', 'Primary fields', 'Indexes'],
        rows=[
            ('MappingAnalysis',
             'policy_doc (FK), regulations (M2M), topic, scope_mode, '
             'scope_topics (JSON), scope_article_ids (JSON), '
             'include_asymmetric, status, progress_current, '
             'progress_total, current_obligation_label, '
             'obligation_count, gap_count, run_at, completed_at, '
             'cancelled_at, created_by (FK User), analyst_note, '
             'submitted_for_review_at, submitted_by (FK User)',
             '1 (status)'),
            ('ObligationMapping',
             'analysis (FK), regulation (FK), article_ref, '
             'obligation_title, obligation_text, coverage, confidence, '
             'severity, plus override fields',
             '1 (coverage)'),
            ('Gap',
             'obligation_mapping (FK), description, severity, '
             'remediation_note, assignee (FK User), status, '
             'created_at, updated_at',
             '1 (severity)'),
        ],
        widths_cm=[3.2, 11.0, 2.3],
        body_size=8,
        mono_cols={0},
    )

    add_heading(doc, 'C.5.5 comparison', level=3)
    add_table(
        doc,
        headers=['Model', 'Primary fields', 'Indexes'],
        rows=[
            ('ComparisonRun',
             'reg_a (FK), reg_b (FK), topic, status, created_at, '
             'created_by (FK User), analyst_note, '
             'submitted_for_review_at, submitted_by (FK User), '
             'report_json (JSON)',
             '1 (status)'),
            ('ClausePair',
             'analysis (FK), reg_a_article, reg_b_article, '
             'match_type, similarity_score, ai_analysis',
             'none'),
        ],
        widths_cm=[3.2, 11.0, 2.3],
        body_size=8,
        mono_cols={0},
    )

    add_heading(doc, 'C.5.6 review', level=3)
    add_table(
        doc,
        headers=['Model', 'Primary fields', 'Indexes'],
        rows=[
            ('ReviewItem',
             'mapping (FK), obligation_mapping (FK), status, '
             'reviewer (FK User), reviewed_at, reviewer_note, '
             'created_at',
             'none'),
        ],
        widths_cm=[3.2, 11.0, 2.3],
        body_size=8,
        mono_cols={0},
    )

    add_heading(doc, 'C.5.7 history', level=3)
    add_table(
        doc,
        headers=['Model', 'Primary fields', 'Indexes'],
        rows=[
            ('AuditLog',
             'event_type, user (FK, nullable), user_role_at_time, '
             'ip_address, timestamp (auto_now_add), description, '
             'related_object_type, related_object_id, '
             'change_detail (JSON)',
             '2 (user+event_type, timestamp)'),
        ],
        widths_cm=[3.2, 11.0, 2.3],
        body_size=8,
        mono_cols={0},
    )


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'appendix_3_implementation_v3.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = (out_dir /
                             f'appendix_3_implementation_v3_v{n}.docx')
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
    write_part_a(doc)
    write_part_b(doc)
    write_part_c(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
