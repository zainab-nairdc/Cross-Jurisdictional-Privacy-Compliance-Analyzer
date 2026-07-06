"""Generate Section 3.2.5 Cybersecurity Considerations (Stage 5) as a Word doc.

Output: thesis_docs/3_2_5_cybersecurity.docx

Rubric-aligned structure with complete enumeration of every control:
  3.2.5 Cybersecurity Considerations
    3.2.5.1  Security posture and scope
    3.2.5.2  Defense-in-depth architecture           + Figure 17
    3.2.5.3  Transport, headers, and CSP
    3.2.5.4  Cookies and session integrity
    3.2.5.5  Idle-state and rolling-session controls
    3.2.5.6  Identity, MFA, and brute-force protection
    3.2.5.7  Role-based access control
    3.2.5.8  Input validation, geofence, and outbound restriction
    3.2.5.9  AI-layer safety
    3.2.5.10 Auditability and evidence integrity
    3.2.5.11 Threat model and STRIDE summary         + Figure 18 + Table 10
    3.2.5.12 Security controls mapping               + Figure 19
    3.2.5.13 Forward reference

Word budget: ~700 words main body. Risk register, security policies, and
the detection-flow diagram live in Appendix 2.5.
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


# Table 10 — STRIDE Coverage Summary
STRIDE_ROWS = [
    ('Spoofing',
     'Stolen credentials, impersonated analyst session',
     'TOTP MFA, Secure session cookie, idle timeout, django-axes lockout, '
     'AxesStandaloneBackend ordered before ModelBackend'),
    ('Tampering',
     'Forged mutation of an ObligationMapping or AuditLog row',
     'ORM-only writes, append-only AuditLog with SET_NULL on user delete, '
     'SHA-256 hash chain on export, ALLOWED_HOSTS validation'),
    ('Repudiation',
     'User denies running a mapping job',
     'AuditLog keyed to actor with user_role_at_time snapshot; signals '
     'capture login, logout, login_failed, idle_timeout, and mfa_enrolled'),
    ('Information disclosure',
     'Cross-tenant access to internal BBK policy chunks',
     'Three-role RBAC with per-row created_by filter, CSP frame-ancestors '
     "'none', Secure + HttpOnly cookies, X-Frame DENY, referrer same-origin"),
    ('Denial of service',
     'Saturating job queue or LLM endpoint',
     'Bounded retries (cfg.llm.retry_attempts = 2), SafeFallback, per-job '
     'concurrency, upload size cap'),
    ('Elevation of privilege',
     'Analyst gains reviewer or admin rights',
     'Admin-only role grants, ForceMFAEnrollmentMiddleware, '
     'ForcePasswordChangeMiddleware, audit on every grant'),
]


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
    p.paragraph_format.space_after = Pt(12)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_image(doc, image_path: Path, width_cm: float = 16.0):
    if not image_path.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f'[MISSING IMAGE: {image_path.name}]')
        set_run_style(run, bold=True, italic=True, color=MUTED, size=10)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(image_path), width=Cm(width_cm))


def add_table(doc, headers, rows, widths_cm, body_size=9):
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
            set_run_style(run, bold=True, color=WHITE, size=10)

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
                        color=DARK_GRAY,
                        size=body_size,
                    )


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '3_2_5_cybersecurity.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'3_2_5_cybersecurity_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    diagrams = base / 'diagrams'
    fig_17 = diagrams / 'Figure_17_SecureArchitecture.drawio.png'
    fig_18 = diagrams / 'Figure_18_ThreatModel.drawio.png'
    fig_19 = diagrams / 'Figure_19_ControlsMapping.drawio.png'

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, '3.2.5 Cybersecurity Considerations', level=1)

    # 3.2.5.1 Security posture and scope
    add_heading(doc, '3.2.5.1 Security posture and scope', level=2)
    add_paragraph(
        doc,
        'CJPCA is an internal compliance tool deployed on the BBK '
        'workstation, so the security goal is protection of a sensitive '
        'regulatory corpus, prevention of unauthorised mutation, and full '
        'traceability of every analyst action. Defense in depth is layered '
        'from the perimeter inward, with no single control trusted in '
        'isolation. The posture maps to NFR-10 through NFR-13, NFR-20, '
        'CR-01, CR-08, and CR-09.',
    )

    # 3.2.5.2 Defense-in-depth architecture
    add_heading(doc, '3.2.5.2 Defense-in-depth architecture', level=2)
    add_paragraph(
        doc,
        'Figure 17 shows the six bands of the secure architecture. The '
        'perimeter band carries TLS 1.3 termination, HSTS, and the static '
        'asset allowlist. The edge band layers django-axes lockout, the '
        'GeoFence middleware, the Content Security Policy, CSRF protection, '
        'and the strict response headers. Authentication and authorization '
        'sit underneath, with AI-layer safety as a peer band that protects '
        'the reasoning path. Data integrity sits innermost, covering '
        'ORM-only writes, the append-only audit log, and the SHA-256 '
        'export hash chain.',
    )
    add_image(doc, fig_17, width_cm=15.5)
    add_caption(doc, 'Figure 17.', 'CJPCA Secure Architecture')

    # 3.2.5.3 Transport, headers, and CSP
    add_heading(doc, '3.2.5.3 Transport, headers, and CSP', level=2)
    add_paragraph(
        doc,
        'HTTPS is terminated at the reverse proxy on port 443; in '
        'production SECURE_SSL_REDIRECT forces every HTTP request to '
        'upgrade. HSTS is configured for 31 536 000 s with '
        'includeSubDomains and preload. Django\'s SecurityMiddleware adds '
        'X-Frame-Options DENY (clickjacking), SECURE_CONTENT_TYPE_NOSNIFF '
        '(MIME confusion), SECURE_REFERRER_POLICY of same-origin, and the '
        'legacy XSS filter. ALLOWED_HOSTS is env-controlled to block Host '
        'header injection. The Content Security Policy locks default-src '
        'to self, allowlists script and style sources to specific CDNs '
        '(unpkg, jsdelivr, fontshare), restricts connect-src to self, '
        "sets frame-ancestors to 'none' for clickjacking defence, and "
        'pins form-action and base-uri to self.',
    )

    # 3.2.5.4 Cookies and session integrity
    add_heading(doc, '3.2.5.4 Cookies and session integrity', level=2)
    add_paragraph(
        doc,
        'In production every session and CSRF cookie carries the Secure '
        'and SameSite=Lax flags. SESSION_COOKIE_HTTPONLY is True so '
        'JavaScript cannot read the session identifier. CSRF_COOKIE_HTTPONLY '
        'is intentionally False because the HTMX and Alpine.js layers '
        'must read the CSRF token from document.cookie before each '
        'request; the trade-off is documented in the settings. CSRF '
        'tokens are required on every mutating form, and the '
        'ensure_csrf_cookie decorator guarantees the cookie is set on '
        'first render of the regulations, policies, and viewer pages.',
    )

    # 3.2.5.5 Idle-state and rolling-session controls
    add_heading(doc, '3.2.5.5 Idle-state and rolling-session controls',
                level=2)
    add_paragraph(
        doc,
        'SESSION_COOKIE_AGE caps absolute session lifetime at 28 800 s '
        '(eight hours). SESSION_SAVE_EVERY_REQUEST is True so each '
        'authenticated request resets the rolling timeout, and '
        'SESSION_EXPIRE_AT_BROWSER_CLOSE evicts the cookie when the '
        'browser closes. IdleSessionTimeoutMiddleware tracks a '
        '_last_activity timestamp per request and logs the user out after '
        '1 800 s of inactivity, writing an auth.idle_timeout audit row '
        'with the idle_seconds metadata. A GET-aware logout view accepts '
        'both POST and the redirect-style GET that the idle timeout uses.',
    )

    # 3.2.5.6 Identity, MFA, and brute-force protection
    add_heading(doc, '3.2.5.6 Identity, MFA, and brute-force protection',
                level=2)
    add_paragraph(
        doc,
        'Five password validators run on every credential change: '
        'UserAttributeSimilarityValidator at a stricter 0.5 threshold, '
        'MinimumLengthValidator at twelve characters, CommonPasswordValidator '
        'against the breached-list, NumericPasswordValidator, and a custom '
        'ComplexityValidator that requires upper, lower, digit, and special. '
        'A custom NoUsernameValidator rejects passwords that embed the '
        'username or email (NFR-11). django-axes locks an account after '
        'five failed attempts inside a thirty-minute cool-off keyed to '
        'both IP and username; AXES_RESET_ON_SUCCESS clears the counter '
        'on legitimate login (NFR-12). AxesStandaloneBackend is ordered '
        'before ModelBackend so locked accounts short-circuit the '
        'password check. TOTP is required (REQUIRE_MFA True in '
        'production); ForceMFAEnrollmentMiddleware redirects unenrolled '
        'users to the two-factor setup flow before any other view loads, '
        'and TWO_FACTOR_PATCH_ADMIN enforces 2FA on Django admin as well '
        '(FR-09). ForcePasswordChangeMiddleware runs before the MFA gate '
        'so new accounts must rotate their temporary password first; an '
        'admin-only flow emails the temporary password on creation or '
        'reset.',
    )

    # 3.2.5.7 Role-based access control
    add_heading(doc, '3.2.5.7 Role-based access control', level=2)
    add_paragraph(
        doc,
        'UserProfile.role carries one of three values (analyst, reviewer, '
        'admin) and defaults to analyst via the ensure_user_profile '
        'signal on user creation (FR-10). The @role_required decorator '
        'and RoleRequiredMixin gate every view and return '
        'HttpResponseForbidden 403 on mismatch. Admin views include user '
        'management, document upload and delete, the ingestion widget, '
        'and the quarantine queue. Object-level access uses a created_by '
        'filter on MappingAnalysis and ComparisonRun so analysts see '
        'only their own work, while reviewer and admin roles see the '
        'full scope.',
    )

    # 3.2.5.8 Input validation, geofence, and outbound restriction
    add_heading(doc,
                '3.2.5.8 Input validation, geofence, and outbound restriction',
                level=2)
    add_paragraph(
        doc,
        'Document uploads are admin-only, restricted to PDF and DOCX, and '
        'are content-hashed with SHA-256 for deduplication; the upload '
        'size is capped by DATA_UPLOAD_MAX_MEMORY_SIZE. Templates use '
        'Django\'s autoescape by default and mark_safe is not used on '
        'user-supplied content. The ORM and Pydantic v2 schemas cover '
        'database and API input validation. GeoFenceMiddleware consults '
        'a MaxMind GeoLite2 database (with double-checked locking) and '
        'returns 403 if the source country is not in the env-controlled '
        'allowlist (default Bahrain, India, Kuwait, United Arab '
        'Emirates); private and loopback addresses always pass, and the '
        'middleware fails open if the database is unavailable to avoid '
        'locking the BBK network out. Outbound traffic is restricted to '
        'the configured LLM endpoint and the static-asset CDN allowlist '
        '(NFR-13).',
    )

    # 3.2.5.9 AI-layer safety
    add_heading(doc, '3.2.5.9 AI-layer safety', level=2)
    add_paragraph(
        doc,
        'The reasoning path treats every document chunk as untrusted '
        'input. A Tier-A deterministic regex scanner applies nine rule '
        'groups for instruction override, role hijack, forced verdict, '
        'safety bypass, developer-mode trigger, prompt leak, fake '
        'delimiter, base64 blob, and suspicious URL. A Tier-B LLM judge '
        'then classifies each chunk and fails closed on classifier '
        'error, routing flagged chunks to the QuarantinedChunk table for '
        'admin review (approve releases the chunk to Chroma and FTS5; '
        'reject permanently holds it). Pydantic v2 schemas reject '
        'malformed output and OutputFixingParser retries are bounded at '
        'two attempts before SafeFallback returns a typed empty report. '
        'The citation verifier requires verbatim grounding and the '
        'cross-encoder NLI hallucination score drops rows above the '
        'configured threshold using a MAX-across-chunks aggregation. The '
        'UI banner discloses AI involvement per CR-09.',
    )

    # 3.2.5.10 Auditability and evidence integrity
    add_heading(doc, '3.2.5.10 Auditability and evidence integrity', level=2)
    add_paragraph(
        doc,
        'Every mutating action is signalled to log_event, which writes an '
        'AuditLog row carrying twenty-eight action constants and a '
        'user_role_at_time snapshot so the historical role survives '
        'later role changes (NFR-20, FR-12). The user foreign key uses '
        'SET_NULL so audit rows survive user deletion. The table is '
        'append-only at the application layer with no UI to edit or '
        'delete rows, and composite indexes on (user, -timestamp) and '
        '(event_type, -timestamp) keep compliance queries fast. Audit '
        'writes are best-effort: failures are logged at warning level '
        'and never raise into the user flow. Signal handlers '
        'automatically capture auth.login, auth.logout, '
        'auth.login_failed (with the attempted_username for anonymous '
        'attempts), auth.idle_timeout, and auth.mfa_enrolled. PDF and '
        'XLSX exports carry a SHA-256 prefix chained over row identity '
        'fields so post-hoc tampering is detectable (CR-08); per-job '
        'structured log files (logs/run_<job>_<id>.log) capture full '
        'traceback context (CR-01).',
    )

    # 3.2.5.11 Threat model and STRIDE summary
    add_heading(doc, '3.2.5.11 Threat model and STRIDE summary', level=2)
    add_paragraph(
        doc,
        'Figure 18 shows the data-flow diagram with four trust zones '
        '(Internet, Perimeter, Application, Third-Party LLM) and STRIDE '
        'chips marking the threat classes introduced at each boundary '
        'crossing. Table 10 summarises the mitigation per STRIDE class; '
        'the full threat model with assets, actors, and trust boundaries '
        'is given in §5.1.',
    )
    add_image(doc, fig_18, width_cm=15.5)
    add_caption(doc, 'Figure 18.', 'CJPCA Threat Model')
    add_caption(doc, 'Table 10.', 'STRIDE Coverage Summary')
    add_table(
        doc,
        ['STRIDE class', 'CJPCA-specific threat', 'Mitigation control'],
        STRIDE_ROWS,
        widths_cm=[3.0, 5.0, 8.5],
    )

    # 3.2.5.12 Security controls mapping
    add_heading(doc, '3.2.5.12 Security controls mapping', level=2)
    add_paragraph(
        doc,
        'Figure 19 groups every control by category (IAM, network and '
        'edge, AI safety, data integrity and audit) and lists the '
        'component that enforces it. This is the protection inventory '
        'referenced by the risk register in Appendix 2.5.',
    )
    add_image(doc, fig_19, width_cm=15.5)
    add_caption(doc, 'Figure 19.', 'Security Controls Mapping')

    # 3.2.5.13 Forward reference
    add_heading(doc, '3.2.5.13 Forward reference', level=2)
    add_paragraph(
        doc,
        'Chapter 5 carries the full risk register, OWASP and OWASP-LLM '
        'mapping, secure-development practices, and incident-response '
        'readiness. Appendix 2.5 holds the risk assessment table, the '
        'security policies, and the detection-flow diagram.',
    )

    doc.save(out_path)
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
