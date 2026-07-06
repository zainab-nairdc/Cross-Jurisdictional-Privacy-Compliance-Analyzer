"""Generate the CJPCA Package Decomposition Diagram as drawio XML.

Output: diagrams/Figure_A2_3_PackageDecomposition.drawio

Hierarchical 4-row layout so dependency arrows always flow downward
(or close to it) and never need to route through other packages:

  Row 1 (foundation):       accounts
  Row 2 (data + audit):     library     history
  Row 3 (pipeline):         ingestion   mapping     comparison
  Row 4 (workflow + cross): review      analytics   core

Edges are kept to the 10 essential dependencies. Arrows from row N
target packages in row N-1 (or N-2) and use orthogonal routing.

Colour scheme:
  Foundation row : light blue
  Data row       : light blue
  Pipeline row   : light purple
  Workflow row   : light orange
"""

from pathlib import Path
from xml.sax.saxutils import escape


# ── Canvas geometry ──────────────────────────────────────────────────────
PAGE_W = 1600
PAGE_H = 1100

TITLE_Y = 30
FOOTER_Y = 1050

PKG_W = 240
PKG_H = 180
PKG_GAP_X = 80

ROW_Y = {
    1: 110,   # foundation
    2: 350,   # data + audit
    3: 590,   # pipeline
    4: 830,   # workflow + cross-cutting
}


# Each package: (id, label, row, slot, fill, border, contents)
# slot is 0-indexed within its row
PACKAGES = [
    # Row 1 — foundation (1 package, centred)
    ('p_accounts', 'accounts', 1, 0, '#DBE7F5', '#2B5F9E',
     ['User', 'Profile']),

    # Row 2 — data + audit (2 packages)
    ('p_library', 'library', 2, 0, '#DBE7F5', '#2B5F9E',
     ['Document', 'Regulation', 'Policy']),
    ('p_history', 'history', 2, 1, '#DBE7F5', '#2B5F9E',
     ['AuditLog']),

    # Row 3 — pipeline (3 packages)
    ('p_ingestion',  'ingestion',  3, 0, '#E8DFF7', '#5E3FBE',
     ['IngestionJob', 'QuarantinedChunk']),
    ('p_mapping',    'mapping',    3, 1, '#E8DFF7', '#5E3FBE',
     ['MappingAnalysis', 'ObligationMapping', 'Gap']),
    ('p_comparison', 'comparison', 3, 2, '#E8DFF7', '#5E3FBE',
     ['ComparisonRun', 'ComparisonResult', 'AuditEvent']),

    # Row 4 — workflow + cross-cutting (3 packages)
    ('p_review',    'review',           4, 0, '#FFE4CC', '#B07A00',
     ['ReviewItem']),
    ('p_analytics', 'analytics',        4, 1, '#FFE4CC', '#B07A00',
     ['views: Dashboard', 'views: HeatmapData', 'views: DriftReport']),
    ('p_core',      'core (+ copilot)', 4, 2, '#FFE4CC', '#B07A00',
     ['views: CopilotMessage', 'views: CopilotScope', 'helpers: scope_state']),
]


# Essential dependencies only — 10 arrows. "→ accounts" links from
# mapping / comparison / review are implied by the foundation status and
# omitted to keep the diagram readable.
DEPENDENCIES = [
    ('p_library',    'p_accounts', 'uses User'),
    ('p_history',    'p_accounts', 'actor User'),

    ('p_ingestion',  'p_library',  'references Document'),
    ('p_mapping',    'p_library',  'Policy / Regulation'),
    ('p_comparison', 'p_library',  'Regulation'),

    ('p_review',     'p_mapping',    'reviews'),
    ('p_review',     'p_comparison', 'reviews'),

    ('p_analytics',  'p_mapping',    'aggregates'),
    ('p_analytics',  'p_comparison', 'aggregates'),

    ('p_core',       'p_library',    'reads'),
]


def packages_in_row(row: int) -> int:
    return sum(1 for p in PACKAGES if p[2] == row)


def slot_x(row: int, slot: int) -> int:
    """Compute the left-x of a package given its row + slot."""
    n = packages_in_row(row)
    total_w = n * PKG_W + (n - 1) * PKG_GAP_X
    margin = (PAGE_W - total_w) // 2
    return margin + slot * (PKG_W + PKG_GAP_X)


# ── Style strings ────────────────────────────────────────────────────────
STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#002583;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#6B7280;'
)
STYLE_PACKAGE_TEMPLATE = (
    'shape=folder;tabWidth=80;tabHeight=22;rounded=0;whiteSpace=wrap;html=1;'
    'fillColor={fill};strokeColor={border};fontColor=#002583;fontStyle=1;'
    'fontSize=12;verticalAlign=top;spacingTop=4;spacingLeft=8;'
    'strokeWidth=1.5;'
)
STYLE_MODEL = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;'
    'fontColor=#1F2937;fontSize=10;align=left;verticalAlign=middle;'
    'spacingLeft=8;'
)
# Style for view-only / behaviour-only entries (italic, lighter border)
STYLE_VIEW = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#7B8499;'
    'fontColor=#1F2937;fontSize=10;fontStyle=2;align=left;verticalAlign=middle;'
    'spacingLeft=8;dashed=0;'
)
# Edges: dashed orthogonal, label on a white-fill background so it never
# sits on top of a package or another line.
STYLE_EDGE = (
    'endArrow=open;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#1F2937;strokeWidth=1;dashed=1;fontSize=8;fontColor=#1F2937;'
    'fontStyle=2;labelBackgroundColor=#FFFFFF;verticalAlign=middle;'
    'exitX=0.5;exitY=0;exitDx=0;exitDy=0;'
    'entryX=0.5;entryY=1;entryDx=0;entryDy=0;'
)
STYLE_LEGEND_BOX = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#F4F6FB;strokeColor=#7B8499;'
    'strokeWidth=1;fontSize=9;fontColor=#1F2937;verticalAlign=top;align=left;'
    'spacingLeft=8;spacingTop=8;'
)


# ── XML builders ─────────────────────────────────────────────────────────

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
        'title', 'Figure A2.3 — Package Decomposition of the CJPCA Django Apps',
        STYLE_TITLE, 320, TITLE_Y, 960, 28,
    ))
    cells.append(cell_vertex(
        'footer',
        'Each Django app is a UML package containing its public domain '
        'models. Dashed arrows point from a dependent app to the app it '
        'depends on. Implied dependencies on accounts (from mapping, '
        'comparison, and review) are omitted to keep the diagram readable.',
        STYLE_FOOTER, 80, FOOTER_Y, 1440, 36,
    ))

    # Packages
    for (pid, label, row, slot, fill, border, models) in PACKAGES:
        x = slot_x(row, slot)
        y = ROW_Y[row]
        style = STYLE_PACKAGE_TEMPLATE.format(fill=fill, border=border)
        cells.append(cell_vertex(pid, label, style, x, y, PKG_W, PKG_H))

        # Inner cells stacked vertically inside the package.
        # Items prefixed "views:" or "helpers:" use the italic view style
        # (because the app has no Django models — it contains views only).
        inner_y = y + 40
        for i, item_label in enumerate(models):
            child_id = f'{pid}_m{i}'
            is_view = item_label.startswith(('views:', 'helpers:'))
            child_style = STYLE_VIEW if is_view else STYLE_MODEL
            child_h = 28
            cells.append(cell_vertex(
                child_id, item_label, child_style,
                x + 14, inner_y, PKG_W - 28, child_h,
            ))
            inner_y += child_h + 6

    # Legend
    legend_value = (
        '<b>Legend</b><br/>'
        'Folder shape: Django app (package)<br/>'
        'Rounded rect inside: public Django model<br/>'
        'Dashed arrow: dependency direction<br/>'
        '<br/>'
        '<i>Layer colours:</i><br/>'
        'Blue = foundation (accounts) and<br/>'
        '&nbsp;&nbsp;data (library, history)<br/>'
        'Purple = pipeline (ingestion,<br/>'
        '&nbsp;&nbsp;mapping, comparison)<br/>'
        'Orange = workflow / cross-cutting<br/>'
        '&nbsp;&nbsp;(review, analytics, core)'
    )
    cells.append(cell_vertex(
        'legend', legend_value, STYLE_LEGEND_BOX,
        PAGE_W - 280, 70, 260, 220,
    ))

    # Dependency edges (top edge of dependent → bottom edge of dependency,
    # set via the exit/entry hints in STYLE_EDGE)
    for i, (src, tgt, label) in enumerate(DEPENDENCIES, start=1):
        cells.append(cell_edge(f'd{i}', src, tgt, label))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure A2.3 Package Decomposition" id="cjpca_packages">
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
    out_path = out_dir / 'Figure_A2_3_PackageDecomposition.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
