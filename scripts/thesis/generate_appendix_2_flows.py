"""Generate the 5 missing Appendix 2 flow diagrams as PNG.

Outputs (under diagrams/):
  Figure_A2_3d_Ingestion_Activity.png       (was only .puml)
  Figure_A2_12_LoginMFA_Flow.png            (A2.12)
  Figure_A2_15_PromptInjection_Flow.png     (A2.15)
  Figure_A2_16_GeoFence_Flow.png            (A2.16)
  Figure_A2_17_AuditHashChain_Flow.png      (A2.17)

Each diagram is built with matplotlib so no external renderer (drawio
CLI, PlantUML) is needed.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


NAVY = '#002583'
LIGHT_BLUE = '#DBE7F5'
AMBER = '#FFF6E0'
AMBER_BORDER = '#B07A00'
RED = '#FAD4D4'
RED_BORDER = '#B91C1C'
GREEN = '#D5EBDF'
GREEN_BORDER = '#15803D'
GRAY = '#F4F6FB'
GRAY_BORDER = '#7B8499'
PURPLE = '#E5DDF7'
PURPLE_BORDER = '#5E3FBE'


def _setup_axes(width=14, height=10):
    fig, ax = plt.subplots(figsize=(width, height), dpi=180)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_aspect('equal')
    ax.axis('off')
    return fig, ax


def _box(ax, x, y, w, h, text, fill, edge, fontsize=8, bold=False):
    rect = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle='round,pad=0.4',
        linewidth=1.0, edgecolor=edge, facecolor=fill,
    )
    ax.add_patch(rect)
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
            fontsize=fontsize, color='black',
            fontweight='bold' if bold else 'normal', wrap=True)


def _diamond(ax, cx, cy, w, h, text, fontsize=7):
    diamond = mpatches.FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h, boxstyle='round,pad=0.2',
        linewidth=1.0, edgecolor=AMBER_BORDER, facecolor=AMBER,
    )
    ax.add_patch(diamond)
    ax.text(cx, cy, text, ha='center', va='center', fontsize=fontsize,
            color='black')


def _arrow(ax, x1, y1, x2, y2, label=None, color='#1F2937'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.2))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 1, label, ha='center',
                va='bottom', fontsize=7, color=color)


def _title(ax, text):
    ax.text(50, 97, text, ha='center', va='top',
            fontsize=12, fontweight='bold', color=NAVY)


# -------------------------------------------------------------------------
# Figure A2.12 — Login and MFA flow
# -------------------------------------------------------------------------

def gen_login_mfa(out_dir: Path):
    fig, ax = _setup_axes(14, 10)
    _title(ax, 'CJPCA Login and Multi-Factor Authentication Flow')

    _box(ax, 5, 80, 18, 8, 'Browser POST\n/two_factor/login/',
         LIGHT_BLUE, NAVY, bold=True)
    _box(ax, 28, 80, 18, 8, 'django-axes check\n(5 fails / 30 min)',
         AMBER, AMBER_BORDER)
    _box(ax, 51, 80, 18, 8, 'Password validators\n(len12 + complexity)',
         AMBER, AMBER_BORDER)
    _box(ax, 74, 80, 18, 8, 'ModelBackend\nverify password',
         GRAY, GRAY_BORDER)
    _box(ax, 5, 60, 18, 8, 'TOTP step\n(django-otp)',
         GRAY, GRAY_BORDER)
    _box(ax, 28, 60, 18, 8, 'ForceMFAEnrolment\nconfirmed=True ?',
         PURPLE, PURPLE_BORDER)
    _box(ax, 51, 60, 18, 8, 'ForcePasswordChange\nmust_change ?',
         PURPLE, PURPLE_BORDER)
    _box(ax, 74, 60, 18, 8,
         'Session created\nSecure + HttpOnly +\nSameSite=Lax',
         GREEN, GREEN_BORDER)
    _box(ax, 5, 40, 18, 8, 'Idle timeout\n1800 s',
         AMBER, AMBER_BORDER)
    _box(ax, 28, 40, 18, 8, 'Lockout after\n5 failed attempts',
         RED, RED_BORDER)
    _box(ax, 51, 40, 18, 8, 'auth.login\nAuditLog row',
         GREEN, GREEN_BORDER)
    _box(ax, 74, 40, 18, 8, 'auth.login_failed\nAuditLog row',
         RED, RED_BORDER)

    _arrow(ax, 23, 84, 28, 84)
    _arrow(ax, 46, 84, 51, 84)
    _arrow(ax, 69, 84, 74, 84)
    _arrow(ax, 83, 80, 14, 68, label='OK')
    _arrow(ax, 23, 64, 28, 64)
    _arrow(ax, 46, 64, 51, 64)
    _arrow(ax, 69, 64, 74, 64)
    _arrow(ax, 83, 60, 60, 44, label='audit')
    _arrow(ax, 14, 60, 14, 48, label='timeout')
    _arrow(ax, 37, 80, 37, 48, label='5 fails')
    _arrow(ax, 83, 60, 83, 48, label='fail')

    ax.text(50, 25, 'On success: session active until idle timeout '
            'or explicit logout.\nOn failure: lockout middleware blocks '
            'further attempts.\nOn first login: forced password change '
            'then MFA enrolment.',
            ha='center', va='center', fontsize=8, color='#1F2937')

    out = out_dir / 'Figure_A2_12_LoginMFA_Flow.png'
    fig.savefig(out, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  {out.name}')


# -------------------------------------------------------------------------
# Figure A2.15 — Prompt Injection Defence Flow
# -------------------------------------------------------------------------

def gen_injection_flow(out_dir: Path):
    fig, ax = _setup_axes(14, 12)
    _title(ax, 'CJPCA Two-Tier Prompt Injection Defence Flow')

    _box(ax, 35, 85, 30, 8, 'Uploaded document\n(PDF / DOCX)',
         LIGHT_BLUE, NAVY, bold=True)
    _box(ax, 35, 72, 30, 8, 'Parse + chunk\n(Docling, section-aware)',
         GRAY, GRAY_BORDER)
    _box(ax, 35, 59, 30, 8,
         'Tier-A regex scan\n9 rule groups: override, role-hijack,\n'
         'forced-verdict, safety-bypass, dev-mode,\n'
         'prompt-leak, fake-delimiter, base64, URL',
         AMBER, AMBER_BORDER, fontsize=7)
    _diamond(ax, 50, 46, 28, 7, 'Any rule matched?')

    _box(ax, 5, 30, 30, 8, 'Embed with BGE-small\n+ index in ChromaDB + FTS5',
         GREEN, GREEN_BORDER)
    _box(ax, 65, 30, 30, 8,
         'Tier-B LLM judge\nspotlight delimiters,\nfail-closed',
         RED, RED_BORDER)
    _diamond(ax, 80, 17, 28, 7, 'Injection verdict?')

    _box(ax, 35, 3, 30, 8,
         'QuarantinedChunk row\npending admin review',
         RED, RED_BORDER, bold=True)

    _arrow(ax, 50, 85, 50, 80)
    _arrow(ax, 50, 72, 50, 67)
    _arrow(ax, 50, 59, 50, 50)
    _arrow(ax, 36, 46, 20, 38, label='no')
    _arrow(ax, 64, 46, 80, 38, label='yes')
    _arrow(ax, 80, 30, 80, 21)
    _arrow(ax, 66, 17, 50, 11, label='injection')
    _arrow(ax, 94, 17, 99, 30, label='clean')

    out = out_dir / 'Figure_A2_15_PromptInjection_Flow.png'
    fig.savefig(out, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  {out.name}')


# -------------------------------------------------------------------------
# Figure A2.16 — GeoFence Middleware Flow
# -------------------------------------------------------------------------

def gen_geofence_flow(out_dir: Path):
    fig, ax = _setup_axes(14, 10)
    _title(ax, 'CJPCA GeoFence Middleware Flow')

    _box(ax, 35, 85, 30, 8, 'Incoming HTTP request',
         LIGHT_BLUE, NAVY, bold=True)
    _box(ax, 35, 72, 30, 8,
         'Read X-Forwarded-For\nresolve client IP',
         GRAY, GRAY_BORDER)
    _diamond(ax, 50, 60, 30, 7, 'Private / loopback IP ?')
    _box(ax, 5, 45, 28, 8,
         'Pass through\n(127.x, 10.x, 192.168.x)',
         GREEN, GREEN_BORDER)
    _box(ax, 67, 45, 28, 8,
         'GeoLite2 country lookup\n(MaxMind DB)',
         AMBER, AMBER_BORDER)
    _diamond(ax, 80, 32, 30, 7, 'GeoLite2 available?')
    _box(ax, 67, 17, 28, 8, 'Fail open\nallow request',
         GREEN, GREEN_BORDER)
    _diamond(ax, 50, 4, 30, 7, 'Country in allowlist?')
    _box(ax, 5, 17, 28, 8, 'HTTP 403\ngeofence.deny audit',
         RED, RED_BORDER, bold=True)
    _box(ax, 35, 60, 30, 0, '', LIGHT_BLUE, NAVY)

    _arrow(ax, 50, 85, 50, 80)
    _arrow(ax, 50, 72, 50, 64)
    _arrow(ax, 36, 60, 19, 53, label='yes')
    _arrow(ax, 64, 60, 81, 53, label='no')
    _arrow(ax, 80, 45, 80, 36)
    _arrow(ax, 95, 32, 81, 21, label='no')
    _arrow(ax, 66, 32, 56, 11, label='yes')
    _arrow(ax, 36, 4, 19, 21, label='no')

    ax.text(50, 92, 'Default allowlist: BH, IN, KW (env-configurable)',
            ha='center', fontsize=8, style='italic', color='#1F2937')

    out = out_dir / 'Figure_A2_16_GeoFence_Flow.png'
    fig.savefig(out, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  {out.name}')


# -------------------------------------------------------------------------
# Figure A2.17 — Audit and Hash Chain Flow
# -------------------------------------------------------------------------

def gen_audit_flow(out_dir: Path):
    fig, ax = _setup_axes(14, 10)
    _title(ax, 'CJPCA Audit Log and SHA-256 Export Hash Chain Flow')

    _box(ax, 5, 80, 24, 8,
         'log_event(actor, action,\ntarget, payload)',
         LIGHT_BLUE, NAVY, bold=True)
    _box(ax, 34, 80, 24, 8,
         'Audit signal fires\n(post-action)',
         GRAY, GRAY_BORDER)
    _box(ax, 63, 80, 24, 8,
         'Sanitiser strips\nkey / token / secret /\npassword fields',
         AMBER, AMBER_BORDER)
    _box(ax, 5, 60, 24, 8,
         'Handler writes\nAuditLog row\n+ user_role_at_time',
         GREEN, GREEN_BORDER)
    _box(ax, 34, 60, 24, 8,
         'Per-job log file\n(structured JSON)',
         GREEN, GREEN_BORDER)
    _box(ax, 63, 60, 24, 8,
         'Approved analysis\nexport requested',
         LIGHT_BLUE, NAVY)
    _box(ax, 5, 40, 24, 8,
         'audit_hash(obj)\nSHA-256 over identity tuple',
         AMBER, AMBER_BORDER, bold=True)
    _box(ax, 34, 40, 24, 8,
         'First 16 hex chars\nstamped in PDF /\nXLSX footer',
         GREEN, GREEN_BORDER)
    _box(ax, 63, 40, 24, 8,
         'export.create\nAuditLog row\nwith hash prefix',
         GREEN, GREEN_BORDER)
    _box(ax, 20, 18, 55, 12,
         'Recipient re-runs audit_hash(obj) on receipt and compares '
         'prefixes.\nMismatch = tampered or stale artifact. '
         'Match = chain intact, sign-off verified.',
         LIGHT_BLUE, NAVY, fontsize=9)

    _arrow(ax, 29, 84, 34, 84)
    _arrow(ax, 58, 84, 63, 84)
    _arrow(ax, 17, 80, 17, 68)
    _arrow(ax, 75, 80, 75, 68)
    _arrow(ax, 46, 60, 46, 50, label='on approval')
    _arrow(ax, 75, 60, 46, 48)
    _arrow(ax, 29, 44, 34, 44)
    _arrow(ax, 58, 44, 63, 44)
    _arrow(ax, 46, 40, 46, 30, label='delivered')

    out = out_dir / 'Figure_A2_17_AuditHashChain_Flow.png'
    fig.savefig(out, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  {out.name}')


# -------------------------------------------------------------------------
# Figure A2.3d — Ingestion activity diagram (3 swim lanes)
# -------------------------------------------------------------------------

def gen_ingestion_activity(out_dir: Path):
    fig, ax = _setup_axes(16, 12)
    _title(ax, 'CJPCA Document Ingestion Pipeline (Activity Diagram)')

    # Swim-lane backdrops
    ax.add_patch(mpatches.Rectangle((1, 5), 32, 86, linewidth=0.8,
                                     edgecolor=GRAY_BORDER, facecolor=GRAY,
                                     alpha=0.3))
    ax.add_patch(mpatches.Rectangle((33.5, 5), 32, 86, linewidth=0.8,
                                     edgecolor=GRAY_BORDER, facecolor='white'))
    ax.add_patch(mpatches.Rectangle((66, 5), 32, 86, linewidth=0.8,
                                     edgecolor=GRAY_BORDER, facecolor=PURPLE,
                                     alpha=0.2))

    ax.text(17, 90, 'Administrator', ha='center', fontsize=10,
            fontweight='bold', color=NAVY)
    ax.text(49.5, 90, 'Django web layer', ha='center', fontsize=10,
            fontweight='bold', color=NAVY)
    ax.text(82, 90, 'Ingestion pipeline', ha='center', fontsize=10,
            fontweight='bold', color=NAVY)

    _box(ax, 3, 80, 28, 6, 'Upload PDF / DOCX\nvia /library/upload/',
         LIGHT_BLUE, NAVY, bold=True)
    _box(ax, 35.5, 80, 28, 6,
         'Create Document row\nstatus = PROCESSING',
         GRAY, GRAY_BORDER)
    _box(ax, 35.5, 71, 28, 6,
         'Create IngestionJob\nstatus = QUEUED',
         GRAY, GRAY_BORDER)
    _box(ax, 35.5, 62, 28, 6,
         'Dispatch background\nworker run_job(pk)',
         GRAY, GRAY_BORDER)
    _box(ax, 68, 62, 28, 6,
         'Stage 1: Parse text\n(Docling)',
         PURPLE, PURPLE_BORDER)
    _box(ax, 68, 53, 28, 6,
         'Stage 2: Chunk\n(section-aware split)',
         PURPLE, PURPLE_BORDER)
    _box(ax, 68, 44, 28, 6,
         'Stage 3: Embed with\nBGE-small (384-dim)',
         PURPLE, PURPLE_BORDER)
    _box(ax, 68, 35, 28, 6,
         'Stage 4: Tier-A regex\n+ Tier-B LLM judge',
         AMBER, AMBER_BORDER)
    _diamond(ax, 82, 26, 28, 5, 'Suspicious patterns?')
    _box(ax, 3, 17, 28, 6,
         'Review quarantined chunk\nat /ingestion/quarantine/',
         RED, RED_BORDER)
    _box(ax, 68, 17, 28, 6,
         'Stage 5: Write to\nChromaDB + SQLite FTS5',
         GREEN, GREEN_BORDER)
    _box(ax, 35.5, 17, 28, 6,
         'Set Document.status\n= INDEXED',
         GREEN, GREEN_BORDER)
    _box(ax, 3, 7, 28, 6,
         'Document searchable\nin library',
         LIGHT_BLUE, NAVY, bold=True)

    _arrow(ax, 31, 83, 35.5, 83)
    _arrow(ax, 49.5, 80, 49.5, 77)
    _arrow(ax, 49.5, 71, 49.5, 68)
    _arrow(ax, 63.5, 65, 68, 65)
    _arrow(ax, 82, 62, 82, 59)
    _arrow(ax, 82, 53, 82, 50)
    _arrow(ax, 82, 44, 82, 41)
    _arrow(ax, 82, 35, 82, 31)
    _arrow(ax, 68, 26, 31, 20, label='yes (quarantine)')
    _arrow(ax, 96, 26, 96, 23, label='no')
    _arrow(ax, 96, 23, 96, 23)
    _arrow(ax, 68, 20, 63.5, 20)
    _arrow(ax, 35.5, 20, 31, 13)

    out = out_dir / 'Figure_A2_3d_Ingestion_Activity.png'
    fig.savefig(out, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  {out.name}')


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'diagrams'
    out_dir.mkdir(exist_ok=True)
    print(f'Writing to {out_dir}/')
    gen_login_mfa(out_dir)
    gen_injection_flow(out_dir)
    gen_geofence_flow(out_dir)
    gen_audit_flow(out_dir)
    gen_ingestion_activity(out_dir)
    print('Done.')


if __name__ == '__main__':
    main()
