"""Generate Figure 18 — CJPCA Threat Model (data-flow + trust boundaries).

Output: diagrams/Figure_18_ThreatModel.drawio

Four trust zones drawn as dashed perimeters, left-to-right:
  - Untrusted Internet      (analyst browser)
  - Semi-trusted Perimeter  (reverse proxy)
  - Trusted Application     (Django middleware stack + engines + data stores)
  - Semi-trusted 3rd Party  (LLM endpoint)

Arrows crossing boundaries carry STRIDE letter markers (S T R I D E)
identifying which threat classes apply at that crossing. The full STRIDE
mitigation table is Table 10 in the main body.
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1500
PAGE_H = 1000

TITLE_Y = 20
FOOTER_Y = 950


# (id, label, x, y, w, h, fill, stroke, dashed)
ZONES = [
    ('z_inet',   'UNTRUSTED INTERNET',        60,  90, 240, 720, '#FBE2DE', '#A02020', True),
    ('z_perim',  'SEMI-TRUSTED PERIMETER',   330,  90, 220, 720, '#FFE4CC', '#B05A00', True),
    ('z_app',    'TRUSTED APPLICATION (BBK host)', 580, 90, 620, 720, '#E1F4E5', '#1B7F3A', True),
    ('z_llm',    'SEMI-TRUSTED 3RD PARTY',  1230,  90, 240, 720, '#DBE7F5', '#2B5F9E', True),
]


# Components: (id, label, x, y, w, h, fill, stroke)
COMPONENTS = [
    # Internet zone
    ('c_analyst',  'Analyst browser\nHTMX + Alpine',     90, 380, 180, 80, '#F4B5B5', '#A02020'),

    # Perimeter zone
    ('c_proxy',    'Reverse proxy\nTLS 1.3 termination', 350, 380, 180, 80, '#F4C49E', '#B05A00'),

    # Application zone — middleware stack vertically
    ('c_axes',     'django-axes\n(lockout)',             600, 130, 180, 55, '#FFE4CC', '#B05A00'),
    ('c_geo',      'GeoFenceMW',                         600, 195, 180, 55, '#FFE4CC', '#B05A00'),
    ('c_auth',     'Auth + MFA\nForceMFA + Session',     600, 260, 180, 55, '#FFF6E0', '#B07A00'),
    ('c_csrf',     'CSRF\n+ CSP + headers',              600, 325, 180, 55, '#FFE4CC', '#B05A00'),
    ('c_rbac',     'RBAC + per-row\nscope filter',       600, 390, 180, 55, '#E8DFF7', '#5E3FBE'),
    ('c_audit',    'Audit signal\n→ AuditLog',           600, 455, 180, 55, '#E1F4E5', '#1B7F3A'),

    # Application — engines
    ('c_views',    'Django views\n(ORM only)',           810, 260, 170, 80, '#FFFFFF', '#002583'),
    ('c_engine',   'Reasoning engine\n(LangGraph)',      810, 360, 170, 80, '#FFFFFF', '#002583'),
    ('c_ai',       'Tier-A regex\n+ Tier-B judge\n+ Verifier', 810, 460, 170, 90, '#DBE7F5', '#2B5F9E'),

    # Application — data stores
    ('c_sqlite',   'SQLite\nusers + audit',             1010, 130, 170, 70, '#B5E0C2', '#1B7F3A'),
    ('c_chroma',   'ChromaDB\nvector index',            1010, 215, 170, 70, '#B5E0C2', '#1B7F3A'),
    ('c_fts',      'SQLite FTS5\nBM25 index',           1010, 300, 170, 70, '#B5E0C2', '#1B7F3A'),
    ('c_media',    'media/ + data/\nfile storage',      1010, 385, 170, 70, '#B5E0C2', '#1B7F3A'),
    ('c_logs',     'AuditLog + per-job\n.log files',    1010, 470, 170, 70, '#9CC9D9', '#2B6E80'),

    # LLM zone
    ('c_llm',      'LLM endpoint\n(Ollama / provider)',  1255, 380, 200, 80, '#9CC5EE', '#2B5F9E'),
]


# Data-flow arrows with STRIDE class markers
# (source, target, label, stride)
FLOWS = [
    ('c_analyst', 'c_proxy',  '1. HTTPS request',      'S T I'),
    ('c_proxy',   'c_axes',   '2. forwarded',          'S T'),
    ('c_axes',    'c_geo',    '',                       ''),
    ('c_geo',     'c_auth',   '',                       ''),
    ('c_auth',    'c_csrf',   '',                       ''),
    ('c_csrf',    'c_rbac',   '',                       ''),
    ('c_rbac',    'c_views',  '3. authorized',         'I E'),
    ('c_views',   'c_audit',  '4. audit signal',       'R'),
    ('c_views',   'c_engine', '5. invoke',             ''),
    ('c_engine',  'c_ai',     '6. verify',             'T'),
    ('c_ai',      'c_llm',    '7. minimal prompt',     'I D'),
    ('c_llm',     'c_ai',     '8. JSON output',        'T'),
    ('c_engine',  'c_chroma', '9. vector query',       ''),
    ('c_engine',  'c_fts',    '',                       ''),
    ('c_audit',   'c_sqlite', '',                       ''),
    ('c_audit',   'c_logs',   '',                       ''),
    ('c_views',   'c_media',  'upload',                'T'),
    ('c_proxy',   'c_analyst','10. response',          ''),
]


STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#002583;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#6B7280;'
)
STYLE_ZONE = (
    'rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
    'strokeWidth=2;dashed=1;dashPattern=8 4;fontColor={stroke};fontStyle=1;'
    'fontSize=11;verticalAlign=top;align=center;opacity=40;'
)
STYLE_ZONE_LABEL = (
    'text;html=1;fontSize=11;fontStyle=1;fontColor={stroke};align=center;'
    'verticalAlign=middle;'
)
STYLE_COMPONENT = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
    'strokeWidth=1.2;fontColor=#1F2937;fontStyle=1;fontSize=10;align=center;'
    'verticalAlign=middle;arcSize=15;'
)
STYLE_EDGE = (
    'endArrow=classic;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#002583;strokeWidth=1.2;fontSize=9;fontColor=#1F2937;'
    'opacity=85;'
)
STYLE_STRIDE = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#A02020;strokeColor=#A02020;'
    'strokeWidth=0;fontColor=#FFFFFF;fontStyle=1;fontSize=9;align=center;'
    'verticalAlign=middle;arcSize=40;'
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
        'Figure 18 — CJPCA Threat Model (DFD + Trust Boundaries)',
        STYLE_TITLE, 250, TITLE_Y, 1000, 30,
    ))

    # Trust zones
    for (zid, label, x, y, w, h, fill, stroke, _dashed) in ZONES:
        style = STYLE_ZONE.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(zid, '', style, x, y, w, h))
        # Zone label band at top of zone
        label_style = STYLE_ZONE_LABEL.format(stroke=stroke)
        cells.append(cell_vertex(
            zid + '_lbl', label, label_style,
            x, y + 8, w, 24,
        ))

    # Components
    for (cid, label, x, y, w, h, fill, stroke) in COMPONENTS:
        style = STYLE_COMPONENT.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(cid, label, style, x, y, w, h))

    # Flow edges
    for i, (src, tgt, lbl, _stride) in enumerate(FLOWS, start=1):
        cells.append(cell_edge(f'fl{i}', src, tgt, lbl))

    # STRIDE chips at boundary-crossing arrows
    # Place near the source side of each cross-zone arrow
    chip_positions = [
        ('S T I', 280, 360),   # Internet → Perimeter
        ('S T',   540, 360),   # Perimeter → App (boundary cross)
        ('I D',  1205, 360),   # App → LLM
        ('T',    1205, 440),   # LLM → App (return)
    ]
    for i, (stride, x, y) in enumerate(chip_positions, start=1):
        cells.append(cell_vertex(
            f'stride_chip_{i}', stride, STYLE_STRIDE,
            x, y, 50, 24,
        ))

    # STRIDE legend
    legend_style = (
        'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#7B8499;'
        'strokeWidth=1;fontColor=#1F2937;fontStyle=0;fontSize=9;align=left;'
        'verticalAlign=top;arcSize=10;'
    )
    legend_text = (
        'STRIDE legend\n'
        'S Spoofing  •  T Tampering  •  R Repudiation\n'
        'I Information disclosure  •  D Denial of service  •  E Elevation of privilege\n'
        'Red chips mark threat classes active at each trust-boundary crossing.\n'
        'Full mitigation mapping is given in Table 10.'
    )
    cells.append(cell_vertex(
        'legend', legend_text, legend_style,
        60, 830, 1410, 90,
    ))

    cells.append(cell_vertex(
        'footer',
        'Dashed boxes are trust boundaries. Arrows show data flow; chips '
        'mark which STRIDE classes are introduced at each boundary crossing.',
        STYLE_FOOTER, 100, FOOTER_Y, 1300, 30,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 18 Threat Model" id="cjpca_threat">
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
    out_path = out_dir / 'Figure_18_ThreatModel.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
