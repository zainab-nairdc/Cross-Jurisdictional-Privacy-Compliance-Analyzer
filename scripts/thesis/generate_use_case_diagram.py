"""Generate the CJPCA Use Case Diagram as drawio XML.

Output: diagrams/Figure_D2_UseCase.drawio

Two-column layout:

  LEFT column (most of the canvas):
      Analyst band     ← top
      Reviewer band 1  ← Validate / Approve-reject / Edit severity
      Reviewer band 2  ← Add note / Compare clauses / Download report
      Shared band      ← 4 shared use cases
      Helpers band     ← 3 helpers (include / extend targets)

  RIGHT column (narrow strip on the right side):
      Admin's 4 use cases stacked vertically.

  Compliance Analyst and Legal Reviewer sit to the LEFT of the boundary,
  Administrator sits to the RIGHT of the boundary. Each actor's lines
  reach use cases that are physically near them, reducing crossings.

After running:
  1. Open diagrams/Figure_D2_UseCase.drawio in https://app.diagrams.net
  2. Drag any line that still looks awkward
  3. File -> Export as -> PNG -> save as Figure_D2_UseCase.drawio.png
"""

from pathlib import Path
from xml.sax.saxutils import escape


# ── Canvas geometry ──────────────────────────────────────────────────────
PAGE_W = 1500
PAGE_H = 1000

BOUNDARY_X = 180
BOUNDARY_Y = 80
BOUNDARY_W = 1140
BOUNDARY_H = 820

USE_CASE_W = 160
USE_CASE_H = 55

ACTOR_W = 40
ACTOR_H = 60

# Where the left-column use cases live (x range)
LEFT_X_START = BOUNDARY_X + 30
LEFT_X_END   = BOUNDARY_X + 770   # everything left of this is the left column
# Where the right-column (Admin) use cases live
RIGHT_X_START = BOUNDARY_X + BOUNDARY_W - 200  # narrow right strip
ADMIN_COLUMN_CENTRE = RIGHT_X_START + USE_CASE_W // 2 - 80


# Band centre y-coordinates for the LEFT-column bands
BAND_Y = {
    'analyst':    155,
    'reviewer1':  275,   # Validate / Approve-reject / Edit severity
    'reviewer2':  385,   # Add note / Compare clauses / Download report
    'shared':     510,
    'helper':     650,
}

# Admin's use cases are stacked vertically on the right
ADMIN_Y_START = 180
ADMIN_Y_STEP  = 100   # spacing between Admin use cases vertically

# Slot counts per band (for x-spacing within the left column)
LEFT_SLOT_COUNT = {
    'analyst':   3,
    'reviewer1': 3,
    'reviewer2': 3,
    'shared':    4,
    'helper':    3,
}


# Actor positions (figure top-left)
ACTORS = [
    # id,             label,                x,    y
    ('actor_analyst',  'Compliance Analyst',  60, 130),
    ('actor_reviewer', 'Legal Reviewer',      60, 320),
    ('actor_admin',    'Administrator',     1410, 360),   # right side
]


# Each use case: id, label, band, slot
# Bands: analyst / reviewer1 / reviewer2 / shared / helper -> left column
#        admin -> stacked on the right column (slot = vertical position 0..N)
USE_CASES = [
    # Analyst band (3 use cases)
    ('uc_run_mapping',     'Run policy mapping',           'analyst',  0),
    ('uc_run_comparison',  'Run regulation comparison',    'analyst',  1),
    ('uc_submit',          'Submit analysis for review',   'analyst',  2),

    # Reviewer band 1 (3 use cases)
    ('uc_validate',        'Validate AI finding',          'reviewer1', 0),
    ('uc_approve',         'Approve / reject finding',     'reviewer1', 1),
    ('uc_edit_severity',   'Edit severity and due date',   'reviewer1', 2),

    # Reviewer band 2 (3 use cases)
    ('uc_note',            'Add reviewer note',                    'reviewer2', 0),
    ('uc_compare_clauses', 'Compare clauses across jurisdictions', 'reviewer2', 1),
    ('uc_download',        'Download approved report',             'reviewer2', 2),

    # Shared band (4 use cases)
    ('uc_copilot',         'Ask Copilot',              'shared', 0),
    ('uc_audit',           'View audit log',           'shared', 1),
    ('uc_library',         'Browse library',           'shared', 2),
    ('uc_analytics',       'View analytics dashboard', 'shared', 3),

    # Admin column (4 use cases stacked vertically on the right)
    ('uc_upload',          'Upload documents',           'admin', 0),
    ('uc_manage_users',    'Manage users and MFA',       'admin', 1),
    ('uc_monitor',         'Monitor system health',      'admin', 2),
    ('uc_quarantine',      'Review quarantined content', 'admin', 3),

    # Helper band (3 use cases — reached only via include / extend)
    ('uc_verify_cites',    'Verify citations',           'helper', 0),
    ('uc_gen_hash',        'Generate audit hash',        'helper', 1),
    ('uc_auto_route',      'Auto-detect relevant regulations',  'helper', 2),
]


ASSOCIATIONS = {
    'actor_analyst': [
        'uc_run_mapping', 'uc_run_comparison', 'uc_submit',
        'uc_copilot', 'uc_audit', 'uc_library', 'uc_analytics',
    ],
    'actor_reviewer': [
        'uc_validate', 'uc_approve', 'uc_edit_severity',
        'uc_note', 'uc_compare_clauses', 'uc_download',
        'uc_copilot', 'uc_audit', 'uc_library', 'uc_analytics',
    ],
    'actor_admin': [
        'uc_upload', 'uc_manage_users', 'uc_monitor', 'uc_quarantine',
        # Admin does NOT use Ask Copilot
        'uc_audit', 'uc_library', 'uc_analytics',
    ],
}


# Include / Extend relationships: list of (source_id, target_id, label)
INCLUDE_EXTEND = [
    ('uc_run_mapping', 'uc_verify_cites', '«include»'),
    ('uc_download',    'uc_gen_hash',     '«include»'),
    ('uc_auto_route',  'uc_run_mapping',  '«extend»'),
]


# ── Style strings ────────────────────────────────────────────────────────
STYLE_ACTOR = (
    'shape=umlActor;verticalLabelPosition=bottom;labelBackgroundColor=#FFFFFF;'
    'verticalAlign=top;html=1;outlineConnect=0;fontStyle=1;fontSize=11;'
    'fontColor=#000000;strokeColor=#000000;'
)
STYLE_BOUNDARY = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;'
    'strokeWidth=2;fontStyle=1;fontSize=13;fontColor=#000000;verticalAlign=top;'
    'spacingTop=8;arcSize=4;'
)
STYLE_USE_CASE = (
    'ellipse;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;'
    'strokeWidth=1;fontColor=#000000;fontSize=10;align=center;verticalAlign=middle;'
)
STYLE_HELPER = (
    'ellipse;whiteSpace=wrap;html=1;fillColor=#F4F4F4;strokeColor=#000000;'
    'strokeWidth=1;fontColor=#000000;fontSize=10;align=center;verticalAlign=middle;'
    'fontStyle=2;'
)
STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#000000;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#555555;'
)
STYLE_BAND_LABEL = (
    'text;html=1;align=left;verticalAlign=middle;fontStyle=2;fontSize=10;'
    'fontColor=#555555;'
)
STYLE_LEGEND_BOX = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#FAFAFA;strokeColor=#000000;'
    'strokeWidth=1;fontSize=9;fontColor=#000000;verticalAlign=top;align=left;'
    'spacingLeft=8;spacingTop=8;'
)
STYLE_EDGE_ASSOC = (
    'endArrow=none;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#000000;strokeWidth=1;fontSize=9;'
)
STYLE_EDGE_INCLUDE_EXTEND = (
    'endArrow=open;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#000000;strokeWidth=1;dashed=1;fontStyle=2;fontSize=9;'
    'verticalAlign=bottom;labelBackgroundColor=#FFFFFF;'
)


# ── Geometry helpers ─────────────────────────────────────────────────────

def use_case_position(band: str, slot: int) -> tuple[int, int]:
    """Return (x, y) for the top-left of a use case ellipse."""
    if band == 'admin':
        # Right column, stacked vertically
        x = RIGHT_X_START
        y = ADMIN_Y_START + slot * ADMIN_Y_STEP - USE_CASE_H // 2
        return x, y
    # Left column bands
    n = LEFT_SLOT_COUNT[band]
    inner_w = LEFT_X_END - LEFT_X_START
    slot_centre = LEFT_X_START + (slot + 0.5) * (inner_w / n)
    x = int(slot_centre - USE_CASE_W / 2)
    y = int(BAND_Y[band] - USE_CASE_H / 2)
    return x, y


# ── XML builder ──────────────────────────────────────────────────────────

def cell_vertex(cell_id: str, value: str, style: str,
                x: int, y: int, w: int, h: int) -> str:
    return (
        f'        <mxCell id="{cell_id}" value="{escape(value)}" '
        f'style="{style}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
        f'as="geometry" />\n'
        f'        </mxCell>'
    )


def cell_edge(edge_id: str, source: str, target: str, style: str,
              label: str = '') -> str:
    value_attr = f' value="{escape(label)}"' if label else ''
    return (
        f'        <mxCell id="{edge_id}"{value_attr} style="{style}" '
        f'edge="1" source="{source}" target="{target}" parent="1">\n'
        f'          <mxGeometry relative="1" as="geometry" />\n'
        f'        </mxCell>'
    )


def build_xml() -> str:
    cells: list[str] = []

    # Title and footer
    cells.append(cell_vertex(
        'title', 'Figure 4 — CJPCA Use Case Diagram',
        STYLE_TITLE, 460, 24, 580, 28,
    ))
    cells.append(cell_vertex(
        'footer',
        'Three user roles and their core interactions with the system.',
        STYLE_FOOTER, 370, 920, 760, 20,
    ))

    # System boundary
    cells.append(cell_vertex(
        'boundary', 'CJPCA', STYLE_BOUNDARY,
        BOUNDARY_X, BOUNDARY_Y, BOUNDARY_W, BOUNDARY_H,
    ))

    # Band labels (small italic on the left of each band, just above)
    band_labels = {
        'analyst':    'Analyst',
        'reviewer1':  'Reviewer',
        'shared':     'Shared',
        'helper':     'Helpers (include / extend targets)',
    }
    for band, label in band_labels.items():
        y = BAND_Y[band] - 50
        cells.append(cell_vertex(
            f'band_{band}_label', label, STYLE_BAND_LABEL,
            BOUNDARY_X + 12, y, 280, 18,
        ))
    # Admin column label (top of the right strip)
    cells.append(cell_vertex(
        'band_admin_label', 'Admin', STYLE_BAND_LABEL,
        RIGHT_X_START, ADMIN_Y_START - 50, 100, 18,
    ))

    # Actors
    for (aid, label, x, y) in ACTORS:
        cells.append(cell_vertex(
            aid, label, STYLE_ACTOR, x, y, ACTOR_W, ACTOR_H,
        ))

    # Use cases
    for (uc_id, label, band, slot) in USE_CASES:
        x, y = use_case_position(band, slot)
        style = STYLE_HELPER if band == 'helper' else STYLE_USE_CASE
        cells.append(cell_vertex(
            uc_id, label, style, x, y, USE_CASE_W, USE_CASE_H,
        ))

    # Legend box (top-right corner of the canvas, above the boundary)
    legend_x = PAGE_W - 290
    legend_y = 20
    legend_value = (
        '<b>Legend</b><br/>'
        '— Solid line: association (actor uses the case)<br/>'
        '⤳ Dashed «include»: always part of base<br/>'
        '⤳ Dashed «extend»: optional extension'
    )
    cells.append(cell_vertex(
        'legend', legend_value, STYLE_LEGEND_BOX,
        legend_x, legend_y, 260, 76,
    ))

    # Association edges
    edge_id = 0
    for actor_id, uc_ids in ASSOCIATIONS.items():
        for uc_id in uc_ids:
            edge_id += 1
            cells.append(cell_edge(
                f'e{edge_id}', actor_id, uc_id, STYLE_EDGE_ASSOC,
            ))

    # Include / Extend edges
    for src, tgt, label in INCLUDE_EXTEND:
        edge_id += 1
        cells.append(cell_edge(
            f'e{edge_id}', src, tgt, STYLE_EDGE_INCLUDE_EXTEND, label,
        ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure D2 UseCase" id="cjpca_usecase">
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
    out_path = out_dir / 'Figure_D2_UseCase.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
