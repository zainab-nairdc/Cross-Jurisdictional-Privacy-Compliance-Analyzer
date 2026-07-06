"""Generate Figure 23 — Audit and Hash-Chain Flow (drawio).

Output: diagrams/Figure_23_AuditHashChain.drawio

Left-to-right flow showing evidence integrity end-to-end:

  Mutating action
    → log_event signal (audit.py)
    → AuditLog row (user_role_at_time, ip, action, related_object)
    → composite indexes for fast compliance query
    → at export time, rows are SHA-256-hashed in lifecycle order;
       each export prefix chains the previous hash, producing a
       tamper-evident chain that ships with the PDF / XLSX report.
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1500
PAGE_H = 900

TITLE_Y = 20
FOOTER_Y = 850


NODES = [
    ('a_act',    'Mutating action\n(login, run job,\napprove, modify, export)',
     60, 200, 200, 100, '#E1F0F8', '#2B6E80'),

    ('a_signal', 'log_event(user, action,\nrequest, target, metadata)',
     290, 210, 240, 80, '#F4C49E', '#B05A00'),

    ('a_role',   'Snapshot at write time:\nuser_role_at_time\n+ IP via X-Forwarded-For',
     290, 320, 240, 90, '#FFE4CC', '#B05A00'),

    ('a_row',    'AuditLog row\nevent_type (28 constants)\nuser FK SET_NULL\ntimestamp + change_detail',
     560, 200, 240, 110, '#C7B3E5', '#5E3FBE'),

    ('a_idx',    'Composite indexes\n(user, -timestamp)\n(event_type, -timestamp)',
     560, 330, 240, 90, '#E8DFF7', '#5E3FBE'),

    ('a_append', 'Append-only at\napplication layer\n(no UI to edit/delete)',
     830, 200, 220, 100, '#B5E0C2', '#1B7F3A'),

    ('a_export', 'Export request\n(PDF / XLSX)',
     830, 340, 220, 80, '#FFE4CC', '#B05A00'),

    ('a_hash',   'SHA-256 over identity fields\n(action, actor, target, timestamp)\nfor each row in order',
     1080, 200, 280, 110, '#9CC5EE', '#2B5F9E'),

    ('a_chain',  'Hash chain prefix\nh_n = SHA-256( h_{n-1} || row_n )',
     1080, 330, 280, 90, '#9CC5EE', '#2B5F9E'),

    ('a_file',   'Export file ships\nwith chain root hash\n(tamper-evident)',
     1080, 460, 280, 100, '#9CC9D9', '#2B6E80'),

    ('a_jobs',   'Per-job log file\nlogs/run_<type>_<id>.log\n(full traceback)',
     560, 460, 240, 90, '#B5E0C2', '#1B7F3A'),

    ('a_admin',  'Admin inspection\n(Django admin +\nrecent activity widget)',
     830, 470, 220, 90, '#9CC9D9', '#2B6E80'),
]


EDGES = [
    ('a_act',    'a_signal',  ''),
    ('a_signal', 'a_row',     ''),
    ('a_signal', 'a_role',    'enrich'),
    ('a_role',   'a_row',     ''),
    ('a_row',    'a_idx',     ''),
    ('a_row',    'a_append',  ''),
    ('a_row',    'a_jobs',    ''),
    ('a_append', 'a_export',  ''),
    ('a_export', 'a_hash',    ''),
    ('a_hash',   'a_chain',   ''),
    ('a_chain',  'a_file',    ''),
    ('a_idx',    'a_admin',   ''),
    ('a_jobs',   'a_admin',   ''),
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
        'Figure 23 — Audit and Hash-Chain Flow',
        STYLE_TITLE, 350, TITLE_Y, 800, 30,
    ))

    for (nid, label, x, y, w, h, fill, stroke) in NODES:
        style = STYLE_NODE.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))

    for i, (src, tgt, lbl) in enumerate(EDGES, start=1):
        cells.append(cell_edge(f'h{i}', src, tgt, lbl))

    cells.append(cell_vertex(
        'footer',
        'The hash chain links each exported row to its predecessor; '
        'modifying any row invalidates every downstream hash, so '
        'post-export tampering is detectable on re-verification.',
        STYLE_FOOTER, 100, FOOTER_Y, 1300, 36,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 23 Audit Hash Chain" id="cjpca_hash">
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
    out_path = out_dir / 'Figure_23_AuditHashChain.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
