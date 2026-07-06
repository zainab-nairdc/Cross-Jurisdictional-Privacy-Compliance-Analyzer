"""Generate Figure A.2.5.1 — Logs and Detection Flow (drawio).

Output: diagrams/Figure_A_2_5_1_LogsDetection.drawio

Left-to-right flow showing how an in-system action becomes a detectable
audit trail. Used in Appendix 2.5 alongside the risk register and the
security policy table.

  User action
    → Middleware (axes, geo, MFA, idle)
    → View handler (RBAC check, ORM call)
    → Audit signal
        → AuditLog table (append-only, role-at-time snapshot)
        → Per-job .log file
    → Detection sinks
        → Admin inspection (Django admin + recent-activity widget)
        → SIEM export (recommended)
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1500
PAGE_H = 800

TITLE_Y = 20
FOOTER_Y = 750


# (id, label, x, y, w, h, fill, stroke)
NODES = [
    ('n_user',     'User action\n(login / upload /\napprove / export)',
     60, 220, 180, 100, '#F4B5B5', '#A02020'),

    ('n_mw',       'Middleware stack\n(axes → geo → MFA →\nsession → CSRF)',
     290, 220, 200, 100, '#F4C49E', '#B05A00'),

    ('n_view',     'View handler\n(RBAC check\n+ ORM call)',
     540, 220, 180, 100, '#E5C97A', '#B07A00'),

    ('n_signal',   'Audit signal\n(log_event)',
     770, 220, 160, 100, '#C7B3E5', '#5E3FBE'),

    ('n_audit',    'AuditLog table\n28 action constants\nuser_role_at_time',
     980, 110, 220, 110, '#B5E0C2', '#1B7F3A'),

    ('n_jobs',     'Per-job .log file\nlogs/run_<type>_<id>.log',
     980, 330, 220, 100, '#B5E0C2', '#1B7F3A'),

    ('n_admin',    'Django admin\n+ recent-activity\nwidget',
     1250, 110, 200, 110, '#9CC9D9', '#2B6E80'),

    ('n_siem',     'SIEM export\n(recommended)',
     1250, 330, 200, 100, '#9CC9D9', '#2B6E80'),

    ('n_block',    'Lockout / 403\n(axes, geo, RBAC)',
     290, 400, 200, 80, '#FBE2DE', '#A02020'),
]


# (source, target, label)
EDGES = [
    ('n_user',   'n_mw',     ''),
    ('n_mw',     'n_view',   'pass'),
    ('n_mw',     'n_block',  'deny'),
    ('n_view',   'n_signal', 'mutating action'),
    ('n_signal', 'n_audit',  'persist'),
    ('n_signal', 'n_jobs',   'append'),
    ('n_audit',  'n_admin',  'inspect'),
    ('n_audit',  'n_siem',   'export'),
    ('n_jobs',   'n_admin',  ''),
    ('n_jobs',   'n_siem',   ''),
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
        'Figure A.2.5.1 — CJPCA Logs and Detection Flow',
        STYLE_TITLE, 300, TITLE_Y, 900, 30,
    ))

    for (nid, label, x, y, w, h, fill, stroke) in NODES:
        style = STYLE_NODE.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))

    for i, (src, tgt, lbl) in enumerate(EDGES, start=1):
        cells.append(cell_edge(f'e{i}', src, tgt, lbl))

    cells.append(cell_vertex(
        'footer',
        'Every mutating action is signalled to log_event. The AuditLog row is '
        'append-only and carries the actor role at write time; per-job files '
        'capture full traceback context for postmortem.',
        STYLE_FOOTER, 100, FOOTER_Y, 1300, 36,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure A.2.5.1 Logs and Detection" id="cjpca_logs">
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
    out_path = out_dir / 'Figure_A_2_5_1_LogsDetection.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
