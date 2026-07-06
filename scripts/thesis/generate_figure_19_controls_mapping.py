"""Generate Figure 19 — CJPCA Security Controls Mapping (drawio).

Output: diagrams/Figure_19_ControlsMapping.drawio

Four control-category columns, each listing concrete controls in the system.
Categories are aligned with the rubric's "IAM / firewall / IDS placement"
language and adapted to the CJPCA stack:

  - IAM                     (identity, MFA, RBAC)
  - Network and edge        (TLS, GeoFence, CSP, CSRF)
  - AI safety               (two-tier injection, verifier, schema)
  - Data integrity and audit (ORM, audit log, hash chain)
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1400
PAGE_H = 1000

TITLE_Y = 20
FOOTER_Y = 950

COL_W = 310
COL_GAP = 20
COL_X = [40, 380, 720, 1060]
COL_HEAD_Y = 80
COL_HEAD_H = 50
ROW_START_Y = 150
ROW_H = 90
ROW_GAP = 12


# (header_text, header_fill, header_stroke, controls[(name, where)])
COLUMNS = [
    (
        'IAM',
        '#E8DFF7', '#5E3FBE',
        [
            ('Login + TOTP',          'login view + django-otp'),
            ('Password validators',   'length 12 + complexity + similarity'),
            ('django-axes lockout',   '5 fails / 30 min, IP+username'),
            ('ForceMFA enrollment',   'middleware redirect to /setup/'),
            ('Force password change', 'middleware on must_change flag'),
            ('RBAC roles + decorator', '@role_required + RoleRequiredMixin'),
            ('Per-row object scope',  'created_by filter on jobs'),
            ('Session + idle timeout', '28 800 s session, 1 800 s idle'),
        ],
    ),
    (
        'NETWORK AND EDGE',
        '#FFE4CC', '#B05A00',
        [
            ('TLS 1.3 at proxy',      'HTTPS only on port 443'),
            ('HSTS preload',          '31 536 000 s + includeSubDomains'),
            ('CSRF middleware',       'token per form, Secure cookie'),
            ('Content Security Policy', 'django-csp 4.x, frame-ancestors none'),
            ('Security headers',      'X-Frame DENY, nosniff, ref policy'),
            ('GeoFence middleware',   'MaxMind allowlist (BH IN KW AE)'),
            ('Outbound allowlist',    'LLM endpoint + CDN only'),
            ('Upload size limit',     'DATA_UPLOAD_MAX_MEMORY_SIZE'),
        ],
    ),
    (
        'AI SAFETY',
        '#DBE7F5', '#2B5F9E',
        [
            ('Tier-A regex scanner',  '9 rule groups, deterministic'),
            ('Tier-B LLM judge',      'fail-closed on classifier error'),
            ('Quarantine table',      'flagged chunks held out of index'),
            ('Citation verifier',     'verbatim grounding check'),
            ('Hallucination score',   'cross-encoder NLI, MAX-across-chunks'),
            ('Pydantic v2 schema',    'reject malformed LLM output'),
            ('OutputFixingParser',    'bounded retry, then SafeFallback'),
            ('Schema retry cap',      'cfg.llm.retry_attempts = 2'),
        ],
    ),
    (
        'DATA INTEGRITY AND AUDIT',
        '#E1F4E5', '#1B7F3A',
        [
            ('Django ORM only',       'parameter binding, no raw SQL'),
            ('Append-only AuditLog',  '28 action constants'),
            ('Role-at-time snapshot', 'user_role_at_time per row'),
            ('Per-job log file',      'logs/run_<job>_<id>.log'),
            ('SHA-256 hash chain',    'on PDF and XLSX export'),
            ('SQLite WAL journal',    'crash-safe writes'),
            ('Template autoescape',   'no mark_safe on user content'),
            ('Secret masking',        'logs strip key/token/password fields'),
        ],
    ),
]


STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#002583;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#6B7280;'
)
STYLE_COL_HEAD = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
    'strokeWidth=1.5;fontColor={stroke};fontStyle=1;fontSize=12;align=center;'
    'verticalAlign=middle;arcSize=10;'
)
STYLE_CONTROL_NAME = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={stroke};'
    'strokeWidth=1.2;fontColor=#1F2937;fontStyle=1;fontSize=10;align=center;'
    'verticalAlign=middle;arcSize=12;'
)
STYLE_CONTROL_WHERE = (
    'text;html=1;fontSize=9;fontStyle=2;fontColor=#4B5563;align=center;'
    'verticalAlign=top;'
)


def cell_vertex(cell_id, value, style, x, y, w, h):
    return (
        f'        <mxCell id="{cell_id}" value="{escape(value)}" '
        f'style="{style}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
        f'as="geometry" />\n'
        f'        </mxCell>'
    )


def build_xml():
    cells = []

    cells.append(cell_vertex(
        'title',
        'Figure 19 — CJPCA Security Controls Mapping',
        STYLE_TITLE, 250, TITLE_Y, 900, 30,
    ))

    for col_idx, (header, fill, stroke, controls) in enumerate(COLUMNS):
        x = COL_X[col_idx]

        # Column header
        head_style = STYLE_COL_HEAD.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(
            f'col_head_{col_idx}', header, head_style,
            x, COL_HEAD_Y, COL_W, COL_HEAD_H,
        ))

        # Control rows
        row_y = ROW_START_Y
        for r_idx, (name, where) in enumerate(controls):
            name_style = STYLE_CONTROL_NAME.format(stroke=stroke)
            cells.append(cell_vertex(
                f'ctrl_{col_idx}_{r_idx}_name', name, name_style,
                x, row_y, COL_W, 32,
            ))
            cells.append(cell_vertex(
                f'ctrl_{col_idx}_{r_idx}_where', where, STYLE_CONTROL_WHERE,
                x + 5, row_y + 34, COL_W - 10, 28,
            ))
            row_y += ROW_H

    cells.append(cell_vertex(
        'footer',
        'Each column maps one control category to the concrete CJPCA control '
        'and the component that enforces it. Names sit on white tiles; the '
        'line below each tile is the enforcement location.',
        STYLE_FOOTER, 100, FOOTER_Y, 1200, 36,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 19 Controls Mapping" id="cjpca_ctrls">
    <mxGraphModel dx="{PAGE_W}" dy="{PAGE_H}" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{PAGE_W}" pageHeight="{PAGE_H}" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
{body}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
'''
    return xml


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'diagrams'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'Figure_19_ControlsMapping.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
