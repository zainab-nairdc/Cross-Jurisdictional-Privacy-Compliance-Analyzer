"""Generate the CJPCA Deployment Diagram as drawio XML.

Output: diagrams/Figure_D3_Deployment.drawio

Layout:
  - User actor on the LEFT
  - User-device node next to the actor (browser inside)
  - Deployment host node (large) in the centre-right containing:
        * Python venv with Django ASGI + background workers (top region)
        * 3 data store cylinders (middle region: ChromaDB, SQLite FTS5,
          Django SQLite)
        * Ollama daemon (bottom region)
  - Trust boundary = dashed rectangle around the entire host
  - Every connection labelled with its communication protocol
  - Title at top, footer caption at bottom, legend in top-right corner

After running:
  1. Open diagrams/Figure_D3_Deployment.drawio in https://app.diagrams.net
  2. Drag any line that still looks awkward
  3. File -> Export as -> PNG -> save as Figure_D3_Deployment.drawio.png
"""

from pathlib import Path
from xml.sax.saxutils import escape


# ── Canvas geometry ──────────────────────────────────────────────────────
PAGE_W = 1500
PAGE_H = 900

TITLE_Y       = 30
FOOTER_Y      = 850

# User device (left side)
USER_X, USER_Y, USER_W, USER_H        = 60,  300, 40,  60
DEVICE_X, DEVICE_Y, DEVICE_W, DEVICE_H = 160, 260, 200, 140
BROWSER_X, BROWSER_Y, BROWSER_W, BROWSER_H = 180, 305, 160, 80

# Deployment host (centre-right)
HOST_X, HOST_Y, HOST_W, HOST_H = 450, 140, 990, 600

# Inside the host: Python venv on top, data stores middle, Ollama bottom
VENV_X,   VENV_Y,   VENV_W,   VENV_H   = 480, 180, 540, 150
DJANGO_X, DJANGO_Y, DJANGO_W, DJANGO_H = 510, 215, 240, 100
WORK_X,   WORK_Y,   WORK_W,   WORK_H   = 770, 215, 220, 100

CHROMA_X, CHROMA_Y, CHROMA_W, CHROMA_H   = 490,  380, 200, 140
FTS5_X,   FTS5_Y,   FTS5_W,   FTS5_H     = 720,  380, 200, 140
DJDB_X,   DJDB_Y,   DJDB_W,   DJDB_H     = 950,  380, 200, 140

OLLAMA_X, OLLAMA_Y, OLLAMA_W, OLLAMA_H   = 1180, 215, 230, 305

# Trust boundary (dashed, slightly larger than host)
TB_X, TB_Y, TB_W, TB_H = HOST_X - 12, HOST_Y - 12, HOST_W + 24, HOST_H + 24


# ── Style strings (master style guide colours) ──────────────────────────
STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#002583;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#6B7280;'
)
# External actor — light gray
STYLE_ACTOR = (
    'shape=umlActor;verticalLabelPosition=bottom;labelBackgroundColor=#FFFFFF;'
    'verticalAlign=top;html=1;outlineConnect=0;fontStyle=1;fontSize=11;'
    'fontColor=#1F2937;strokeColor=#7B8499;fillColor=#F4F6FB;'
)
# User device + Deployment host — white containers, navy border
STYLE_NODE_DEVICE = (
    'shape=cube;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;'
    'darkOpacity=0.05;fillColor=#FFFFFF;strokeColor=#002583;fontColor=#002583;'
    'fontStyle=1;fontSize=11;verticalAlign=top;spacingTop=4;strokeWidth=1.5;'
)
STYLE_NODE_HOST = (
    'shape=cube;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;'
    'darkOpacity=0.05;fillColor=#FFFFFF;strokeColor=#002583;fontColor=#002583;'
    'fontStyle=1;fontSize=12;verticalAlign=top;spacingTop=4;strokeWidth=2;'
)
# Python venv sub-grouping — dashed light gray
STYLE_NODE_VENV = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#F4F6FB;strokeColor=#7B8499;'
    'fontColor=#1F2937;fontStyle=2;fontSize=10;verticalAlign=top;'
    'spacingTop=4;dashed=1;'
)
# Web-layer component — light blue
STYLE_COMPONENT_WEB = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#DBE7F5;strokeColor=#2B5F9E;'
    'fontColor=#1F2937;fontSize=10;align=center;verticalAlign=middle;'
)
# Background workers — light purple (orchestration / background)
STYLE_COMPONENT_WORKERS = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#E8DFF7;strokeColor=#5E3FBE;'
    'fontColor=#1F2937;fontSize=10;align=center;verticalAlign=middle;'
)
# Data stores — light green cylinders
STYLE_CYLINDER = (
    'shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;'
    'size=15;fillColor=#E1F4E5;strokeColor=#1B7F3A;fontColor=#1F2937;fontSize=10;'
    'align=center;verticalAlign=middle;'
)
# Ollama daemon — light orange (AI service)
STYLE_OLLAMA = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE4CC;strokeColor=#B07A00;'
    'fontColor=#1F2937;fontStyle=1;fontSize=10;align=center;verticalAlign=middle;'
)
# Trust boundary — dashed red
STYLE_TRUST_BOUNDARY = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#D93939;'
    'strokeWidth=1.5;dashed=1;dashPattern=8 4;fontColor=#D93939;'
    'fontStyle=2;fontSize=10;verticalAlign=top;align=right;spacingTop=2;'
    'spacingRight=8;'
)
# Legend — light gray box
STYLE_LEGEND_BOX = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#F4F6FB;strokeColor=#7B8499;'
    'strokeWidth=1;fontSize=9;fontColor=#1F2937;verticalAlign=top;align=left;'
    'spacingLeft=8;spacingTop=8;'
)
# Edges — navy lines
STYLE_EDGE = (
    'endArrow=open;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#002583;strokeWidth=1;fontSize=9;fontColor=#1F2937;'
    'labelBackgroundColor=#FFFFFF;verticalAlign=middle;'
)


# Connections: (source_id, target_id, label)
CONNECTIONS = [
    ('user',      'browser', 'Workstation'),
    ('browser',   'django',  'HTTPS / TLS 1.3'),

    ('django',    'chroma',  'In-process API\n+ file I/O'),
    ('django',    'fts5',    'SQLite C API\n+ file I/O'),
    ('django',    'djdb',    'Django ORM\n+ file I/O'),
    ('django',    'ollama',  'HTTP\nlocalhost:11434'),

    ('workers',   'chroma',  'In-process API'),
    ('workers',   'fts5',    'SQLite C API'),
    ('workers',   'djdb',    'Django ORM'),
]


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


def cell_edge(edge_id: str, source: str, target: str, label: str,
              style: str = STYLE_EDGE) -> str:
    value_attr = f' value="{escape(label)}"'
    return (
        f'        <mxCell id="{edge_id}"{value_attr} style="{style}" '
        f'edge="1" source="{source}" target="{target}" parent="1">\n'
        f'          <mxGeometry relative="1" as="geometry" />\n'
        f'        </mxCell>'
    )


def build_xml() -> str:
    cells: list[str] = []

    # Title
    cells.append(cell_vertex(
        'title', 'Figure 5 — Deployment Diagram of the CJPCA System',
        STYLE_TITLE, 400, TITLE_Y, 700, 28,
    ))

    # Footer caption
    cells.append(cell_vertex(
        'footer',
        'Single-host on-premises deployment. Every connection is labelled '
        'with its communication protocol.',
        STYLE_FOOTER, 280, FOOTER_Y, 940, 20,
    ))

    # Trust boundary (drawn first, behind everything else)
    cells.append(cell_vertex(
        'trust_boundary',
        '<b>Trust boundary (host perimeter)</b>',
        STYLE_TRUST_BOUNDARY,
        TB_X, TB_Y, TB_W, TB_H,
    ))

    # User actor
    cells.append(cell_vertex(
        'user', 'User\n(Analyst / Reviewer / Admin)',
        STYLE_ACTOR, USER_X, USER_Y, USER_W, USER_H,
    ))

    # User device node
    cells.append(cell_vertex(
        'user_device', 'User device',
        STYLE_NODE_DEVICE, DEVICE_X, DEVICE_Y, DEVICE_W, DEVICE_H,
    ))
    # Browser component inside the device (web — light blue)
    cells.append(cell_vertex(
        'browser', 'Web browser\n(HTMX + Alpine.js)',
        STYLE_COMPONENT_WEB, BROWSER_X, BROWSER_Y, BROWSER_W, BROWSER_H,
    ))

    # Deployment host node
    cells.append(cell_vertex(
        'host',
        'Deployment host (Linux server, on-premises BBK datacentre)',
        STYLE_NODE_HOST, HOST_X, HOST_Y, HOST_W, HOST_H,
    ))

    # Python venv sub-node inside the host
    cells.append(cell_vertex(
        'venv', 'Python 3.13 venv (application process)',
        STYLE_NODE_VENV, VENV_X, VENV_Y, VENV_W, VENV_H,
    ))

    # Django ASGI (web layer — light blue) and background workers (purple)
    cells.append(cell_vertex(
        'django',
        '<b>Django ASGI</b><br/>:8000<br/>RBAC + 2FA + CSRF',
        STYLE_COMPONENT_WEB, DJANGO_X, DJANGO_Y, DJANGO_W, DJANGO_H,
    ))
    cells.append(cell_vertex(
        'workers',
        '<b>Background workers</b><br/>(ingestion pipeline)',
        STYLE_COMPONENT_WORKERS, WORK_X, WORK_Y, WORK_W, WORK_H,
    ))

    # Data store cylinders
    cells.append(cell_vertex(
        'chroma',
        '<b>ChromaDB</b><br/>HNSW · 384-dim<br/>vector index',
        STYLE_CYLINDER, CHROMA_X, CHROMA_Y, CHROMA_W, CHROMA_H,
    ))
    cells.append(cell_vertex(
        'fts5',
        '<b>SQLite FTS5</b><br/>bm25_index<br/>(BM25 ranking)',
        STYLE_CYLINDER, FTS5_X, FTS5_Y, FTS5_W, FTS5_H,
    ))
    cells.append(cell_vertex(
        'djdb',
        '<b>Django SQLite</b><br/>db.sqlite3<br/>(users · models · audit log)',
        STYLE_CYLINDER, DJDB_X, DJDB_Y, DJDB_W, DJDB_H,
    ))

    # Ollama daemon
    cells.append(cell_vertex(
        'ollama',
        '<b>Ollama daemon</b><br/>:11434<br/>llama3.2:1b<br/>llama3.2:latest',
        STYLE_OLLAMA, OLLAMA_X, OLLAMA_Y, OLLAMA_W, OLLAMA_H,
    ))

    # Legend box (top-right corner). Plain text, no emoji.
    legend_value = (
        '<b>Legend</b><br/>'
        '3D box: deployment node<br/>'
        'Cylinder: data store (persistent)<br/>'
        'Rounded box: software component<br/>'
        'Stick figure: external actor<br/>'
        'Dashed red rectangle: trust boundary<br/>'
        '<br/>'
        '<i>Fills by role:</i><br/>'
        'Blue = web layer<br/>'
        'Purple = background / orchestration<br/>'
        'Green = data store<br/>'
        'Orange = AI service'
    )
    cells.append(cell_vertex(
        'legend', legend_value,
        STYLE_LEGEND_BOX, PAGE_W - 290, 60, 270, 200,
    ))

    # Connection edges with protocol labels
    for i, (src, tgt, label) in enumerate(CONNECTIONS, start=1):
        cells.append(cell_edge(f'e{i}', src, tgt, label))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure D3 Deployment" id="cjpca_deployment">
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
    out_path = out_dir / 'Figure_D3_Deployment.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
