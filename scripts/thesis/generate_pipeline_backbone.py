"""Generate the AI Pipeline Backbone diagram as drawio XML.

Output: diagrams/Figure_A2_3_AI_Pipeline_Backbone.drawio

A left-to-right block diagram in five vertical bands:

  Band 1 (inputs):       Documents, Query
  Band 2 (offline):      Ingestion phase  ─→  feeds the corpus
  Band 3 (corpus):       ChromaDB HNSW + SQLite FTS5
  Band 4 (online):       Retrieval phase  →  Reasoning phase
  Band 5 (output):       Verified answer

Each phase component references its detailed figure (A2.3d, A2.3e, A2.3f).
"""

from pathlib import Path
from xml.sax.saxutils import escape


# ── Canvas geometry ──────────────────────────────────────────────────────
PAGE_W = 1600
PAGE_H = 900

TITLE_Y = 30
FOOTER_Y = 850


# Outer container blocks (phase wrappers): (id, label, x, y, w, h, fill)
PHASE_BLOCKS = [
    ('block_offline', 'Offline  (runs once per document)',
     320, 110, 260, 660, '#FFF6E0'),
    ('block_corpus',  'Stored corpus  (kept on disk)',
     620, 110, 280, 660, '#F4F6FB'),
    ('block_online',  'Online  (runs for each question)',
     940, 110, 360, 660, '#E1F0F8'),
]


# Inner components (id, label, x, y, w, h, style_key)
COMPONENTS = [
    # Input actors (left band)
    ('act_docs',     'Documents\nuploaded\nby admin',
     80, 220, 180, 90, 'input'),
    ('act_query',    'Question\nasked\nby user',
     80, 540, 180, 90, 'input'),

    # Offline phase — Ingestion component (inside block_offline)
    ('comp_ingestion',
     '<b>Ingestion</b>\n(Figure A2.3d)\n\nRead the file,\nsplit it into chunks,\nlearn each chunk,\nsave to the corpus',
     345, 300, 210, 280, 'ingestion'),

    # Corpus stores (inside block_corpus)
    ('db_chroma',
     '<b>Meaning index</b>\n(ChromaDB)\n\nfinds chunks\nby meaning',
     650, 210, 220, 150, 'cylinder'),
    ('db_fts5',
     '<b>Word index</b>\n(SQLite FTS5)\n\nfinds chunks\nby keyword',
     650, 520, 220, 150, 'cylinder'),

    # Online phase — Retrieval and Reasoning (inside block_online)
    ('comp_retrieval',
     '<b>Retrieval</b>\n(Figure A2.3e)\n\nLook up the\nbest chunks\nfor the question',
     965, 230, 200, 200, 'retrieval'),
    ('comp_reasoning',
     '<b>Reasoning</b>\n(Figure A2.3f)\n\nDraft an answer,\ncheck it, fix it,\nfinalise it',
     965, 470, 200, 200, 'reasoning'),

    # Output (right band)
    ('act_answer',
     'Final answer\nwith sources\nand a\nconfidence score',
     1380, 380, 190, 130, 'output'),
]


# Flows: (source, target, label)
FLOWS = [
    ('act_docs',       'comp_ingestion', 'upload'),
    ('comp_ingestion', 'db_chroma',      'save meanings'),
    ('comp_ingestion', 'db_fts5',        'save words'),

    ('act_query',      'comp_retrieval', 'ask'),
    ('db_chroma',      'comp_retrieval', 'matches'),
    ('db_fts5',        'comp_retrieval', 'matches'),
    ('comp_retrieval', 'comp_reasoning', 'top chunks'),

    ('comp_reasoning', 'act_answer',     'answer'),
]


# ── Styles ───────────────────────────────────────────────────────────────
STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=15;'
    'fontColor=#002583;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#6B7280;'
)
STYLE_PHASE_BLOCK_TEMPLATE = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor=#7B8499;'
    'strokeWidth=1.5;fontColor=#002583;fontStyle=1;fontSize=11;verticalAlign=top;'
    'spacingTop=10;dashed=1;dashPattern=8 4;'
)
STYLE_INPUT = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#F4F6FB;strokeColor=#7B8499;'
    'strokeWidth=1;fontColor=#1F2937;fontStyle=1;fontSize=11;align=center;'
    'verticalAlign=middle;arcSize=20;'
)
STYLE_OUTPUT = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#E1F4E5;strokeColor=#1B7F3A;'
    'strokeWidth=1.5;fontColor=#1F2937;fontStyle=1;fontSize=11;align=center;'
    'verticalAlign=middle;arcSize=20;'
)
STYLE_INGESTION = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#E8DFF7;strokeColor=#5E3FBE;'
    'strokeWidth=1.5;fontColor=#1F2937;fontSize=11;align=center;'
    'verticalAlign=middle;arcSize=15;'
)
STYLE_RETRIEVAL = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#DBE7F5;strokeColor=#2B5F9E;'
    'strokeWidth=1.5;fontColor=#1F2937;fontSize=11;align=center;'
    'verticalAlign=middle;arcSize=15;'
)
STYLE_REASONING = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE4CC;strokeColor=#B07A00;'
    'strokeWidth=1.5;fontColor=#1F2937;fontSize=11;align=center;'
    'verticalAlign=middle;arcSize=15;'
)
STYLE_CYLINDER = (
    'shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;'
    'size=15;fillColor=#E1F4E5;strokeColor=#1B7F3A;fontColor=#1F2937;fontSize=10;'
    'align=center;verticalAlign=middle;'
)
STYLE_EDGE = (
    'endArrow=open;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#002583;strokeWidth=1.5;fontSize=9;fontColor=#1F2937;'
    'fontStyle=1;labelBackgroundColor=#FFFFFF;verticalAlign=middle;'
)


STYLES_BY_KEY = {
    'input':     STYLE_INPUT,
    'output':    STYLE_OUTPUT,
    'ingestion': STYLE_INGESTION,
    'retrieval': STYLE_RETRIEVAL,
    'reasoning': STYLE_REASONING,
    'cylinder':  STYLE_CYLINDER,
}


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

    # Title + footer
    cells.append(cell_vertex(
        'title',
        'Figure A2.3 — AI Pipeline Backbone: Ingestion · Retrieval · Reasoning',
        STYLE_TITLE, 280, TITLE_Y, 1040, 30,
    ))
    cells.append(cell_vertex(
        'footer',
        'The pipeline has two halves. Documents are read and stored once, '
        'offline. Each new question is answered online by looking up the '
        'best chunks and reasoning over them.',
        STYLE_FOOTER, 100, FOOTER_Y, 1400, 36,
    ))

    # Phase wrapper blocks (drawn behind components)
    for (bid, label, x, y, w, h, fill) in PHASE_BLOCKS:
        style = STYLE_PHASE_BLOCK_TEMPLATE.format(fill=fill)
        cells.append(cell_vertex(bid, label, style, x, y, w, h))

    # Inner components. Labels may contain HTML like <b>...</b>; cell_vertex
    # escapes them to &lt;b&gt; in the XML attribute. drawio un-escapes back
    # to <b> at render time and applies the bold because html=1 is set.
    for (cid, label, x, y, w, h, key) in COMPONENTS:
        style = STYLES_BY_KEY[key]
        cells.append(cell_vertex(cid, label, style, x, y, w, h))

    # Flow arrows
    for i, (src, tgt, label) in enumerate(FLOWS, start=1):
        cells.append(cell_edge(f'f{i}', src, tgt, label))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure A2.3 AI Pipeline Backbone" id="cjpca_backbone">
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
    out_path = out_dir / 'Figure_6_AI_Pipeline_Backbone.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
