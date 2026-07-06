"""Generate Figure 20 — Login and MFA Flow (drawio).

Output: diagrams/Figure_20_LoginMFAFlow.drawio

Sequence-style flow showing every gate that a user crosses between hitting
the login page and reaching an authenticated view:

  Browser → axes lockout check → password validators → MFA challenge →
  ForceMFAEnrollment (if no confirmed TOTP device) → ForcePasswordChange
  (if must_change_password flag) → session created → audit row.

Failure branches drop down to denied states with audit signals.
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1500
PAGE_H = 1000

TITLE_Y = 20
FOOTER_Y = 950


# (id, label, x, y, w, h, fill, stroke)
NODES = [
    ('s_browser',  'Browser POST\n/two_factor/login/',
     60, 110, 180, 70, '#E1F0F8', '#2B6E80'),

    ('s_axes',     'django-axes check\n(5 fails / 30 min,\nIP+username)',
     290, 100, 200, 90, '#FFE4CC', '#B05A00'),

    ('s_pw',       'Password validators\nlen 12 + complexity +\nsimilar + breached',
     540, 100, 220, 90, '#FFE4CC', '#B05A00'),

    ('s_creds',    'ModelBackend\nverify password',
     810, 110, 180, 70, '#E5C97A', '#B07A00'),

    ('s_mfa',      'OTP step\n(TOTP code)',
     1040, 110, 170, 70, '#E5C97A', '#B07A00'),

    ('s_enroll',   'ForceMFAEnrollment\nMW: confirmed=True ?',
     1260, 110, 200, 80, '#C7B3E5', '#5E3FBE'),

    ('s_force_pw', 'ForcePasswordChange\nMW: must_change ?',
     810, 240, 220, 80, '#C7B3E5', '#5E3FBE'),

    ('s_session',  'Session created\nCookie: Secure + HttpOnly +\nSameSite=Lax',
     1090, 240, 240, 90, '#B5E0C2', '#1B7F3A'),

    ('s_audit_ok', 'AuditLog\nauth.login + mfa_enrolled\n(if first device)',
     1090, 360, 240, 80, '#9CC9D9', '#2B6E80'),

    # Failure paths
    ('s_locked',   'HTTP 403\nLocked Out\naudit: lockout',
     290, 240, 200, 80, '#FBE2DE', '#A02020'),

    ('s_failed',   'Invalid credentials\naudit: auth.login_failed\n(attempted_username)',
     540, 240, 220, 80, '#FBE2DE', '#A02020'),

    ('s_setup',    'Redirect to\n/two_factor/setup/\n(TOTP enrollment)',
     1260, 240, 200, 80, '#FFF6E0', '#B07A00'),

    ('s_change',   'Redirect to\n/accounts/password_change/',
     540, 360, 220, 80, '#FFF6E0', '#B07A00'),

    # Authenticated view
    ('s_view',     'Authenticated view\nRBAC + per-row scope',
     1090, 480, 240, 80, '#B5E0C2', '#1B7F3A'),
]


# (source, target, label)
EDGES = [
    ('s_browser',  's_axes',     ''),
    ('s_axes',     's_pw',       'pass'),
    ('s_axes',     's_locked',   'lockout'),
    ('s_pw',       's_creds',    'valid'),
    ('s_pw',       's_failed',   'reject'),
    ('s_creds',    's_mfa',      'OK'),
    ('s_creds',    's_failed',   'bad password'),
    ('s_mfa',      's_enroll',   'OK or skip'),
    ('s_enroll',   's_setup',    'no device'),
    ('s_enroll',   's_force_pw', 'confirmed'),
    ('s_force_pw', 's_change',   'flag = True'),
    ('s_force_pw', 's_session',  'flag = False'),
    ('s_session',  's_audit_ok', ''),
    ('s_audit_ok', 's_view',     ''),
]


STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#002583;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#6B7280;'
)
STYLE_NODE = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
    'strokeWidth=1.4;fontColor=#1F2937;fontStyle=1;fontSize=10;align=center;'
    'verticalAlign=middle;arcSize=15;'
)
STYLE_EDGE = (
    'endArrow=classic;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#002583;strokeWidth=1.2;fontSize=9;fontColor=#1F2937;'
    'opacity=85;'
)


def cell_vertex(cell_id, value, style, x, y, w, h):
    return (
        f'        <mxCell id="{cell_id}" value="{escape(value)}" '
        f'style="{style}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
        f'as="geometry" />\n'
        f'        </mxCell>'
    )


def cell_edge(edge_id, source, target, label):
    return (
        f'        <mxCell id="{edge_id}" value="{escape(label)}" '
        f'style="{STYLE_EDGE}" edge="1" source="{source}" target="{target}" '
        f'parent="1">\n'
        f'          <mxGeometry relative="1" as="geometry" />\n'
        f'        </mxCell>'
    )


def build_xml():
    cells = []

    cells.append(cell_vertex(
        'title',
        'Figure 20 — Login and MFA Flow',
        STYLE_TITLE, 400, TITLE_Y, 700, 30,
    ))

    for (nid, label, x, y, w, h, fill, stroke) in NODES:
        style = STYLE_NODE.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))

    for i, (src, tgt, lbl) in enumerate(EDGES, start=1):
        cells.append(cell_edge(f'l{i}', src, tgt, lbl))

    legend_style = (
        'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#7B8499;'
        'strokeWidth=1;fontColor=#1F2937;fontStyle=0;fontSize=9;align=left;'
        'verticalAlign=top;spacingLeft=8;spacingTop=4;arcSize=8;'
    )
    legend_text = (
        'Order matters: django-axes runs before the password check so locked '
        'accounts short-circuit; ForcePasswordChangeMiddleware runs before '
        'ForceMFAEnrollment so new accounts rotate the temporary password '
        'first. Every terminal state in this flow produces an AuditLog row.'
    )
    cells.append(cell_vertex(
        'legend', legend_text, legend_style,
        60, 620, 1370, 60,
    ))

    cells.append(cell_vertex(
        'footer',
        'Red boxes are denied terminal states; green boxes are authenticated '
        'states; orange boxes are remediation redirects.',
        STYLE_FOOTER, 100, FOOTER_Y, 1300, 36,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 20 Login MFA Flow" id="cjpca_login">
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
    out_path = out_dir / 'Figure_20_LoginMFAFlow.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
