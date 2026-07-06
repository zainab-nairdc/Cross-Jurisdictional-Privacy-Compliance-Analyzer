"""Generate Figure 16 — Django URL Routes Catalog (drawio).

Output: diagrams/Figure_16_URLRoutesCatalog.drawio

Two-column catalog of the key Django URL routes, grouped by app.
Each route shows HTTP method (color-coded), URL pattern, and description.

Style modelled on the user's reference image — method badge on the left,
URL pattern in monospace, description on the right. Sections grouped by
Django app with a header bar at the top of each.
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1500
PAGE_H = 2200

TITLE_Y = 30

# ── Method palette (match the reference image) ──────────────────────────
METHOD_STYLES = {
    'GET':    ('#D8F0D5', '#1B7F3A'),   # green
    'POST':   ('#C5DCF5', '#2B5F9E'),   # blue
    'PATCH':  ('#FCD9A8', '#B07A00'),   # orange
    'DELETE': ('#F5C2C2', '#A02020'),   # red
    'WS':     ('#E3D5F2', '#5E3FBE'),   # purple
}

# ── Sections (Django app groupings) ─────────────────────────────────────
# Each section: (header, color, [(method, path, description), ...])
LEFT_SECTIONS = [
    ('HOME', '#E1F0F8', [
        ('GET',  '/',                                'Landing — scope state + recent activity'),
    ]),
    ('ACCOUNTS — Auth, MFA, Profile', '#F4E6FF', [
        ('GET',  '/accounts/login/',                 'Login form'),
        ('POST', '/accounts/login/',                 'Submit credentials + TOTP'),
        ('GET',  '/accounts/logout/',                'End session'),
        ('POST', '/accounts/password_change/',       'Forced password change (must_change=True)'),
        ('GET',  '/accounts/profile/',               'Self-service profile'),
        ('POST', '/accounts/profile/password/',      'Change own password'),
        ('POST', '/accounts/profile/backup-codes/',  'Regenerate TOTP backup codes'),
        ('POST', '/accounts/heartbeat/',             'Reset idle-session timer'),
    ]),
    ('USERS & MONITORING (admin)', '#FFE6E6', [
        ('GET',  '/accounts/users/',                       'List users'),
        ('POST', '/accounts/users/new/',                   'Create user (temp password by email)'),
        ('POST', '/accounts/users/<pk>/role/',             'Change role'),
        ('POST', '/accounts/users/<pk>/disable/',          'Toggle active'),
        ('POST', '/accounts/users/<pk>/reset-password/',   'Reset password'),
        ('POST', '/accounts/users/<pk>/reset-mfa/',        'Reset MFA enrolment'),
        ('GET',  '/accounts/admin/monitoring/',            'System monitoring page'),
    ]),
    ('LIBRARY — Documents, Search, Terms', '#DBE7F5', [
        ('GET',  '/library/regulations/',          'List regulations'),
        ('GET',  '/library/policies/',             'List internal policies'),
        ('GET',  '/library/terms/',                'Term dictionary'),
        ('GET',  '/library/search/',               'Cross-ref search'),
        ('GET',  '/library/obligations/',          'Obligation register'),
        ('POST', '/library/upload/',               'Upload PDF/DOCX (admin)'),
        ('POST', '/library/upload/preview/',       'Metadata preview before commit'),
        ('GET',  '/library/view/<pk>/',            'Document viewer (with article anchors)'),
        ('PATCH','/library/<pk>/tags/',            'Edit document tags'),
        ('DELETE','/library/delete/<pk>/',         'Delete document (admin)'),
    ]),
    ('MAPPING — Policy Mapping Workflow', '#E1F4E5', [
        ('GET',  '/mapping/',                              'Policy picker landing'),
        ('GET',  '/mapping/setup/<pk>/',                   'Mapping config form'),
        ('POST', '/mapping/setup/<pk>/run/',               'Start mapping job'),
        ('GET',  '/mapping/<pk>/running/',                 'Progress page'),
        ('GET',  '/mapping/<pk>/progress/',                'HTMX progress poll'),
        ('GET',  '/mapping/<pk>/',                         'Results workspace'),
        ('GET',  '/mapping/evidence/<pk>/',                'Evidence panel partial'),
        ('POST', '/mapping/obligation/<pk>/override/',     'Override coverage verdict'),
        ('POST', '/mapping/gap/<pk>/save/',                'Save gap remediation'),
        ('POST', '/mapping/gap/<pk>/suggest/',             'AI gap remediation suggestion'),
        ('POST', '/mapping/gap/<pk>/assign/',              'Assign owner + due date'),
        ('POST', '/mapping/<pk>/send-to-review/',          'Submit for review (analyst)'),
        ('POST', '/mapping/<pk>/validate/',                'Approve analysis (reviewer cascade)'),
        ('GET',  '/mapping/<pk>/exports/exec-summary.pdf', 'PDF export with audit hash'),
        ('GET',  '/mapping/<pk>/exports/gap-register.xlsx','XLSX gap register export'),
    ]),
]

RIGHT_SECTIONS = [
    ('COMPARISON — Cross-Jurisdictional', '#E8DFF7', [
        ('GET',  '/comparison/',                              'Pair picker landing'),
        ('POST', '/comparison/run/',                          'Start comparison job'),
        ('GET',  '/comparison/runs/<pk>/',                    'Comparison workspace'),
        ('POST', '/comparison/runs/<pk>/submit-review/',      'Submit for review'),
        ('GET',  '/comparison/api/pairs/',                    'Available pairs (JSON)'),
        ('POST', '/comparison/api/topic-scan/',               'Topic-coverage scan (JSON)'),
        ('GET',  '/comparison/api/documents/<pk>/strictness/','StrictnessScore (JSON)'),
        ('GET',  '/comparison/runs/<pk>/status/',             'Run status poll'),
        ('GET',  '/comparison/runs/<pk>/insights/',           'Top divergences (JSON)'),
        ('POST', '/comparison/results/<pk>/transition/',      'Approve/reject finding'),
        ('POST', '/comparison/results/<pk>/note/',            'Save reviewer note'),
        ('GET',  '/comparison/runs/<pk>/exports/exec-summary.pdf', 'PDF export with audit hash'),
        ('GET',  '/comparison/runs/<pk>/exports/comparison-register.xlsx', 'XLSX export'),
    ]),
    ('REVIEW — Reviewer Queue', '#FFF6E0', [
        ('GET',  '/review/',                  'Pending review queue (reviewer + admin)'),
        ('GET',  '/review/item/<pk>/',        'Single item review viewer'),
        ('GET',  '/review/export/<format>/',  'Bulk export PDF / XLSX'),
    ]),
    ('INGESTION — Quarantine (admin)', '#FCE8E8', [
        ('GET',  '/ingestion/widget/',                      'HTMX progress widget'),
        ('GET',  '/ingestion/quarantine/',                  'Quarantine queue'),
        ('POST', '/ingestion/quarantine/<pk>/<action>/',    'Approve/reject flagged chunk'),
        ('WS',   '/ws/ingestion/<job_id>/',                 'Live ingestion progress (Channels)'),
    ]),
    ('COPILOT — Q&A Panel', '#FFE4CC', [
        ('POST', '/copilot/message/',               'Submit question → grounded answer'),
        ('POST', '/copilot/clear/',                 'Clear conversation thread'),
        ('GET',  '/copilot/scope/',                 'Copilot readiness state'),
        ('PATCH','/copilot/scope/preferences/',     'Update doc-scope preferences'),
        ('GET',  '/viewer/<doc>/<article>/',        'Doc viewer with article anchor'),
    ]),
    ('ANALYTICS — Dashboards', '#E1F4E5', [
        ('GET', '/analytics/',                  'Compliance dashboard'),
        ('GET', '/analytics/data/',             'Chart data (JSON)'),
        ('GET', '/analytics/heatmap/',          'Coverage heatmap partial'),
        ('GET', '/analytics/gaps/',             'Gap register summary'),
        ('GET', '/analytics/cross-gap/',        'Cross-jurisdiction gap view'),
        ('GET', '/analytics/conflicts/',        'Conflict scanner'),
    ]),
    ('HISTORY — Audit Log', '#F4F6FB', [
        ('GET', '/history/',          'Audit log timeline (scoped by role)'),
        ('GET', '/history/<pk>/',     'Event detail'),
    ]),
]


# ── Layout constants ────────────────────────────────────────────────────
COL_LEFT_X       = 30
COL_RIGHT_X      = 760
COL_W            = 700

SECTION_HEADER_H = 30
ROUTE_H          = 26
SECTION_GAP      = 18

METHOD_W         = 70
PATH_W           = 340
DESC_W           = COL_W - METHOD_W - PATH_W - 30


# ── Styles ──────────────────────────────────────────────────────────────
STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#002583;'
)
STYLE_SECTION_HEADER = (
    'rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor=#7B8499;'
    'strokeWidth=1;fontColor=#002583;fontStyle=1;fontSize=11;'
    'verticalAlign=middle;align=center;'
)
STYLE_ROUTE_ROW = (
    'rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#E5E8EF;'
    'strokeWidth=1;fontColor=#1F2937;fontStyle=0;fontSize=9;'
    'verticalAlign=middle;align=left;spacingLeft=8;'
)
STYLE_METHOD_BADGE = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
    'strokeWidth=1;fontColor={stroke};fontStyle=1;fontSize=9;'
    'verticalAlign=middle;align=center;arcSize=20;'
)
STYLE_PATH = (
    'text;html=1;align=left;verticalAlign=middle;fontStyle=0;fontSize=9;'
    'fontColor=#1F2937;fontFamily=Consolas;spacingLeft=4;'
)
STYLE_DESC = (
    'text;html=1;align=left;verticalAlign=middle;fontStyle=0;fontSize=9;'
    'fontColor=#6B7280;fontStyle=2;spacingLeft=4;'
)


def cell_vertex(cell_id, value, style, x, y, w, h):
    return (
        f'        <mxCell id="{cell_id}" value="{escape(value)}" '
        f'style="{style}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
        f'as="geometry" />\n'
        f'        </mxCell>'
    )


def emit_section(cells, section, x_col, y_start, section_idx):
    """Emit a section header and its rows. Returns the y-coordinate after."""
    header, fill, routes = section
    # Header bar
    cells.append(cell_vertex(
        f'sec_{section_idx}_hdr', header,
        STYLE_SECTION_HEADER.format(fill=fill),
        x_col, y_start, COL_W, SECTION_HEADER_H,
    ))
    y = y_start + SECTION_HEADER_H
    for i, (method, path, desc) in enumerate(routes):
        # Row background
        cells.append(cell_vertex(
            f'sec_{section_idx}_r{i}_bg', '',
            STYLE_ROUTE_ROW,
            x_col, y, COL_W, ROUTE_H,
        ))
        # Method badge
        fill, stroke = METHOD_STYLES.get(method, METHOD_STYLES['GET'])
        cells.append(cell_vertex(
            f'sec_{section_idx}_r{i}_m', method,
            STYLE_METHOD_BADGE.format(fill=fill, stroke=stroke),
            x_col + 6, y + 4, METHOD_W - 12, ROUTE_H - 8,
        ))
        # URL path
        cells.append(cell_vertex(
            f'sec_{section_idx}_r{i}_p', path,
            STYLE_PATH,
            x_col + METHOD_W, y, PATH_W, ROUTE_H,
        ))
        # Description
        cells.append(cell_vertex(
            f'sec_{section_idx}_r{i}_d', desc,
            STYLE_DESC,
            x_col + METHOD_W + PATH_W, y, DESC_W, ROUTE_H,
        ))
        y += ROUTE_H
    return y + SECTION_GAP


def build_xml():
    cells = []

    # Title
    cells.append(cell_vertex(
        'title',
        'Figure 16 — Django URL Routes Catalog',
        STYLE_TITLE, 300, TITLE_Y, 900, 30,
    ))

    # Left column
    y_left = 80
    section_idx = 0
    for section in LEFT_SECTIONS:
        y_left = emit_section(cells, section, COL_LEFT_X, y_left, section_idx)
        section_idx += 1

    # Right column
    y_right = 80
    for section in RIGHT_SECTIONS:
        y_right = emit_section(cells, section, COL_RIGHT_X, y_right, section_idx)
        section_idx += 1

    body = '\n'.join(cells)
    final_h = max(y_left, y_right) + 50
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 16 URL Routes Catalog" id="cjpca_url_catalog">
    <mxGraphModel dx="{PAGE_W}" dy="{final_h}" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{PAGE_W}" pageHeight="{final_h}" math="0" shadow="0">
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
    out_path = out_dir / 'Figure_16_URLRoutesCatalog.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
