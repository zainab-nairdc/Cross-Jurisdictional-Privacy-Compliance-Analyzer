"""Generate Figure 17 — CJPCA Secure Architecture (drawio).

Output: diagrams/Figure_17_SecureArchitecture.drawio

Network-topology style (similar to the Oracle Cloud / on-prem reference
diagrams the user shared). CJPCA is positioned as an internal application
system hosted on the BBK workstation; external traffic enters through a
BBK-managed edge firewall and a GeoFence gate, then traverses the
application tiers inside a dashed-red Internal Network perimeter:

  External actors          Edge gates              Internal tiers (host)
  Analyst browser    -->   BBK Edge Firewall  -->  GeoFence  -->  Reverse Proxy
  Admin browser      -->   VPN tunnel         ----------------->  Django Admin
                                                                  (2FA-patched)

  Inside the Internal Network:
    Perimeter tier       reverse proxy (TLS 1.3, HSTS)
    Edge middleware      axes / CSRF / CSP / headers / force-pw / MFA
    Application tier     Django ASGI + Channels + RBAC + per-row scope
    Reasoning workers    ingestion threads, mapping/comparison subprocs,
                         Tier-A regex, Tier-B judge, verifier
    Data tier            SQLite + audit, ChromaDB, FTS5, media + logs

  Outbound egress allowlist points to local Ollama and the CDN allowlist.
"""

from pathlib import Path
from xml.sax.saxutils import escape


PAGE_W = 1500
PAGE_H = 1350

TITLE_Y = 20
FOOTER_Y = 1300


# (id, label, x, y, w, h, fill, stroke, font_color, font_style)
EXTERNAL_NODES = [
    ('ext_analyst',  'Analyst browser\nHTMX + Alpine',
     120, 90, 200, 70, '#E1F0F8', '#2B6E80', '#1F2937', 1),
    ('ext_admin',    'Admin browser\n(staff)',
     1180, 90, 200, 70, '#E1F0F8', '#2B6E80', '#1F2937', 1),
]

# Edge gates
EDGE_NODES = [
    ('edge_fw',      'BBK Edge Firewall\n(IT-managed perimeter)',
     120, 200, 200, 70, '#FBE2DE', '#A02020', '#A02020', 1),
    ('edge_vpn',     'VPN tunnel\n(admin access)',
     1180, 200, 200, 70, '#FFE4CC', '#B05A00', '#B05A00', 1),
    ('edge_geo',     'GeoFenceMiddleware\nMaxMind GeoLite2  •  allowlist: BH IN KW AE',
     420, 280, 660, 50, '#FBE2DE', '#A02020', '#A02020', 1),
]


# Tiers inside the Internal Network perimeter
# Each tier is a rounded tier box with components inside.
TIER_BOXES = [
    ('tier_proxy',   'PERIMETER TIER',
     180, 470, 1140, 100, '#F8FAFC', '#7B8499'),
    ('tier_mw',      'EDGE MIDDLEWARE TIER',
     180, 600, 1140, 100, '#F8FAFC', '#7B8499'),
    ('tier_app',     'APPLICATION TIER',
     180, 730, 1140, 110, '#F8FAFC', '#7B8499'),
    ('tier_work',    'REASONING WORKER TIER',
     180, 870, 1140, 110, '#F8FAFC', '#7B8499'),
    ('tier_data',    'DATA TIER',
     180, 1010, 1140, 110, '#F8FAFC', '#7B8499'),
]


# Components inside each tier
TIER_COMPONENTS = [
    # Perimeter tier
    ('p_proxy_tls', 'Reverse Proxy\nTLS 1.3 + HSTS (31 536 000 s) + preload',
     230, 500, 460, 60, '#F4C49E', '#B05A00'),
    ('p_proxy_redir', 'SECURE_SSL_REDIRECT\nport 443 only  •  X-Frame DENY  •  nosniff  •  ref same-origin',
     720, 500, 560, 60, '#F4C49E', '#B05A00'),

    # Edge middleware tier — chips
    ('mw_axes',  'django-axes\n5 / 30 min',           230, 630, 165, 60, '#FFE4CC', '#B05A00'),
    ('mw_csrf',  'CsrfView MW\n+ token per form',      405, 630, 165, 60, '#FFE4CC', '#B05A00'),
    ('mw_csp',   'CSP 4.x\nframe-ancestors none',      580, 630, 165, 60, '#FFE4CC', '#B05A00'),
    ('mw_force', 'ForcePassword\nChange MW',           755, 630, 165, 60, '#FFE4CC', '#B05A00'),
    ('mw_mfa',   'ForceMFA\nEnrollment MW',            930, 630, 165, 60, '#FFE4CC', '#B05A00'),
    ('mw_idle',  'IdleSessionTimeout\n1 800 s + axes',1105, 630, 175, 60, '#FFE4CC', '#B05A00'),

    # Application tier
    ('a_django', 'Django ASGI views\nORM-only, autoescape',  230, 760, 320, 70, '#E5C97A', '#B07A00'),
    ('a_chan',   'Django Channels\nWebSocket ingestion',     560, 760, 280, 70, '#E5C97A', '#B07A00'),
    ('a_rbac',   'RBAC\n@role_required + Mixin',             850, 760, 220, 70, '#C7B3E5', '#5E3FBE'),
    ('a_scope',  'Per-row scope\ncreated_by filter',        1080, 760, 200, 70, '#C7B3E5', '#5E3FBE'),

    # Reasoning worker tier
    ('w_ing',    'Ingestion daemon\nthreading.Thread',       230, 900, 220, 70, '#DBE7F5', '#2B5F9E'),
    ('w_jobs',   'Mapping + Comparison\nsubprocess dispatch',455, 900, 245, 70, '#DBE7F5', '#2B5F9E'),
    ('w_tA',     'Tier-A regex\n9 rule groups',              705, 900, 175, 70, '#9CC5EE', '#2B5F9E'),
    ('w_tB',     'Tier-B LLM judge\nfail-closed',            885, 900, 175, 70, '#9CC5EE', '#2B5F9E'),
    ('w_verify', 'Verifier + NLI\n+ Pydantic schema',       1065, 900, 215, 70, '#9CC5EE', '#2B5F9E'),

    # Data tier
    ('d_sql',    'SQLite\nusers, audit,\nsessions (WAL)',    230, 1040, 200, 70, '#B5E0C2', '#1B7F3A'),
    ('d_chroma', 'ChromaDB\nHNSW vector index',              435, 1040, 200, 70, '#B5E0C2', '#1B7F3A'),
    ('d_fts',    'SQLite FTS5\nBM25 keyword index',          640, 1040, 200, 70, '#B5E0C2', '#1B7F3A'),
    ('d_media',  'media/ + data/\n+ hf_cache/',              845, 1040, 200, 70, '#B5E0C2', '#1B7F3A'),
    ('d_logs',   'AuditLog + .log files\nSHA-256 export hash chain',
     1050, 1040, 230, 70, '#9CC9D9', '#2B6E80'),
]


# Outbound egress at the bottom
OUTBOUND_NODES = [
    ('out_egress', 'Outbound Egress Allowlist\n(LLM endpoint + CDN allowlist; CSP connect-src self)',
     420, 1170, 660, 50, '#FFF6E0', '#B07A00', '#B07A00', 1),
    ('out_llm',   'LLM endpoint\nOllama localhost:11434 (or external provider)',
     120, 1230, 280, 50, '#DBE7F5', '#2B5F9E', '#1F2937', 1),
    ('out_cdn',   'CDN allowlist\nunpkg, jsdelivr, fontshare, flagcdn',
     1100, 1230, 280, 50, '#DBE7F5', '#2B5F9E', '#1F2937', 1),
]


# (source, target, label)
EDGES = [
    ('ext_analyst', 'edge_fw',   'HTTPS'),
    ('ext_admin',   'edge_vpn',  'HTTPS'),
    ('edge_fw',     'edge_geo',  ''),
    ('edge_vpn',    'edge_geo',  ''),
    ('edge_geo',    'tier_proxy','allowed country'),
    ('out_egress',  'out_llm',   ''),
    ('out_egress',  'out_cdn',   ''),
    ('tier_data',   'out_egress',''),
    ('tier_work',   'out_egress',''),
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
    'strokeWidth=1.4;fontColor={fc};fontStyle={fs};fontSize=10;align=center;'
    'verticalAlign=middle;arcSize=15;'
)
STYLE_TIER = (
    'rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
    'strokeWidth=1.2;dashed=0;fontColor=#002583;fontStyle=1;fontSize=11;'
    'verticalAlign=top;align=left;spacingLeft=12;spacingTop=6;arcSize=10;'
)
STYLE_PERIM = (
    'rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#A02020;'
    'strokeWidth=2;dashed=1;dashPattern=10 6;fontColor=#A02020;fontStyle=1;'
    'fontSize=12;verticalAlign=top;align=left;spacingLeft=14;spacingTop=8;'
)
STYLE_EDGE = (
    'endArrow=classic;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;'
    'strokeColor=#002583;strokeWidth=1.4;fontSize=9;fontColor=#1F2937;'
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
        'Figure 17 — CJPCA Secure Architecture (Internal Application System)',
        STYLE_TITLE, 200, TITLE_Y, 1100, 30,
    ))

    # External actors and edge gates
    for (nid, label, x, y, w, h, fill, stroke, fc, fs) in EXTERNAL_NODES:
        style = STYLE_NODE.format(fill=fill, stroke=stroke, fc=fc, fs=fs)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))
    for (nid, label, x, y, w, h, fill, stroke, fc, fs) in EDGE_NODES:
        style = STYLE_NODE.format(fill=fill, stroke=stroke, fc=fc, fs=fs)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))

    # Internal Network dashed-red perimeter (large rectangle around tiers)
    cells.append(cell_vertex(
        'internal_perim',
        'Internal Network — BBK On-Premises Host',
        STYLE_PERIM, 130, 380, 1240, 770,
    ))

    # Tier containers
    for (tid, label, x, y, w, h, fill, stroke) in TIER_BOXES:
        style = STYLE_TIER.format(fill=fill, stroke=stroke)
        cells.append(cell_vertex(tid, label, style, x, y, w, h))

    # Tier components
    for (cid, label, x, y, w, h, fill, stroke) in TIER_COMPONENTS:
        style = STYLE_NODE.format(fill=fill, stroke=stroke,
                                  fc='#1F2937', fs=1)
        cells.append(cell_vertex(cid, label, style, x, y, w, h))

    # Outbound egress
    for (nid, label, x, y, w, h, fill, stroke, fc, fs) in OUTBOUND_NODES:
        style = STYLE_NODE.format(fill=fill, stroke=stroke, fc=fc, fs=fs)
        cells.append(cell_vertex(nid, label, style, x, y, w, h))

    # Edges
    for i, (src, tgt, lbl) in enumerate(EDGES, start=1):
        cells.append(cell_edge(f'e{i}', src, tgt, lbl))

    # Legend
    legend_style = (
        'rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#7B8499;'
        'strokeWidth=1;fontColor=#1F2937;fontStyle=0;fontSize=9;align=left;'
        'verticalAlign=top;spacingLeft=8;spacingTop=4;arcSize=8;'
    )
    legend_text = (
        'Notes:\n'
        '•  CJPCA is an internal application system on the BBK workstation; '
        'external traffic is gated by the BBK-managed edge firewall.\n'
        '•  Admin access uses the VPN tunnel plus TWO_FACTOR_PATCH_ADMIN '
        'for the Django admin path.\n'
        '•  Outbound egress is restricted by host network rules; the in-app '
        'CSP and connect-src self enforce this at the browser layer.\n'
        '•  IDS / IPS recommended at the BBK edge firewall and on the host '
        'workstation (BBK endpoint protection covers anti-malware).'
    )
    cells.append(cell_vertex(
        'legend', legend_text, legend_style,
        130, 1230, 1240, 60,
    ))

    cells.append(cell_vertex(
        'footer',
        'Red dashed perimeter is the Internal Network; tier boxes inside the '
        'perimeter are co-located on the BBK host process. GeoFence sits at '
        'the entry point so disallowed source countries never reach the '
        'application tiers.',
        STYLE_FOOTER, 100, FOOTER_Y, 1300, 36,
    ))

    body = '\n'.join(cells)
    xml = f'''<mxfile host="app.diagrams.net" type="device">
  <diagram name="Figure 17 Secure Architecture" id="cjpca_secarch">
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
    out_path = out_dir / 'Figure_17_SecureArchitecture.drawio'
    out_path.write_text(build_xml(), encoding='utf-8')
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
