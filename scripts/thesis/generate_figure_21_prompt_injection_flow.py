"""Generate Figure 21 — Prompt-Injection Defense Flow (drawio).

Output: diagrams/Figure_21_PromptInjectionFlow.drawio

Shows the two-tier ingestion-time defense plus the reasoning-time
verify/correct loop:

  Document chunk
    → Tier-A regex scanner (9 rule groups)
        → match? → Quarantine table (admin approve/reject)
    → Tier-B LLM judge (Claude Haiku 4.5 / Ollama fallback)
        → flagged? → Quarantine (fail-closed if judge unreachable)
    → Embed to ChromaDB + index in FTS5

  Reasoning time:
    Retrieved chunks → LangGraph draft → Verifier (citation + NLI)
      → correct (bounded retry) → Finalize OR SafeFallback
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1500
PAGE_H = 1100

TITLE_Y = 20
FOOTER_Y = 1050


NODES = [
    # Top row — ingestion-time scan
    ('p_chunk',   'Document chunk\n(post-extract)',
     60, 120, 170, 80, '#E1F0F8', '#2B6E80'),
    ('p_tierA',   'Tier-A regex scanner\n9 rule groups',
     280, 120, 220, 80, '#F4C49E', '#B05A00'),

    ('p_rules',   'INST_OVERRIDE • ROLE_HIJACK\nFORCED_VERDICT • SAFETY_BYPASS\n'
                  'DEV_MODE_TRIGGER • PROMPT_LEAK\nFAKE_DELIMITER • BASE64_BLOB\nSUSPICIOUS_URL',
     280, 220, 220, 130, '#FFF6E0', '#B07A00'),

    ('p_tierB',   'Tier-B LLM judge\n(Claude Haiku 4.5\nfallback to Ollama)',
     550, 120, 220, 80, '#F4C49E', '#B05A00'),

    ('p_failclosed', 'Both judges\nunreachable?\nFail closed → Quarantine',
     550, 220, 220, 100, '#FBE2DE', '#A02020'),

    ('p_clean',   'Chunk passes\n(no flags)',
     820, 120, 180, 80, '#B5E0C2', '#1B7F3A'),

    ('p_quar',    'QuarantinedChunk\n(severity, rule_id,\nmatched_snippet,\nall_detections JSON)',
     280, 380, 270, 110, '#FBE2DE', '#A02020'),

    ('p_admin',   'Admin review\n(QuarantineQueueView)',
     280, 510, 270, 80, '#FFF6E0', '#B07A00'),

    ('p_approve', 'Approve\n→ release to index',
     130, 620, 200, 80, '#B5E0C2', '#1B7F3A'),
    ('p_reject',  'Reject\n→ permanent hold',
     350, 620, 200, 80, '#FBE2DE', '#A02020'),

    ('p_audit_q', 'AuditLog\nquarantine.flagged\nquarantine.approved\nquarantine.rejected',
     590, 510, 240, 130, '#9CC9D9', '#2B6E80'),

    ('p_embed',   'Embed to ChromaDB\n(BGE-small 384-dim)',
     1050, 120, 220, 80, '#9CC5EE', '#2B5F9E'),
    ('p_fts',     'Index in SQLite FTS5\n(BM25)',
     1310, 120, 180, 80, '#9CC5EE', '#2B5F9E'),

    # Bottom row — reasoning-time defense
    ('r_retr',    'Retrieved chunks\n(top-5 after rerank)',
     60, 800, 200, 80, '#DBE7F5', '#2B5F9E'),
    ('r_draft',   'LangGraph Draft\n(LLM generation)',
     290, 800, 200, 80, '#F4C49E', '#B05A00'),
    ('r_verify',  'Verifier\nverbatim grounding +\ncross-encoder NLI',
     520, 800, 240, 100, '#C7B3E5', '#5E3FBE'),
    ('r_correct', 'Correct\n(bounded retry,\nattempts ≤ 2)',
     790, 800, 200, 100, '#FFE4CC', '#B05A00'),
    ('r_final',   'Finalize\n(Pydantic v2 schema)',
     1020, 800, 220, 100, '#B5E0C2', '#1B7F3A'),
    ('r_fallback','SafeFallback\n(empty typed report)',
     1270, 800, 220, 100, '#FBE2DE', '#A02020'),
]


EDGES = [
    ('p_chunk',   'p_tierA',     ''),
    ('p_tierA',   'p_tierB',     'pass'),
    ('p_tierA',   'p_quar',      'match'),
    ('p_tierB',   'p_clean',     'pass'),
    ('p_tierB',   'p_quar',      'flag'),
    ('p_tierB',   'p_failclosed','judge unreachable'),
    ('p_failclosed','p_quar',    ''),
    ('p_clean',   'p_embed',     ''),
    ('p_embed',   'p_fts',       ''),
    ('p_quar',    'p_admin',     ''),
    ('p_admin',   'p_approve',   ''),
    ('p_admin',   'p_reject',    ''),
    ('p_approve', 'p_embed',     'release'),
    ('p_quar',    'p_audit_q',   ''),
    ('p_admin',   'p_audit_q',   ''),

    ('r_retr',    'r_draft',     ''),
    ('r_draft',   'r_verify',    ''),
    ('r_verify',  'r_correct',   'fail'),
    ('r_verify',  'r_final',     'pass'),
    ('r_correct', 'r_draft',     'retry'),
    ('r_correct', 'r_fallback',  'exhausted'),
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
STYLE_BAND = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor=#F8FAFC;strokeColor=#7B8499;'
    'strokeWidth=1;dashed=0;fontColor=#002583;fontStyle=1;fontSize=11;'
    'verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;arcSize=8;'
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
        'Figure 21 — Prompt-Injection Defense Flow',
        STYLE_TITLE, 350, TITLE_Y, 800, 30,
    ))

    # Band labels
    cells.append(cell_vertex(
        'band_ing', 'INGESTION-TIME DEFENCE (Tier-A + Tier-B)',
        STYLE_BAND, 40, 70, 1450, 670,
    ))
    cells.append(cell_vertex(
        'band_rea', 'REASONING-TIME DEFENCE (Verify / Correct / Fallback)',
        STYLE_BAND, 40, 760, 1450, 200,
    ))

    for (nid, label, x, y, w, h, fill, stroke) in NODES:
        style = STYLE_NODE.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))

    for i, (src, tgt, lbl) in enumerate(EDGES, start=1):
        cells.append(cell_edge(f'p{i}', src, tgt, lbl))

    cells.append(cell_vertex(
        'footer',
        'Tier-A is deterministic regex; Tier-B is an LLM judge that fails '
        'closed on classifier error. Quarantine is admin-reviewed and every '
        'transition is audited. Reasoning-time verification adds an '
        'orthogonal defence at output time.',
        STYLE_FOOTER, 100, FOOTER_Y, 1300, 36,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 21 Prompt Injection" id="cjpca_inj">
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
    out_path = out_dir / 'Figure_21_PromptInjectionFlow.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
