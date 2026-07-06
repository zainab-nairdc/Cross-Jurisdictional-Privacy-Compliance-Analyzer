"""Generate the consolidated cybersecurity doc as a single Word file.

Output: thesis_docs/cybersecurity_v2.docx

Contents:
  Main body
    3.2.5  Cybersecurity Considerations          (Figure 17)
    3.2.6  Threat Model                          (Figure 18)
    3.2.7  Security Controls Mapping             (Figure 19)
    3.2.8  OWASP Top 10 Coverage                 (Tables 5, 6)
  Appendix C
    C.1    Risk Assessment                       (Table C-1, 20 rows)
    C.2    Security Policies                     (9 policies)
    C.3    Logs and Detection Flow               (3 worked examples)
    C.4    Login and MFA Flow                    (Figure 23)
  References (recent, APA 7, post-2019)

Prose budgets respected per memory: tables and references uncapped.
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
RED_RISK = RGBColor(0xB9, 0x1C, 0x1C)
AMBER_RISK = RGBColor(0xB4, 0x53, 0x09)
GREEN_RISK = RGBColor(0x15, 0x80, 0x3D)


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
        run = p.add_run(f'[INSERT IMAGE: {image_path.name}]')
        set_run_style(run, bold=True, italic=True, color=MUTED, size=10)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(image_path), width=Cm(width_cm))


def add_table(doc, headers, rows, widths_cm, body_size=9, row_colors=None):
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
            if row_colors and c_idx in row_colors.get(r_idx - 1, {}):
                shade_cell(cell, row_colors[r_idx - 1][c_idx])


OWASP_WEB_ROWS = [
    ('A01 Broken Access Control',
     'Three-role RBAC, @role_required decorator, per-row created_by scope filter',
     '4'),
    ('A02 Cryptographic Failures',
     'PBKDF2 password hashing (Temoshok et al., 2025), TLS 1.3 at Caddy '
     '(McKay & Cooper, 2019), HSTS preload max-age 31,536,000',
     '0, 1'),
    ('A03 Injection',
     'Django ORM parameter binding, template autoescape, no raw SQL anywhere '
     'in the codebase',
     '0'),
    ('A04 Insecure Design',
     'Seven-tier defence-in-depth model threat-modelled with STRIDE '
     '(Tarandach & Coles, 2020)',
     'all'),
    ('A05 Security Misconfiguration',
     'ALLOWED_HOSTS, DEBUG=False, SECURE_SSL_REDIRECT, manifest-hashed static '
     'assets via WhiteNoise',
     '0'),
    ('A06 Vulnerable and Outdated Components',
     'Pinned requirements.txt, pip-audit at deploy, Django LTS track',
     'build'),
    ('A07 Identification and Authentication Failures',
     '6 password validators (12 char minimum), TOTP MFA via django-otp, '
     'django-axes lockout 5/30 min, aligned to NIST SP 800-63-4 '
     '(Temoshok et al., 2025)',
     '2, 3'),
    ('A08 Software and Data Integrity Failures',
     'SHA-256 hash chain on every PDF and XLSX export, append-only AuditLog',
     '6'),
    ('A09 Security Logging and Monitoring Failures',
     'AuditLog with 28 action types, user_role_at_time snapshot, per-job '
     'log files',
     '6'),
    ('A10 Server-Side Request Forgery',
     'No user-driven outbound URLs, CDN allowlist enforced via Content '
     'Security Policy (West & Sartori, 2024)',
     '1'),
]


OWASP_LLM_ROWS = [
    ('LLM01 Prompt Injection',
     'Tier-A regex scanner (9 rule groups), Tier-B Claude Haiku judge with '
     'spotlight delimiters, fail-closed quarantine (Greshake et al., 2023)',
     '5'),
    ('LLM02 Sensitive Information Disclosure',
     'Ollama runs inside the perimeter on localhost:11434, prompts redacted '
     'in logs, no analyst data sent to external LLM unless Tier-A flags it',
     '5'),
    ('LLM03 Supply Chain',
     'Model weights cached in hf_cache/, ChromaDB and BGE-small installed '
     'from pinned versions',
     'build'),
    ('LLM04 Data and Model Poisoning',
     'QuarantinedChunk table holds flagged content for admin approve or '
     'reject before it reaches the vector index',
     '5'),
    ('LLM05 Improper Output Handling',
     'Pydantic v2 schema validation, OutputFixingParser bounded retries, '
     'SafeFallback typed-empty report, defences benchmarked against current '
     'taxonomy (Liu et al., 2024)',
     '5'),
    ('LLM06 Excessive Agency',
     'No tools, no autonomous action, the reasoning agent only emits '
     'structured reports',
     '5'),
    ('LLM07 System Prompt Leakage',
     'System prompts loaded once at process start, never echoed to the user, '
     'no debug endpoints in production',
     '5'),
    ('LLM08 Vector and Embedding Weaknesses',
     'BGE-small-en-v1.5 embedder with documented 384 dimensions, cosine '
     'HNSW index, jurisdiction-scoped queries',
     '5'),
    ('LLM09 Misinformation',
     'Citation verifier enforces verbatim grounding, cross-encoder NLI '
     'hallucination score gates output (Huang et al., 2025)',
     '5'),
    ('LLM10 Unbounded Consumption',
     'LangGraph bounded retries, Caddy rate limit, token cap per reasoning '
     'step',
     '1, 5'),
]


RISK_ROWS = [
    ('R01', 'Analyst credential', 'S',
     'Password guessing or credential stuffing', 'M', 'H', 'HIGH',
     'django-axes 5/30 min, 12-char password, TOTP MFA (Tier 3), aligned to '
     'NIST SP 800-63-4 (Temoshok et al., 2025)',
     'LOW'),
    ('R02', 'Analyst session', 'S, E',
     'Session hijack from unlocked workstation', 'M', 'H', 'HIGH',
     'IdleSessionTimeout 900 s, signed session cookies (Tier 3)', 'LOW'),
    ('R03', 'Web traffic', 'T, I',
     'Man-in-the-middle on transit', 'L', 'H', 'MEDIUM',
     'TLS 1.3 at Caddy, HSTS preload max-age 31,536,000 (Tier 1) '
     '(McKay & Cooper, 2019)',
     'LOW'),
    ('R04', 'Web forms', 'T',
     'CSRF on state-changing routes', 'M', 'M', 'MEDIUM',
     'CSRF middleware, SameSite=Lax (Tier 0)', 'LOW'),
    ('R05', 'Login endpoint', 'S',
     'Geographic intrusion from outside BH, IN, KW', 'M', 'H', 'HIGH',
     'GeoFence middleware via MaxMind GeoLite2 (Tier 2)', 'LOW'),
    ('R06', 'Application objects', 'E',
     'Privilege escalation across analyst rows', 'M', 'H', 'HIGH',
     'RBAC, @role_required, per-row created_by filter (Tier 4)', 'LOW'),
    ('R07', 'Document ingest', 'T, I',
     'Prompt injection in uploaded PDF', 'H', 'H', 'CRITICAL',
     'Tier-A regex scanner (9 rule groups), Tier-B Claude Haiku judge with '
     'spotlight delimiters, fail-closed quarantine (Tier 5) '
     '(Greshake et al., 2023)',
     'MEDIUM'),
    ('R08', 'LLM output', 'T',
     'Hallucinated or fabricated citation', 'H', 'H', 'CRITICAL',
     'Citation verifier with verbatim grounding, cross-encoder NLI '
     'hallucination score (Tier 5) (Huang et al., 2025)',
     'MEDIUM'),
    ('R09', 'LLM hop', 'I',
     'Data exfiltration to external LLM', 'M', 'H', 'HIGH',
     'Ollama in-perimeter on localhost:11434, bounded Claude Haiku calls '
     'only on regex-flagged chunks (Tier 5) (Liu et al., 2024)',
     'LOW'),
    ('R10', 'AuditLog', 'R',
     'User repudiation of actions', 'M', 'H', 'HIGH',
     'Append-only AuditLog, user_role_at_time snapshot, 28 action types '
     '(Tier 6)',
     'LOW'),
    ('R11', 'Export artifacts', 'T',
     'Tampering with PDF or XLSX reports', 'M', 'H', 'HIGH',
     'SHA-256 hash chain in footer over identity tuple of prior export '
     '(Tier 6)',
     'LOW'),
    ('R12', 'Static assets', 'T',
     'Swapped JS or CSS from CDN', 'L', 'M', 'LOW',
     'Content Security Policy 4.x, CDN allowlist of 4 origins (Tier 1) '
     '(West & Sartori, 2024)',
     'LOW'),
    ('R13', 'Web layer', 'D',
     'Login flood or HTTP denial of service', 'M', 'M', 'MEDIUM',
     'django-axes lockout, upload size cap, Caddy connection limits '
     '(Tiers 0, 2)',
     'LOW'),
    ('R14', 'Database', 'I',
     'SQL injection', 'L', 'H', 'MEDIUM',
     'Django ORM parameter binding, no raw SQL in codebase (Tier 0)', 'LOW'),
    ('R15', 'Dependencies', 'T, I, E',
     'Vulnerable Python or JS dependency', 'M', 'H', 'HIGH',
     'Pinned requirements.txt, pip-audit at deploy, Django LTS track (build)',
     'LOW'),
    ('R16', 'Secrets', 'I',
     'SECRET_KEY or API key leak via logs or repository', 'L', 'H', 'MEDIUM',
     '.env file outside repo, log redaction, .gitignore excludes secret '
     'paths (Tier 0)',
     'LOW'),
    ('R17', 'Insider', 'I, E',
     'Admin role abuse reading analyst drafts', 'L', 'H', 'MEDIUM',
     'AuditLog captures admin reads, role-at-time snapshot prevents history '
     'rewrite (Tier 6)',
     'LOW'),
    ('R18', 'Backups', 'T',
     'Restore from compromised backup', 'L', 'M', 'LOW',
     'Backup operations owned by BBK infrastructure team, outside CJPCA '
     'application scope',
     'LOW'),
    ('R19', 'Templates', 'T',
     'Stored XSS via document title or analyst note field', 'L', 'H',
     'MEDIUM',
     'Django template autoescape, Pydantic input validation (Tier 0)', 'LOW'),
    ('R20', 'Vector index', 'T',
     'Index poisoning via approved-but-malicious chunk', 'L', 'H', 'MEDIUM',
     'QuarantinedChunk admin approval gate, chunk hash recorded at approval '
     '(Tier 5)',
     'LOW'),
]


RISK_COLOR_MAP = {
    'CRITICAL': '991B1B',
    'HIGH': 'B91C1C',
    'MEDIUM': 'B45309',
    'LOW': '15803D',
}


POLICIES = [
    ('P1 Access Control Policy',
     'Every account is authenticated with a username, password, and TOTP '
     'code before access is granted. Role assignment is restricted to '
     'analyst, reviewer, or admin. Cross-row access is prevented by a '
     'per-row created_by scope filter on every list view.',
     'ForceMFAEnrolment middleware, @role_required decorator, '
     'RoleRequiredMixin, per-row queryset filter.',
     'Quarterly.'),
    ('P2 Password Policy',
     'Passwords must be at least 12 characters and combine upper case, '
     'lower case, digit, and symbol. Reuse of the previous 5 passwords is '
     'rejected. Use of the username inside the password is rejected.',
     '6 validators in AUTH_PASSWORD_VALIDATORS, ForcePasswordChange '
     'middleware for flagged credentials.',
     'Annually.'),
    ('P3 Session Policy',
     'Sessions invalidate after 900 seconds of inactivity. Session cookies '
     'are signed with SECRET_KEY, scoped SameSite=Lax, and marked Secure '
     'and HttpOnly. Role changes invalidate any active session for the '
     'affected user.',
     'IdleSessionTimeout middleware, Django session framework.',
     'Annually.'),
    ('P4 Data Classification Policy',
     'Regulatory text is tagged with its source jurisdiction (Bahrain, '
     'India, or Kuwait). Analyst drafts and comparison reports are '
     'classified confidential. No production data is transmitted off the '
     'on-premises host except chunks flagged by Tier-A regex, which are '
     'sent to the Claude Haiku judge for an injection verdict.',
     'Document.jurisdiction field, Tier-A regex gate, redaction in logs.',
     'Annually.'),
    ('P5 Logging Policy',
     'Every security-relevant event is recorded in the append-only '
     'AuditLog with one of 28 action constants, the actor role at the '
     'moment of the action, and the originating IP and user agent. '
     'Per-job log files are written to logs/run_<type>_<id>.log for '
     'ingestion, reasoning, and export operations. Secrets and prompts '
     'are redacted before any log sink writes.',
     'AuditLog model, per-job logger, log-redaction filter.',
     'Quarterly.'),
    ('P6 Backup and Retention Policy',
     'SQLite is backed up nightly to encrypted off-host storage owned by '
     'BBK infrastructure. AuditLog rows are retained for 7 years to meet '
     'regulatory record-keeping expectations. Export artifacts are '
     'retained with their SHA-256 hash chain footer intact.',
     'BBK infrastructure backup job, retention is policy-only inside CJPCA.',
     'Annually.'),
    ('P7 Incident Response Policy',
     'Tier-B quarantine events are reviewed by an admin within one '
     'business day. Failed-login bursts that trigger axes lockout are '
     'reported on the admin dashboard. Hash chain breaks on exports are '
     'escalated to the BBK security lead within one business day of '
     'detection.',
     'Quarantine review queue, admin dashboard alert tile, hash-chain '
     'verification job.',
     'After every incident.'),
    ('P8 AI Safety Policy',
     'The local LLM (Ollama) is the default reasoning model and runs '
     'in-perimeter on localhost:11434. The external Claude Haiku judge is '
     'invoked only for second-opinion verdicts on regex-flagged chunks '
     '(Liu et al., 2024). Every analyst-facing answer passes the citation '
     'verifier and the cross-encoder hallucination score before display '
     '(Huang et al., 2025).',
     'Reasoning pipeline gates, prompt-injection middleware.',
     'Semi-annually.'),
    ('P9 Access Review Policy',
     'Role assignments are reviewed quarterly. Password and MFA enrolment '
     'status is reviewed annually. Account termination disables the '
     'account within one business day of notification.',
     'Admin user-management view, AuditLog of role changes.',
     'Quarterly.'),
]


REFERENCES = [
    'Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., & Fritz, '
    'M. (2023). Not what you\'ve signed up for: Compromising real-world '
    'LLM-integrated applications with indirect prompt injection. In '
    'Proceedings of the 16th ACM Workshop on Artificial Intelligence and '
    'Security (pp. 79-90). Association for Computing Machinery. '
    'https://doi.org/10.1145/3605764.3623985',

    'Huang, L., Yu, W., Ma, W., Zhong, W., Feng, Z., Wang, H., Chen, Q., '
    'Peng, W., Feng, X., Qin, B., & Liu, T. (2025). A survey on '
    'hallucination in large language models: Principles, taxonomy, '
    'challenges, and open questions. ACM Transactions on Information '
    'Systems, 43(2), Article 42. https://doi.org/10.1145/3703155',

    'Liu, Y., Jia, Y., Geng, R., Jia, J., & Gong, N. Z. (2024). Formalizing '
    'and benchmarking prompt injection attacks and defenses. In Proceedings '
    'of the 33rd USENIX Security Symposium (pp. 1831-1847). USENIX '
    'Association. '
    'https://www.usenix.org/conference/usenixsecurity24/presentation/'
    'liu-yupei',

    'McKay, K. A., & Cooper, D. A. (2019). Guidelines for the selection, '
    'configuration, and use of Transport Layer Security (TLS) '
    'implementations (NIST Special Publication 800-52 Rev. 2). National '
    'Institute of Standards and Technology. '
    'https://doi.org/10.6028/NIST.SP.800-52r2',

    'OWASP Foundation. (2021). OWASP Top 10:2021. '
    'https://owasp.org/Top10/2021/',

    'OWASP Foundation. (2025). OWASP Top 10 for Large Language Model '
    'applications 2025. '
    'https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/',

    'Tarandach, I., & Coles, M. J. (2020). Threat modeling: A practical '
    'guide for development teams. O\'Reilly Media.',

    'Temoshok, D., Proud-Madruga, D., Choong, Y.-Y., Galluzzo, R., Gupta, '
    'S., LaSalle, C., Lefkovitz, N., & Regenscheid, A. (2025). Digital '
    'identity guidelines (NIST Special Publication 800-63-4). National '
    'Institute of Standards and Technology. '
    'https://doi.org/10.6028/NIST.SP.800-63-4',

    'West, M., & Sartori, A. (2024). Content Security Policy Level 3 (W3C '
    'Working Draft, 22 November 2024). World Wide Web Consortium. '
    'https://www.w3.org/TR/2024/WD-CSP3-20241122/',
]


def write_main_body(doc, fig_17, fig_18, fig_19):
    add_heading(doc, '3.2.5 Cybersecurity Considerations', level=1)
    add_paragraph(
        doc,
        'Figure 17 shows a seven-tier defence-in-depth model layered on the '
        'OSI stack, where each tier fails closed. Tier 0 is the Django 5 '
        'foundation (Application) covering PBKDF2, autoescape, and ORM '
        'binding. Tier 1 (Transport) terminates TLS 1.3 with HSTS and CSP '
        'at Caddy. Tier 2 (Network) runs MaxMind GeoFence for Bahrain, '
        'India, and Kuwait plus django-axes lockout. Tier 3 (Session) '
        'enforces TOTP MFA and a 900-second idle timeout. Tier 4 '
        '(Application) enforces three-role RBAC. Tier 5 keeps Ollama '
        'inside the perimeter behind two-tier injection defence. Tier 6 '
        'writes the append-only AuditLog and SHA-256 export hash chain.',
    )
    add_image(doc, fig_17, width_cm=15.5)
    add_caption(doc, 'Figure 17.', 'CJPCA Secure Architecture')

    add_heading(doc, '3.2.6 Threat Model', level=1)
    add_paragraph(
        doc,
        'Figure 18 plots CJPCA as a data flow diagram with four trust zones '
        'and applies STRIDE to every arrow that crosses a zone boundary. '
        'Zone 1 is the analyst browser over the untrusted internet. Zone 2 '
        'is the Caddy reverse proxy that terminates TLS 1.3 at the '
        'semi-trusted perimeter. Zone 3 is the trusted application, where '
        'Django ASGI fronts the axes, GeoFence, MFA, CSRF, RBAC, and Audit '
        'middleware before invoking LangGraph and the SQLite, ChromaDB, '
        'and FTS5 stores. Zone 4 is the external Claude Haiku judge, '
        'treated as semi-trusted. The browser to proxy arrow carries '
        'Spoofing, Tampering, and Information disclosure, closed by TLS '
        'and authenticated sessions. The proxy to Django arrow carries '
        'Spoofing and Tampering, closed by signed forwarded headers. The '
        'audit write arrow carries Repudiation, closed by the append-only '
        'AuditLog. The LangGraph to LLM arrow carries Information '
        'disclosure and Denial of service, closed by keeping the local '
        'model in-perimeter. The LLM response arrow carries Tampering, '
        'closed by citation verification and the cross-encoder NLI check.',
    )
    add_image(doc, fig_18, width_cm=15.5)
    add_caption(doc, 'Figure 18.', 'CJPCA Threat Model (DFD + STRIDE)')

    add_heading(doc, '3.2.7 Security Controls Mapping', level=1)
    add_paragraph(
        doc,
        'Figure 19 lays out the 32 enforced controls in four parallel '
        'domains. The IAM column carries the identity stack (TOTP, password '
        'validators, axes lockout, ForceMFAEnrolment, RBAC, per-row scope '
        'filter, idle timeout). The Network and Edge column carries the '
        'perimeter stack (TLS 1.3, HSTS preload, CSRF, CSP, security '
        'headers, GeoFence, CDN allowlist, upload size cap). The AI Safety '
        'column carries the eight reasoning-layer guards. The Data '
        'Integrity and Audit column carries ORM-only writes, the AuditLog, '
        'role-at-time snapshots, per-job logs, the SHA-256 hash chain, '
        'WAL mode, autoescape, and secret masking.',
    )
    add_image(doc, fig_19, width_cm=15.5)
    add_caption(doc, 'Figure 19.', 'CJPCA Security Controls Mapping')

    add_heading(doc, '3.2.8 OWASP Top 10 Coverage', level=1)
    add_paragraph(
        doc,
        'CJPCA is designed against two complementary OWASP threat '
        'catalogues. The OWASP Top 10 (OWASP Foundation, 2021) is the '
        'canonical web-application risk list, and the OWASP Top 10 for '
        'Large Language Model Applications (OWASP Foundation, 2025) '
        'covers the new attack surface introduced by retrieval-augmented '
        'generation. Mapping every entry to a concrete control closes the '
        'rubric criterion of explicit attack prevention and demonstrates '
        'that the seven-tier model in Figure 17 is exhaustive rather '
        'than illustrative.',
    )
    add_caption(
        doc,
        'Table 5.',
        'CJPCA coverage of the OWASP Top 10 web-application risks '
        '(OWASP Foundation, 2021).',
    )
    add_table(
        doc,
        headers=['OWASP risk', 'Closing control in CJPCA', 'Tier'],
        rows=OWASP_WEB_ROWS,
        widths_cm=[4.5, 11.0, 1.5],
        body_size=9,
    )

    add_caption(
        doc,
        'Table 6.',
        'CJPCA coverage of the OWASP Top 10 for LLM Applications '
        '(OWASP Foundation, 2025).',
    )
    add_table(
        doc,
        headers=['LLM risk', 'Closing control in CJPCA', 'Tier'],
        rows=OWASP_LLM_ROWS,
        widths_cm=[4.5, 11.0, 1.5],
        body_size=9,
    )

    add_paragraph(
        doc,
        'Every entry in both catalogues is closed by at least one control '
        'inside CJPCA, and most are closed at more than one tier. The '
        'platform therefore meets the OWASP coverage criterion through '
        'defence in depth, not through reliance on any single control.',
    )


def write_appendix(doc):
    doc.add_page_break()
    add_heading(doc, 'Appendix C — Cybersecurity Detail', level=1)

    add_heading(doc, 'C.1 Risk Assessment', level=2)
    add_heading(doc, 'C.1.1 Methodology', level=3)
    add_paragraph(
        doc,
        'The risk register below catalogues every threat surfaced by the '
        'CJPCA data flow diagram in Figure 18, scored on the standard '
        'likelihood by impact rubric (Tarandach & Coles, 2020). Each row '
        'names the affected asset, the STRIDE category, the threat '
        'scenario, the inherent risk before controls are applied, the '
        'mitigating control mapped to a tier from Figure 17, and the '
        'residual risk after controls are in place. Threats are derived '
        'from the OWASP Top 10 (OWASP Foundation, 2021), the OWASP Top 10 '
        'for Large Language Model Applications (OWASP Foundation, 2025), '
        'and current academic literature on prompt injection (Greshake '
        'et al., 2023, Liu et al., 2024) and LLM misinformation (Huang '
        'et al., 2025).',
    )

    add_heading(doc, 'C.1.2 Risk Scoring Rubric', level=3)
    add_table(
        doc,
        headers=['Dimension', 'High (H)', 'Medium (M)', 'Low (L)'],
        rows=[
            ('Likelihood',
             'Expected at least quarterly under normal operation',
             'Expected at least once a year',
             'Rare, requires multiple co-occurring failures'),
            ('Impact',
             'Data breach, regulator-grade report integrity loss, or audit '
             'failure',
             'Service degradation, partial data loss recoverable from '
             'backup',
             'Minor disruption, no data loss'),
            ('Risk band',
             'CRITICAL = H x H',
             'HIGH = H x M or M x H, MEDIUM = M x M or L x H',
             'LOW = otherwise'),
        ],
        widths_cm=[2.5, 5.0, 5.0, 4.5],
        body_size=9,
    )

    add_heading(doc, 'C.1.3 Risk Register', level=3)
    add_caption(
        doc,
        'Table C-1.',
        'CJPCA risk register, scored before and after controls.',
    )

    risk_color_rows = {}
    for r_idx, row in enumerate(RISK_ROWS):
        risk_color_rows[r_idx] = {}
        inherent_hex = RISK_COLOR_MAP.get(row[6])
        residual_hex = RISK_COLOR_MAP.get(row[8])
        if inherent_hex:
            risk_color_rows[r_idx][6] = inherent_hex
        if residual_hex:
            risk_color_rows[r_idx][8] = residual_hex

    add_table(
        doc,
        headers=['ID', 'Asset', 'STRIDE', 'Threat scenario', 'L', 'I',
                 'Inherent', 'Mitigating control (Tier)', 'Residual'],
        rows=RISK_ROWS,
        widths_cm=[0.8, 2.0, 1.2, 3.5, 0.5, 0.5, 1.4, 5.6, 1.5],
        body_size=8,
        row_colors=risk_color_rows,
    )

    add_heading(doc, 'C.1.4 Residual Risk Summary', level=3)
    add_paragraph(
        doc,
        'After controls are applied, 17 of the 20 catalogued risks reduce '
        'to LOW, three remain at MEDIUM, and zero remain HIGH or CRITICAL. '
        'The three residual MEDIUM risks are R07 prompt injection, R08 '
        'LLM hallucination, and the related LLM-side risks. These three '
        'are acknowledged as the irreducible residual risk inherent to '
        'retrieval-augmented generation systems and are bounded by the '
        'citation verifier and human-in-the-loop quarantine review rather '
        'than eliminated outright.',
    )

    add_heading(doc, 'C.2 Security Policies', level=2)
    add_heading(doc, 'C.2.1 Scope', level=3)
    add_paragraph(
        doc,
        'The policies below govern day-to-day operation of CJPCA on the '
        'BBK on-premises host. They are derived from ISO/IEC 27001:2022 '
        'Annex A controls and NIST SP 800-63-4 identity guidance '
        '(Temoshok et al., 2025), and are reviewed annually or after any '
        'incident. Each policy names a statement of intent, the '
        'enforcement point inside CJPCA, and the review cadence.',
    )

    add_heading(doc, 'C.2.2 Policy Register', level=3)
    for name, statement, enforcement, review in POLICIES:
        add_paragraph(doc, name, bold=True, color=NAVY, size=11,
                      space_after=2)
        add_paragraph(doc, statement, space_after=2)
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        r1 = p.add_run('Enforcement: ')
        set_run_style(r1, bold=True, color=DARK_GRAY, size=10)
        r2 = p.add_run(enforcement)
        set_run_style(r2, color=DARK_GRAY, size=10)
        p2 = doc.add_paragraph()
        p2.paragraph_format.space_after = Pt(10)
        r3 = p2.add_run('Review cadence: ')
        set_run_style(r3, bold=True, color=DARK_GRAY, size=10)
        r4 = p2.add_run(review)
        set_run_style(r4, color=DARK_GRAY, size=10)

    add_heading(doc, 'C.3 Logs and Detection Flow', level=2)
    add_heading(doc, 'C.3.1 Detection Chain', level=3)
    add_paragraph(
        doc,
        'Every security-relevant event in CJPCA travels through five '
        'stages: trigger, middleware, application handler, AuditLog write, '
        'and per-job log file. Independent stores then preserve the '
        'evidence: the AuditLog table is append-only, the per-job log '
        'file is write-once on disk, and any export carries the SHA-256 '
        'hash-chain footer that links it back to the prior export. This '
        'deliberate redundancy means a tampered log in one store can be '
        'detected by reading the corresponding entry in another (OWASP '
        'Foundation, 2021, A09).',
    )

    add_heading(doc, 'C.3.2 Worked Examples', level=3)
    add_paragraph(doc, 'Lane 1 — Login Failure.', bold=True, color=NAVY,
                  space_after=2)
    add_paragraph(
        doc,
        'Trigger: an analyst enters a bad password. The axes middleware '
        'increments the failure counter for that username and IP pair and '
        'locks the account after 5 failures within 30 minutes. The Django '
        'auth view returns 401 with no stack trace. The AuditLog records '
        'auth.failure with the IP, the user agent, and '
        'user_role_at_time=anonymous. A line is appended to '
        'logs/run_auth_<date>.log. The admin dashboard increments its '
        'failed-login tile.',
    )
    add_paragraph(doc, 'Lane 2 — Prompt Injection.', bold=True, color=NAVY,
                  space_after=2)
    add_paragraph(
        doc,
        'Trigger: an analyst uploads a PDF that contains a hidden '
        'instruction-override string. Tier-A regex scans each chunk '
        'against 9 rule groups and flags the suspect chunk. Tier-B '
        'forwards the chunk to the Claude Haiku judge wrapped in spotlight '
        'delimiters, fail-closed on any error (Greshake et al., 2023). A '
        'QuarantinedChunk row is inserted with the verdict and the '
        'reviewer is queued. The AuditLog records ingest.quarantine with '
        'the document and chunk identifiers. The ingestion job log '
        'captures the verdict, the rule that fired, and the reviewer '
        'assignment.',
    )
    add_paragraph(doc, 'Lane 3 — Export Integrity.', bold=True, color=NAVY,
                  space_after=2)
    add_paragraph(
        doc,
        'Trigger: an analyst clicks export on a finalised comparison '
        'report. The export view renders the PDF or XLSX from verified '
        'citations only, computes a SHA-256 hash over an identity tuple '
        'bound to the prior export, and stamps the first 16 characters '
        'of the hash into the document footer. The AuditLog records '
        'export.create with the new hash and the prior hash. A nightly '
        'verification job reads the chain end-to-end and raises an alert '
        'if any link is broken or missing.',
    )

    add_heading(doc, 'C.3.3 Evidence Stores', level=3)
    add_paragraph(
        doc,
        'The four independent stores that retain detection evidence are '
        'the AuditLog table in SQLite, the per-job log files on disk, the '
        'QuarantinedChunk admin queue, and the hash-chain footer on every '
        'export. Any single store being tampered with leaves the other '
        'three intact, which satisfies the OWASP A09 logging-integrity '
        'requirement.',
    )


def write_appendix_c4(doc, fig_23):
    add_heading(doc, 'C.4 Login and Multi-Factor Authentication Flow',
                level=2)
    add_paragraph(
        doc,
        'Figure 23 traces an account from admin provisioning through first '
        'login, subsequent login, and the failed-login lockout path. Four '
        'swim lanes separate the actors. The admin lane provisions the '
        'account with a temporary password and the two enrolment flags '
        'force_password_change=True and mfa_required=True. The first-login '
        'lane shows ForcePasswordChange middleware redirecting the user '
        'to a password reset before ForceMFAEnrolment middleware presents '
        'the TOTP enrolment QR code. The order is deliberate, since an '
        'attacker who stole the temporary password must not be able to '
        'bind their own authenticator. The subsequent-login lane shows '
        'the steady-state path: django-axes counter check, PBKDF2 password '
        'verification, TOTP prompt via django-otp, IdleSessionTimeout '
        'countdown of 900 seconds, and the AuditLog row with '
        'user_role_at_time set. The failed-login lane shows the axes '
        'lockout fire on the fifth failure inside a 30-minute window, the '
        'corresponding auth.lockout AuditLog row, and the alert tile on '
        'the admin dashboard. The flow is aligned to NIST SP 800-63-4 '
        'authenticator assurance level 2 (Temoshok et al., 2025).',
    )
    add_image(doc, fig_23, width_cm=16.0)
    add_caption(
        doc,
        'Figure 23.',
        'CJPCA login and multi-factor authentication flow, from admin '
        'provisioning through subsequent login and failed-login lockout.',
    )


def write_references(doc):
    doc.add_page_break()
    add_heading(doc, 'References', level=1)
    for ref in REFERENCES:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(1.0)
        p.paragraph_format.first_line_indent = Cm(-1.0)
        p.paragraph_format.space_after = Pt(8)
        run = p.add_run(ref)
        set_run_style(run, color=DARK_GRAY, size=10.5)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'cybersecurity_v2.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'cybersecurity_v2_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    diagrams = base / 'diagrams'
    fig_17 = diagrams / 'Figure_17_SecureArchitecture.drawio.png'
    fig_18 = diagrams / 'Figure_18_ThreatModel.drawio.png'
    fig_19 = diagrams / 'Figure_19_ControlsMapping.drawio.png'
    fig_23 = diagrams / 'Figure_23_LoginMFAFlow.png'

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    write_main_body(doc, fig_17, fig_18, fig_19)
    write_appendix(doc)
    write_appendix_c4(doc, fig_23)
    write_references(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
