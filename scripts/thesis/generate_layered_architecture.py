"""Generate Figure 15 — CJPCA Layered Architecture Diagram (drawio).

Output: diagrams/Figure_15_LayeredArchitecture.drawio

Six horizontal bands, top-to-bottom data flow:
  1. Ingestion          (light green)
  2. Preprocessing      (light purple)
  3. Embedding & index  (light blue)
  4. Retrieval          (light amber)
  5. Reasoning agent    (light orange)
  6. Output & workflows (light teal)

Each band has a left label and a row of component boxes. Arrows
between bands show data flow.
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1400
PAGE_H = 1100

TITLE_Y = 20
FOOTER_Y = 1050

BAND_LABEL_W = 130
BAND_BODY_X = 150
BAND_BODY_W = 1230
BAND_H = 150
BAND_GAP = 10

# (id, label, y, fill)
BANDS = [
    ('band_ingest',   'INGESTION',           80,  '#E1F4E5'),
    ('band_prep',     'PREPROCESSING',      245,  '#E8DFF7'),
    ('band_embed',    'EMBEDDING\n& INDEX', 410,  '#DBE7F5'),
    ('band_retr',     'RETRIEVAL',          575,  '#FFF6E0'),
    ('band_reason',   'REASONING\nAGENT',   740,  '#FFE4CC'),
    ('band_output',   'OUTPUT &\nWORKFLOWS',905,  '#E1F0F8'),
]

# (id, label, x, y, w, h, fill, stroke)
COMPONENTS = [
    # Band 1 — Ingestion (y around 100)
    ('c_upload',   'File upload\n(PDF / DOCX)',           180, 105, 220, 60, '#B5E0C2', '#1B7F3A'),
    ('c_api',      'Library upload endpoint\n/library/upload/', 440, 105, 240, 60, '#B5E0C2', '#1B7F3A'),

    # Band 2 — Preprocessing (y around 270)
    ('c_extract',  'Text extract\n(PyMuPDF / docx)',       180, 270, 170, 60, '#C7B3E5', '#5E3FBE'),
    ('c_ocr',      'OCR fallback\n(EasyOCR)',              370, 270, 170, 60, '#C7B3E5', '#5E3FBE'),
    ('c_chunk',    'Two-level chunker\n(header + merge)',  560, 270, 200, 60, '#C7B3E5', '#5E3FBE'),
    ('c_classify', 'Chunk classify\n(12-topic taxonomy)',  780, 270, 200, 60, '#C7B3E5', '#5E3FBE'),
    ('c_inject',   'Injection scanner\n(Tier A + Tier B)', 1000, 270, 200, 60, '#F4B5B5', '#A02020'),
    ('c_quar',     'Quarantine table\n(SQLite)',          1000, 340, 200, 50, '#F4B5B5', '#A02020'),

    # Band 3 — Embedding (y around 435)
    ('c_embed',    'BGE-small embedder\n(384-dim)',        180, 440, 220, 60, '#9CC5EE', '#2B5F9E'),
    ('c_chroma',   'ChromaDB HNSW\n(vector index)',        440, 440, 220, 60, '#9CC5EE', '#2B5F9E'),
    ('c_fts5',     'SQLite FTS5\n(BM25 index)',            700, 440, 220, 60, '#9CC5EE', '#2B5F9E'),
    ('c_dictag',   'chunk_tags\n(taxonomy table)',         960, 440, 220, 60, '#9CC5EE', '#2B5F9E'),

    # Band 4 — Retrieval (y around 600)
    ('c_termdict', 'Term dictionary\nexpansion',            180, 605, 200, 60, '#E5C97A', '#B07A00'),
    ('c_bm25',     'BM25 search\n(top-20)',                400, 605, 180, 60, '#E5C97A', '#B07A00'),
    ('c_vec',      'Vector search\n(top-20)',              600, 605, 180, 60, '#E5C97A', '#B07A00'),
    ('c_rrf',      'RRF merge\n(k = 60)',                  800, 605, 180, 60, '#E5C97A', '#B07A00'),
    ('c_rerank',   'Cross-encoder\nrerank → top-5',        1000, 605, 200, 60, '#E5C97A', '#B07A00'),

    # Band 5 — Reasoning (y around 770)
    ('c_router',   'Query router\n(3-NN, no LLM)',         180, 770, 180, 60, '#F4C49E', '#B05A00'),
    ('c_draft',    'Draft\n(LLM via Ollama)',              380, 770, 180, 60, '#F4C49E', '#B05A00'),
    ('c_verify',   'Verify\n(citation + NLI)',             580, 770, 180, 60, '#F4C49E', '#B05A00'),
    ('c_correct',  'Correct\n(bounded retry)',             780, 770, 180, 60, '#F4C49E', '#B05A00'),
    ('c_final',    'Finalize /\nSafeFallback',             980, 770, 200, 60, '#F4C49E', '#B05A00'),

    # Band 6 — Output (y around 935)
    ('c_mapping',  'Policy Mapping\nworkflow',             180, 935, 180, 60, '#9CC9D9', '#2B6E80'),
    ('c_compare',  'Comparison\nworkflow',                 380, 935, 180, 60, '#9CC9D9', '#2B6E80'),
    ('c_gap',      'Gap Analysis\nworkflow',               580, 935, 180, 60, '#9CC9D9', '#2B6E80'),
    ('c_copilot',  'Copilot Q&A\n(grounded answer)',       780, 935, 200, 60, '#9CC9D9', '#2B6E80'),
    ('c_export',   'PDF / XLSX export\n(audit hash)',     1000, 935, 200, 60, '#9CC9D9', '#2B6E80'),
]

# (source, target) -- arrows between bands showing data flow
FLOWS = [
    # Ingestion -> Preprocessing
    ('c_upload',   'c_extract'),
    ('c_api',      'c_extract'),

    # Preprocessing internal flow (one path: extract -> ocr or chunk)
    ('c_extract',  'c_chunk'),
    ('c_ocr',      'c_chunk'),
    ('c_chunk',    'c_classify'),
    ('c_classify', 'c_inject'),
    ('c_inject',   'c_quar'),

    # Preprocessing -> Embedding (safe chunks only)
    ('c_inject',   'c_embed'),
    ('c_embed',    'c_chroma'),
    ('c_embed',    'c_fts5'),
    ('c_classify', 'c_dictag'),

    # Corpus -> Retrieval (read paths)
    ('c_chroma',   'c_vec'),
    ('c_fts5',     'c_bm25'),
    ('c_termdict', 'c_bm25'),
    ('c_termdict', 'c_vec'),
    ('c_bm25',     'c_rrf'),
    ('c_vec',      'c_rrf'),
    ('c_rrf',      'c_rerank'),

    # Retrieval -> Reasoning
    ('c_rerank',   'c_draft'),
    ('c_router',   'c_draft'),
    ('c_draft',    'c_verify'),
    ('c_verify',   'c_correct'),
    ('c_correct',  'c_draft'),
    ('c_verify',   'c_final'),
    ('c_correct',  'c_final'),

    # Reasoning -> Output
    ('c_final',    'c_mapping'),
    ('c_final',    'c_compare'),
    ('c_final',    'c_gap'),
    ('c_final',    'c_copilot'),
    ('c_mapping',  'c_export'),
    ('c_compare',  'c_export'),
    ('c_gap',      'c_export'),
]


# ── Styles ───────────────────────────────────────────────────────────────
STYLE_TITLE = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=1;fontSize=14;'
    'fontColor=#002583;'
)
STYLE_FOOTER = (
    'text;html=1;align=center;verticalAlign=middle;fontStyle=2;fontSize=9;'
    'fontColor=#6B7280;'
)
STYLE_BAND_BODY = (
    'rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor=#7B8499;'
    'strokeWidth=1;fontColor=#002583;fontStyle=0;fontSize=10;'
    'verticalAlign=top;dashed=0;opacity=50;'
)
STYLE_BAND_LABEL = (
    'rounded=0;whiteSpace=wrap;html=1;fillColor=#FAFAFA;strokeColor=#7B8499;'
    'strokeWidth=1;fontColor=#002583;fontStyle=1;fontSize=11;'
    'verticalAlign=middle;align=center;'
)
STYLE_COMPONENT = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
    'strokeWidth=1.2;fontColor=#1F2937;fontStyle=1;fontSize=10;align=center;'
    'verticalAlign=middle;arcSize=15;'
)
STYLE_EDGE = (
    'endArrow=open;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#002583;strokeWidth=1.2;fontSize=9;fontColor=#1F2937;'
    'opacity=80;'
)


def cell_vertex(cell_id, value, style, x, y, w, h):
    return (
        f'        <mxCell id="{cell_id}" value="{escape(value)}" '
        f'style="{style}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
        f'as="geometry" />\n'
        f'        </mxCell>'
    )


def cell_edge(edge_id, source, target):
    return (
        f'        <mxCell id="{edge_id}" style="{STYLE_EDGE}" '
        f'edge="1" source="{source}" target="{target}" parent="1">\n'
        f'          <mxGeometry relative="1" as="geometry" />\n'
        f'        </mxCell>'
    )


def build_xml():
    cells = []

    # Title
    cells.append(cell_vertex(
        'title',
        'Figure 15 — CJPCA Layered Architecture',
        STYLE_TITLE, 300, TITLE_Y, 800, 30,
    ))

    # Bands (body + left label)
    for (bid, label, y, fill) in BANDS:
        # Body
        body_style = STYLE_BAND_BODY.format(fill=fill)
        cells.append(cell_vertex(
            bid + '_body', '', body_style,
            BAND_BODY_X, y, BAND_BODY_W, BAND_H,
        ))
        # Left label
        cells.append(cell_vertex(
            bid + '_label', label, STYLE_BAND_LABEL,
            10, y, BAND_LABEL_W, BAND_H,
        ))

    # Components
    for (cid, label, x, y, w, h, fill, stroke) in COMPONENTS:
        style = STYLE_COMPONENT.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(cid, label, style, x, y, w, h))

    # Flow edges
    for i, (src, tgt) in enumerate(FLOWS, start=1):
        cells.append(cell_edge(f'f{i}', src, tgt))

    # Footer
    cells.append(cell_vertex(
        'footer',
        'Documents enter at the top and flow downward through six pipeline phases. '
        'Each phase is implemented as one or more Python modules sharing the same '
        'process; the LLM call in the Reasoning band is the only HTTP hop, to the '
        'local Ollama daemon on port 11434.',
        STYLE_FOOTER, 100, FOOTER_Y, 1200, 36,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 15 Layered Architecture" id="cjpca_layered">
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
    out_path = out_dir / 'Figure_15_LayeredArchitecture.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
