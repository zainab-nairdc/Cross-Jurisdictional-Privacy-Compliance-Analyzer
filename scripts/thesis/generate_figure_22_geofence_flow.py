"""Generate Figure 22 — GeoFence Decision Flow (drawio).

Output: diagrams/Figure_22_GeoFenceFlow.drawio

Decision flowchart for GeoFenceMiddleware. Shows the exempt paths,
private-IP shortcut, MaxMind lookup, allowlist match, and the fail-open
behaviour that avoids locking the BBK network out on lookup error.
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1300
PAGE_H = 900

TITLE_Y = 20
FOOTER_Y = 850


NODES = [
    ('g_req',     'Incoming request',
     520, 90, 200, 60, '#E1F0F8', '#2B6E80'),

    ('g_enabled', 'GEOFENCE_ENABLED\n= True ?',
     520, 180, 200, 70, '#FFE4CC', '#B05A00'),

    ('g_exempt',  '/static/ or /media/\nprefix ?',
     520, 280, 200, 70, '#FFE4CC', '#B05A00'),

    ('g_ip',      'Extract client IP\n(X-Forwarded-For first hop\nor REMOTE_ADDR)',
     520, 380, 240, 80, '#F4C49E', '#B05A00'),

    ('g_private', 'Private / loopback /\nlink-local IP ?',
     520, 490, 240, 70, '#FFE4CC', '#B05A00'),

    ('g_lookup',  'MaxMind GeoLite2\nlookup',
     520, 590, 240, 60, '#F4C49E', '#B05A00'),

    ('g_failopen','Lookup error\nor reader missing ?',
     820, 590, 220, 60, '#FBE2DE', '#A02020'),

    ('g_allowed', 'Country in\nGEOFENCE_ALLOWED_\nCOUNTRIES ?\n(default BH IN KW AE)',
     520, 680, 240, 90, '#FFE4CC', '#B05A00'),

    ('g_pass',    'Pass to next\nmiddleware',
     200, 540, 200, 70, '#B5E0C2', '#1B7F3A'),

    ('g_block',   'HTTP 403\nGeographic policy\nviolation',
     900, 700, 200, 80, '#FBE2DE', '#A02020'),
]


EDGES = [
    ('g_req',     'g_enabled',  ''),
    ('g_enabled', 'g_pass',     'no — disabled'),
    ('g_enabled', 'g_exempt',   'yes'),
    ('g_exempt',  'g_pass',     'yes'),
    ('g_exempt',  'g_ip',       'no'),
    ('g_ip',      'g_private',  ''),
    ('g_private', 'g_pass',     'yes'),
    ('g_private', 'g_lookup',   'no'),
    ('g_lookup',  'g_failopen', ''),
    ('g_failopen','g_pass',     'yes — fail open\n(log warning)'),
    ('g_failopen','g_allowed',  'no'),
    ('g_allowed', 'g_pass',     'yes'),
    ('g_allowed', 'g_block',    'no'),
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
        'Figure 22 — GeoFence Decision Flow',
        STYLE_TITLE, 350, TITLE_Y, 600, 30,
    ))

    for (nid, label, x, y, w, h, fill, stroke) in NODES:
        style = STYLE_NODE.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))

    for i, (src, tgt, lbl) in enumerate(EDGES, start=1):
        cells.append(cell_edge(f'g{i}', src, tgt, lbl))

    cells.append(cell_vertex(
        'footer',
        'GeoFence fails open on lookup error so BBK staff are never locked '
        'out by an unavailable GeoLite2 database; private and loopback '
        'addresses are always allowed.',
        STYLE_FOOTER, 100, FOOTER_Y, 1100, 36,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 22 GeoFence" id="cjpca_geo">
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
    out_path = out_dir / 'Figure_22_GeoFenceFlow.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
