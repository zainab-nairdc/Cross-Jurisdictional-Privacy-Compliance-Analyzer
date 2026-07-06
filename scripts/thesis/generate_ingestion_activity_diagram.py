"""Generate the Ingestion Pipeline Activity Diagram as drawio XML.

Output: diagrams/Figure_A2_3d_Ingestion_Activity.drawio

Layout: vertical activity diagram with 3 swim lanes:
  Lane 1 (left):   Administrator
  Lane 2 (centre): Django web layer
  Lane 3 (right):  Ingestion pipeline (background workers)

Activity boxes flow top-to-bottom with arrows. One decision diamond for
the prompt-injection scanner: suspicious chunks go to Quarantine for
admin review, clean chunks go straight to the indexes.
"""

from pathlib import Path
from xml.sax.saxutils import escape


# ── Canvas geometry ──────────────────────────────────────────────────────
PAGE_W = 1400
PAGE_H = 1500

TITLE_Y = 30
FOOTER_Y = 1450

LANE_TOP = 90
LANE_BOTTOM = 1420

LANES = [
    # (id, label, x_start, width, bg_colour)
    ('lane_admin',   'Administrator',         60,   400, '#FAFAFA'),
    ('lane_django',  'Django web layer',      480,  400, '#F4F6FB'),
    ('lane_pipeline','Ingestion pipeline',    900,  400, '#E8DFF7'),
]


# Activity nodes:
# (id, kind, label, lane_idx, y, w, h)
#   kind: 'start' | 'end' | 'activity' | 'decision' | 'merge' | 'fork' | 'join'
ACTIVITIES = [
    ('a_start',     'start',    '',                                          0, 130, 30,  30),
    ('a_upload',    'activity', 'Upload document\n(PDF or DOCX)\nvia /library/upload/', 0, 190, 280, 70),

    ('a_create_doc','activity', 'Create Document row\n(status = PROCESSING)',  1, 190, 280, 60),
    ('a_create_job','activity', 'Create IngestionJob row\n(status = QUEUED)',  1, 280, 280, 60),
    ('a_dispatch',  'activity', 'Dispatch background worker\nvia run_job(pk)', 1, 360, 280, 60),

    ('a_extract',   'activity', 'Stage 1 — Extract text\n(PyMuPDF / python-docx)', 2, 360, 280, 60),
    ('a_ocr_dec',   'decision', 'Scanned PDF?\nno embedded text', 2, 450, 200, 70),
    ('a_ocr',       'activity', 'Stage 2 — OCR\nwith EasyOCR',  2, 560, 200, 60),

    ('a_chunk',     'activity', 'Stage 3 — Chunk\n(header split +\nsemantic merge)',  2, 660, 280, 70),
    ('a_embed',     'activity', 'Stage 4 — Embed with\nBGE-small (384-dim)',          2, 750, 280, 60),
    ('a_scan',      'activity', 'Stage 5 — Prompt-injection\nregex scanner',          2, 830, 280, 60),

    ('a_susp_dec',  'decision', 'Suspicious patterns\ndetected?', 2, 920, 200, 70),

    ('a_quarantine','activity', 'Write chunk to\nQuarantine table\n(status = PENDING)', 2, 1020, 240, 70),

    ('a_admin_review','activity', 'Review chunk in\n/ingestion/quarantine/', 0, 1020, 280, 60),
    ('a_admin_dec', 'decision', 'Approve\nchunk?', 0, 1110, 200, 70),

    ('a_index',     'activity', 'Stage 6 — Write to indexes\n(ChromaDB HNSW +\nSQLite FTS5 BM25)', 2, 1200, 280, 80),

    ('a_set_indexed','activity','Document.status = INDEXED\nIngestionJob.status = COMPLETE', 1, 1280, 280, 60),

    ('a_searchable','activity', 'Document is searchable\nin the library', 0, 1280, 280, 60),
    ('a_end',       'end',      '',                                          0, 1360, 30,  30),
]


# Flow edges: (source, target, label)
EDGES = [
    ('a_start',     'a_upload',     ''),
    ('a_upload',    'a_create_doc', ''),
    ('a_create_doc','a_create_job', ''),
    ('a_create_job','a_dispatch',   ''),
    ('a_dispatch',  'a_extract',    ''),
    ('a_extract',   'a_ocr_dec',    ''),
    ('a_ocr_dec',   'a_ocr',        'yes'),
    ('a_ocr',       'a_chunk',      ''),
    ('a_ocr_dec',   'a_chunk',      'no'),
    ('a_chunk',     'a_embed',      ''),
    ('a_embed',     'a_scan',       ''),
    ('a_scan',      'a_susp_dec',   ''),
    ('a_susp_dec',  'a_index',      'no'),
    ('a_susp_dec',  'a_quarantine', 'yes'),
    ('a_quarantine','a_admin_review',''),
    ('a_admin_review','a_admin_dec',''),
    ('a_admin_dec', 'a_index',      'yes'),
    ('a_admin_dec', 'a_end',        'no\n(reject + audit log)'),
    ('a_index',     'a_set_indexed',''),
    ('a_set_indexed','a_searchable',''),
    ('a_searchable','a_end',        ''),
]


# ── Style strings ────────────────────────────────────────────────────────
STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#002583;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#6B7280;'
)
STYLE_LANE = (
    'rounded=0;whiteSpace=wrap;html=1;fillColor={bg};strokeColor=#7B8499;'
    'strokeWidth=1;fontColor=#002583;fontStyle=1;fontSize=12;verticalAlign=top;'
    'spacingTop=8;dashed=0;'
)
STYLE_START = (
    'ellipse;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#000000;'
)
STYLE_END = (
    'ellipse;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;'
    'strokeWidth=3;'
)
STYLE_ACTIVITY = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#002583;'
    'fontColor=#1F2937;fontSize=10;align=center;verticalAlign=middle;'
    'strokeWidth=1.5;arcSize=20;'
)
STYLE_DECISION = (
    'rhombus;whiteSpace=wrap;html=1;fillColor=#FFF6E0;strokeColor=#B07A00;'
    'fontColor=#1F2937;fontSize=10;align=center;verticalAlign=middle;'
    'strokeWidth=1.5;'
)
STYLE_EDGE = (
    'endArrow=open;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#1F2937;strokeWidth=1;fontSize=9;fontColor=#1F2937;'
    'labelBackgroundColor=#FFFFFF;verticalAlign=middle;'
)


def lane_centre_x(lane_idx: int) -> int:
    lane = LANES[lane_idx]
    return lane[2] + lane[3] // 2


def node_x(node_id: str, lane_idx: int, w: int) -> int:
    """Centre a node within its lane."""
    return lane_centre_x(lane_idx) - w // 2


# ── XML helpers ──────────────────────────────────────────────────────────

def cell_vertex(cell_id: str, value: str, style: str,
                x: int, y: int, w: int, h: int) -> str:
    return (
        f'        <mxCell id="{cell_id}" value="{escape(value)}" '
        f'style="{style}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
        f'as="geometry" />\n'
        f'        </mxCell>'
    )


def cell_edge(edge_id: str, source: str, target: str, label: str) -> str:
    label_attr = f' value="{escape(label)}"' if label else ''
    return (
        f'        <mxCell id="{edge_id}"{label_attr} style="{STYLE_EDGE}" '
        f'edge="1" source="{source}" target="{target}" parent="1">\n'
        f'          <mxGeometry relative="1" as="geometry" />\n'
        f'        </mxCell>'
    )


def build_xml() -> str:
    cells: list[str] = []

    # Title and footer
    cells.append(cell_vertex(
        'title', 'Figure A2.3d — Document Ingestion Pipeline',
        STYLE_TITLE, 360, TITLE_Y, 680, 28,
    ))
    cells.append(cell_vertex(
        'footer',
        'Three swim lanes: Administrator (left), Django web layer (centre), '
        'and Ingestion pipeline (right). Six stages, one OCR branch, one '
        'quarantine branch for suspicious chunks.',
        STYLE_FOOTER, 60, FOOTER_Y, 1280, 36,
    ))

    # Swim lanes (rendered as tall background rectangles)
    for (lid, label, x, w, bg) in LANES:
        style = STYLE_LANE.format(bg=bg)
        cells.append(cell_vertex(
            lid, label, style,
            x, LANE_TOP, w, LANE_BOTTOM - LANE_TOP,
        ))

    # Activity / start / end / decision nodes
    for (nid, kind, label, lane_idx, y, w, h) in ACTIVITIES:
        style = {
            'start':    STYLE_START,
            'end':      STYLE_END,
            'activity': STYLE_ACTIVITY,
            'decision': STYLE_DECISION,
        }[kind]
        x = node_x(nid, lane_idx, w)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))

    # Flow edges
    for i, (src, tgt, label) in enumerate(EDGES, start=1):
        cells.append(cell_edge(f'e{i}', src, tgt, label))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure A2.3d Ingestion Activity" id="cjpca_ingestion">
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


def main() -> None:
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'diagrams'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'Figure_A2_3d_Ingestion_Activity.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
