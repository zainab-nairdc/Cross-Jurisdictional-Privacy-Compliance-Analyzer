"""Build a SIMPLE bullet-point demo deck from scratch.

No template clutter. Each slide:
- Clean navy title bar
- Bullet points OR
- "[ ADD HERE: ... ]" placeholder for diagrams/screenshots

Output: demo/CJPCA_Demo_Deck_Simple.pptx
"""
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'demo' / 'CJPCA_Demo_Deck_Simple.pptx'

# Colors
NAVY     = RGBColor(0x00, 0x25, 0x83)
DARK     = RGBColor(0x00, 0x3B, 0xA3)
ACCENT   = RGBColor(0x4A, 0x8C, 0xFF)
WHITE    = RGBColor(0xFF, 0xFF, 0xFF)
BLACK    = RGBColor(0x1F, 0x29, 0x37)
GREY     = RGBColor(0x6B, 0x72, 0x80)
GREY_LT  = RGBColor(0xF2, 0xF2, 0xF2)
PALE     = RGBColor(0xFA, 0xFA, 0xFA)
AMBER    = RGBColor(0xFF, 0xB8, 0x00)
GREEN    = RGBColor(0x15, 0x80, 0x3D)
RED      = RGBColor(0xB9, 0x1C, 0x1C)


def add_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])  # BLANK


def rect(slide, x, y, w, h, fill, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line:
        s.line.color.rgb = line
        s.line.width = Pt(0.5)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    return s


def text(slide, x, y, w, h, content, *, size=14, bold=False, color=BLACK,
         align='left', anchor='top', font='Calibri'):
    align_map = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}
    anchor_map = {'top': MSO_ANCHOR.TOP, 'middle': MSO_ANCHOR.MIDDLE, 'bottom': MSO_ANCHOR.BOTTOM}

    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor_map[anchor]
    tf.margin_left = Inches(0.08)
    tf.margin_right = Inches(0.08)

    lines = content if isinstance(content, list) else content.split('\n')
    for i, line in enumerate(lines):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.alignment = align_map[align]
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        r.font.name = font


def title_bar(slide, title, subtitle=None):
    """Navy title bar at top."""
    rect(slide, 0, 0, 13.33, 0.95, NAVY)
    text(slide, 0.5, 0.12, 12.3, 0.5, title,
         size=24, bold=True, color=WHITE, anchor='middle')
    if subtitle:
        text(slide, 0.5, 0.58, 12.3, 0.35, subtitle,
             size=11, color=RGBColor(0xCF, 0xDB, 0xF5), anchor='middle')


def bullets(slide, x, y, w, h, items, *, size=14, color=BLACK, bold_first=False):
    """Add bullet list of items. Each item is a string."""
    content = '\n\n'.join(['•  ' + i for i in items])
    text(slide, x, y, w, h, content, size=size, color=color)


def placeholder_box(slide, x, y, w, h, what_to_add):
    """Marked placeholder for diagrams or screenshots — pale box with instruction."""
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = PALE
    s.line.color.rgb = AMBER
    s.line.width = Pt(2)
    # Make dashed
    from pptx.oxml.ns import qn
    ln = s.line._get_or_add_ln()
    prstDash = ln.find(qn('a:prstDash'))
    if prstDash is None:
        prstDash = ln.makeelement(qn('a:prstDash'), {'val': 'dash'})
        ln.append(prstDash)
    else:
        prstDash.set('val', 'dash')
    s.shadow.inherit = False

    # Icon
    text(slide, x, y + h/2 - 0.7, w, 0.5, "📷",
         size=36, color=AMBER, align='center')
    # Label
    text(slide, x, y + h/2 - 0.1, w, 0.4, "ADD HERE",
         size=14, bold=True, color=AMBER, align='center')
    # Instruction
    text(slide, x + 0.2, y + h/2 + 0.3, w - 0.4, h/2 - 0.4, what_to_add,
         size=11, color=GREY, align='center')


def footer(slide, n):
    text(slide, 0.5, 7.15, 6, 0.3, "CJPCA · Viva Demo · 20 May 2026",
         size=8, color=GREY)
    text(slide, 12.3, 7.15, 0.9, 0.3, f"{n}",
         size=8, color=GREY, align='right')


def notes(slide, script_text):
    """Add speaker notes to a slide.

    The text appears in PowerPoint's notes pane below the slide
    (visible to the presenter, hidden from the audience).
    """
    notes_slide = slide.notes_slide
    text_frame = notes_slide.notes_text_frame
    text_frame.text = script_text


# ════════════════════════════════════════════════════════════════════════════
# SLIDES
# ════════════════════════════════════════════════════════════════════════════

def s01(prs):
    """Title + NDA"""
    s = add_slide(prs)
    rect(s, 0, 0, 13.33, 7.5, NAVY)
    rect(s, 0, 4.5, 13.33, 0.04, ACCENT)

    text(s, 1, 1.0, 11, 0.4, "IT8X99  ·  PROJECT DEMONSTRATION  ·  VIVA",
         size=12, bold=True, color=ACCENT)
    text(s, 1, 1.6, 11, 1.2, "Cross-Jurisdictional Privacy",
         size=42, bold=True, color=WHITE)
    text(s, 1, 2.6, 11, 1.2, "Compliance Analyzer",
         size=42, bold=True, color=WHITE)
    text(s, 1, 4.0, 11, 0.5,
         "AI-assisted regulatory compliance for cross-border banking",
         size=16, color=RGBColor(0xCF, 0xDB, 0xF5))

    text(s, 1, 5.0, 11, 1.5,
         ["Student         Zainab Ayman Abdulmajeed Isa Hammad",
          "CLP Company   Nasser Centre — AI Research & Development Centre",
          "Date                 20 May 2026"],
         size=14, color=WHITE)

    rect(s, 1, 6.4, 11.3, 0.7, AMBER)
    text(s, 1.2, 6.45, 11, 0.6,
         "This project is under an NDA. Architecture, live functionality, and pseudocode are demonstrated; source code is not shown.",
         size=11, bold=True, color=BLACK, anchor='middle')

    notes(s, """[0:00 - 0:30] TITLE + NDA

Stand. Smile. Look at the panel. Speak slowly.

"Good morning. My name is Zainab. I'm presenting the Cross-Jurisdictional Privacy Compliance Analyzer, built during my internship at Nasser Centre's AI Research and Development Centre.

This project is under an NDA with our banking client, so I'll be presenting through architecture diagrams, live functionality, and pseudocode rather than source code. The course coordinator has approved this approach.

Let me start with the problem."

→ ADVANCE to Slide 2""")


def s02(prs):
    """Problem"""
    s = add_slide(prs)
    title_bar(s, "The Problem")

    bullets(s, 0.8, 1.4, 11.5, 4.5, [
        "Banks operating across multiple regulatory jurisdictions face a growing compliance challenge",
        "Privacy laws differ in terminology and obligations — 'data subject' vs 'data principal'",
        "Compliance teams currently map regulations against internal policies by hand",
        "Result: slow, error-prone, regulatory penalty exposure",
    ], size=18)

    text(s, 0.8, 5.8, 11.5, 0.4, "Three jurisdictions in scope:",
         size=14, bold=True, color=NAVY)

    flags = [("BAHRAIN PDPL", NAVY), ("INDIA DPDPA", DARK), ("KUWAIT DPPR", ACCENT)]
    x = 0.8
    for name, color in flags:
        rect(s, x, 6.3, 3.85, 0.7, color)
        text(s, x, 6.3, 3.85, 0.7, name, size=15, bold=True, color=WHITE,
             align='center', anchor='middle')
        x += 3.95
    footer(s, 2)


def s03(prs):
    """Aim + Features ✓/⚠/✗"""
    s = add_slide(prs)
    title_bar(s, "Project Aim & Features")

    # AIM (left)
    rect(s, 0.4, 1.2, 5.5, 5.9, GREY_LT)
    text(s, 0.6, 1.35, 5.2, 0.4, "THE AIM",
         size=11, bold=True, color=NAVY)
    text(s, 0.6, 1.85, 5.2, 4.3,
         "Equip compliance teams with an AI workspace that completes cross-jurisdictional review in minutes — with every AI finding grounded in a real regulatory clause.",
         size=14, color=BLACK)
    rect(s, 0.6, 5.7, 5.1, 1.2, NAVY)
    text(s, 0.8, 5.85, 4.7, 0.95,
         "The contribution:\nCompress days into minutes without trading speed for trust.",
         size=11, color=WHITE, bold=True)

    # FEATURES (right)
    text(s, 6.2, 1.2, 6.7, 0.4, "FEATURES & STATUS",
         size=11, bold=True, color=NAVY)
    feats = [
        ('✓', 'Cross-jurisdictional regulation comparison', 'DELIVERED', GREEN),
        ('✓', 'Policy-to-regulation coverage mapping',       'DELIVERED', GREEN),
        ('✓', 'Gap register + severity + AI remediation',    'DELIVERED', GREEN),
        ('✓', 'Citation-backed Copilot chat',                'DELIVERED', GREEN),
        ('✓', 'Human-in-the-loop reviewer queue',            'DELIVERED', GREEN),
        ('✓', 'Analytics + audit dashboards',                'DELIVERED', GREEN),
        ('✓', '7-tier defence-in-depth security shell',      'DELIVERED', GREEN),
        ('✓', 'Append-only audit log + SHA-256 export',      'DELIVERED', GREEN),
        ('⚠', 'Cross-jurisdictional auto-routing',           'PARTIAL',   AMBER),
        ('⚠', 'Arabic-language corpus support',              'PARTIAL',   AMBER),
        ('✗', 'Multi-tenant deployment',                      'NOT SCOPED', RED),
    ]
    y = 1.7
    for icon, label, status, color in feats:
        text(s, 6.2, y, 0.35, 0.42, icon, size=15, bold=True, color=color)
        text(s, 6.6, y, 4.8, 0.42, label, size=11, color=BLACK, anchor='middle')
        text(s, 11.4, y, 1.5, 0.42, status, size=9, bold=True, color=color,
             align='right', anchor='middle')
        y += 0.47
    footer(s, 3)


def s04(prs):
    """Client fit"""
    s = add_slide(prs)
    title_bar(s, "Where I Fit In")

    rect(s, 3.5, 1.5, 6.3, 1.0, NAVY)
    text(s, 3.5, 1.6, 6.3, 0.4, "Nasser Centre for Science & Technology",
         size=14, bold=True, color=WHITE, align='center')
    text(s, 3.5, 2.0, 6.3, 0.4, "Artificial Intelligence Research & Development Centre",
         size=11, color=RGBColor(0xCF, 0xDB, 0xF5), align='center')

    text(s, 6.5, 2.5, 0.3, 0.4, "▼", size=22, color=NAVY, align='center')

    rect(s, 1.0, 3.1, 5.4, 1.7, GREY_LT)
    text(s, 1.0, 3.2, 5.4, 0.4, "Project supervisors",
         size=13, bold=True, color=NAVY, align='center')
    text(s, 1.1, 3.7, 5.2, 1.0,
         "Qabas Elayan · Mohammed Albasri\n\nArchitectural review + technical guidance",
         size=11, color=GREY, align='center')

    rect(s, 6.9, 3.1, 5.4, 1.7, ACCENT)
    text(s, 6.9, 3.2, 5.4, 0.4, "Sole technical builder (me)",
         size=13, bold=True, color=WHITE, align='center')
    text(s, 7.0, 3.7, 5.2, 1.0,
         "End-to-end design, implementation,\neval, and on-prem deployment",
         size=11, color=WHITE, align='center')

    text(s, 6.5, 5.0, 0.3, 0.4, "▼", size=22, color=AMBER, align='center')

    rect(s, 3.5, 5.4, 6.3, 1.5, AMBER)
    text(s, 3.5, 5.55, 6.3, 0.4, "Banking client (under NDA)",
         size=14, bold=True, color=WHITE, align='center')
    text(s, 3.6, 6.05, 6.1, 0.85,
         "Use-case sponsor · Document corpus owner · Compliance team end-user",
         size=11, color=WHITE, align='center')
    footer(s, 4)


def s05(prs):
    """Tech stack — bullet style, simple"""
    s = add_slide(prs)
    title_bar(s, "Technology Stack", "Every choice was eval-driven, not a default")

    # 2 columns of tech picks
    items_left = [
        ("Web", "Django 5 + HTMX + Alpine + Tailwind"),
        ("LLM", "Claude Haiku 4.5 (OpenRouter) + Ollama fallback"),
        ("Reasoning", "LangGraph state machine + Pydantic"),
        ("Embedding", "BGE-small-en-v1.5 (local, 384-dim)"),
        ("Reranker", "ms-marco-MiniLM (beat BGE-large in eval)"),
    ]
    items_right = [
        ("Vector DB", "ChromaDB (local, persistent)"),
        ("Keyword search", "SQLite FTS5 (BM25, filter pushdown)"),
        ("NLI gate", "DeBERTa-v3 cross-encoder"),
        ("PDF parsing", "Docling (preserves structure)"),
        ("Security", "django-axes · TOTP MFA · CSP · django-csp"),
    ]
    y = 1.4
    for cat, val in items_left:
        text(s, 0.6, y, 2.5, 0.4, cat, size=12, bold=True, color=NAVY)
        text(s, 3.1, y, 3.4, 0.4, val, size=11, color=BLACK)
        y += 0.55
    y = 1.4
    for cat, val in items_right:
        text(s, 6.8, y, 2.4, 0.4, cat, size=12, bold=True, color=NAVY)
        text(s, 9.2, y, 3.5, 0.4, val, size=11, color=BLACK)
        y += 0.55

    # Key decisions box
    rect(s, 0.4, 4.6, 12.5, 2.4, GREY_LT)
    text(s, 0.6, 4.7, 12.1, 0.4, "KEY DECISIONS — chosen vs rejected",
         size=11, bold=True, color=NAVY)
    decisions = [
        "ChromaDB over Pinecone — Pinecone is paid SaaS, breaks zero-egress",
        "SQLite FTS5 over in-memory BM25 — eval: hit_rate@5 0.95 vs 0.875",
        "MiniLM reranker over BGE-reranker-large — smaller, but beat it on our corpus",
        "Claude Haiku over GPT-4o-mini — eval'd better on verbatim citation",
    ]
    bullets(s, 0.7, 5.15, 12.0, 1.8, decisions, size=11)
    footer(s, 5)


def s06(prs):
    """Architecture — 5 layers + AI Pipeline placeholder"""
    s = add_slide(prs)
    title_bar(s, "System Architecture", "Five layers built bottom-up · AI pipeline runs through three lanes")

    # 5-layer text on LEFT
    text(s, 0.4, 1.25, 6, 0.4, "5-LAYER ARCHITECTURE (bottom-up)",
         size=11, bold=True, color=NAVY)
    layers = [
        ("WEB",       "Django · HTMX · Channels (WebSocket)",      ACCENT),
        ("REASONING", "LangGraph · Claude Haiku · Pydantic",        NAVY),
        ("RETRIEVAL", "BM25 + Vector + RRF + Cross-encoder",        DARK),
        ("INGESTION", "Docling · Chunker · Inject Scan · Index",    AMBER),
        ("DATA",      "43 docs · 25-field metadata · 4 juris",      GREEN),
    ]
    y = 1.75
    for name, desc, color in layers:
        rect(s, 0.4, y, 6.2, 0.95, color)
        text(s, 0.55, y + 0.1, 5.9, 0.35, name,
             size=13, bold=True, color=WHITE)
        text(s, 0.55, y + 0.45, 5.9, 0.45, desc,
             size=10, color=WHITE)
        y += 1.02

    # AI Pipeline placeholder on RIGHT
    text(s, 6.9, 1.25, 6, 0.4, "AI PIPELINE DIAGRAM",
         size=11, bold=True, color=NAVY)
    placeholder_box(s, 6.9, 1.75, 6.0, 5.3,
                    "AI Pipeline diagram from poster\n\nFile: thesis_docs/poster/Figure_PosterAIPipeline.png\n\n3 lanes: Ingestion → Retrieval → Reasoning")
    footer(s, 6)


def s07(prs):
    """Security — defence-in-depth placeholder + 7-tier bullets"""
    s = add_slide(prs)
    title_bar(s, "Security Architecture", "7-tier defence-in-depth shell")

    # Placeholder on LEFT
    placeholder_box(s, 0.4, 1.25, 5.5, 5.8,
                    "Defence-in-Depth diagram from poster\n\nFile: thesis_docs/poster/Figure_PosterDefenceInDepth.png\n\n7 concentric tiers visualised")

    # 7-tier bullet list on RIGHT
    text(s, 6.2, 1.25, 6.7, 0.4, "7 TIERS — OUTERMOST → INNERMOST",
         size=11, bold=True, color=NAVY)
    tiers = [
        ('T7', 'Network perimeter', 'TLS 1.3 · GeoFence · Caddy'),
        ('T6', 'Identity & access', 'django-axes · TOTP MFA'),
        ('T5', 'Authorisation', 'RBAC (Analyst / Reviewer / Admin)'),
        ('T4', 'App hardening', 'CSP · CSRF · secure cookies'),
        ('T3', 'Content defence', 'Two-tier injection scanner'),
        ('T2', 'AI safety', 'Citation verifier + NLI gate'),
        ('T1', 'Forensic layer', 'AuditLog + SHA-256 export'),
    ]
    y = 1.75
    for tier, layer, mech in tiers:
        rect(s, 6.2, y, 0.6, 0.65, NAVY)
        text(s, 6.2, y, 0.6, 0.65, tier,
             size=14, bold=True, color=WHITE, align='center', anchor='middle')
        text(s, 6.9, y + 0.02, 6.0, 0.35, layer,
             size=11, bold=True, color=BLACK)
        text(s, 6.9, y + 0.35, 6.0, 0.3, mech,
             size=9, color=GREY)
        y += 0.7
    footer(s, 7)


def s08(prs):
    """User journey — 3 roles bullets"""
    s = add_slide(prs)
    title_bar(s, "User Journey", "Admin sets up · Analyst works · Reviewer signs off")

    roles = [
        ("PHASE 1: ADMIN", NAVY, [
            "Create users + assign roles",
            "Trigger forced MFA enrollment",
            "Upload documents",
            "Approve quarantined chunks",
            "Monitor full audit log",
        ]),
        ("PHASE 2: ANALYST", ACCENT, [
            "Run cross-jurisdictional comparison",
            "Map internal policies",
            "Review AI-drafted gap remediation",
            "Ask citation-backed Copilot",
            "Submit work to reviewer",
        ]),
        ("PHASE 3: REVIEWER", GREEN, [
            "See submitted work in queue",
            "Accept / Modify / Reject rows",
            "Export executive summary PDF",
            "PDF embeds SHA-256 audit hash",
            "Approved rows ship as evidence",
        ]),
    ]
    x = 0.5
    for header, color, items in roles:
        rect(s, x, 1.3, 4.1, 0.6, color)
        text(s, x, 1.32, 4.1, 0.55, header,
             size=14, bold=True, color=WHITE, align='center', anchor='middle')
        rect(s, x, 1.95, 4.1, 4.8, GREY_LT)
        bullet_text = '\n\n'.join(['•  ' + i for i in items])
        text(s, x + 0.2, 2.15, 3.9, 4.4, bullet_text,
             size=11, color=BLACK)
        x += 4.25

    rect(s, 0.5, 6.9, 12.3, 0.4, AMBER)
    text(s, 0.5, 6.9, 12.3, 0.4,
         "Every action across all three roles → AuditLog (append-only, 28 event types)",
         size=10, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 8)


def s09(prs):
    """Admin — bullets + screenshot placeholder"""
    s = add_slide(prs)
    title_bar(s, "Phase 1: Admin — Setup", "Live demo: user creation · MFA enrollment · quarantine review")

    text(s, 0.4, 1.25, 6, 0.4, "ADMIN RESPONSIBILITIES",
         size=11, bold=True, color=NAVY)
    bullets(s, 0.6, 1.7, 6.0, 5.5, [
        "Create users → assign role (Analyst / Reviewer / Admin)",
        "New user → forced password change + MFA enrollment",
        "MFA = TOTP via authenticator app + backup tokens",
        "Upload documents → triggers 6-stage ingestion pipeline",
        "Stages: Parse → Chunk → Inject-Scan → Embed → Index → Ready",
        "Review Quarantine Queue → approve / reject flagged chunks",
        "Monitor full audit log (28 event types)",
    ], size=13)

    # Live demo placeholder
    placeholder_box(s, 6.9, 1.25, 6.0, 5.8,
                    "Live screenshot — Quarantine Queue\n\nShow 3 flagged chunks: INST_OVERRIDE,\nFORCED_VERDICT, SAFETY_BYPASS\n\n(or browse to /ingestion/quarantine/\nduring live demo)")
    footer(s, 9)


def s10(prs):
    """Comparison — bullets + diagram placeholder"""
    s = add_slide(prs)
    title_bar(s, "Phase 2A: Analyst — Cross-Jurisdictional Comparison",
              "Hybrid retrieval + verification gate")

    text(s, 0.4, 1.25, 6, 0.4, "HOW IT WORKS",
         size=11, bold=True, color=NAVY)
    bullets(s, 0.6, 1.7, 6.0, 5.5, [
        "Analyst picks two regulations + topics → clicks Run",
        "Query fans out to TWO retrieval paths in parallel:",
        "  →  Vector path: BGE + ChromaDB cosine similarity",
        "  →  BM25 path: SQLite FTS5 keyword match",
        "Filter pushdown at DB layer — LLM can't see out-of-scope chunks",
        "RRF fusion (k=60) merges both ranked lists",
        "Cross-encoder reranks top-20 for precision",
        "Verification gate: verbatim quote check + NLI score",
        "Drop rule: no citation AND risk > 0.90 → invention",
    ], size=12)

    # Comparison screenshot placeholder
    placeholder_box(s, 6.9, 1.25, 6.0, 5.8,
                    "Live screenshot — Comparison Workspace\n\nShow one obligation card with:\n• Verbatim quotes on both sides\n• Citation verified badge\n• Confidence + similarity scores")
    footer(s, 10)


def s11(prs):
    """Mapping + Copilot — bullets + screenshot placeholder"""
    s = add_slide(prs)
    title_bar(s, "Phase 2B: Analyst — Mapping + Copilot",
              "Policy-driven auto-routing · Gap Register · Citation-backed Copilot")

    text(s, 0.4, 1.25, 6, 0.4, "POLICY-DRIVEN MAPPING",
         size=11, bold=True, color=NAVY)
    bullets(s, 0.6, 1.7, 6.0, 5.5, [
        "Read what topics the POLICY actually covers (chunk tags)",
        "Read what topics the REGULATION covers (same)",
        "Intersect: map ONLY topics in BOTH sets",
        "Skip topics policy covers but regulation doesn't (audit note)",
        "Per-topic mapping pass with filter pushdown",
        "Gap Register: each gap + severity + AI remediation",
        "Copilot: ask natural-language questions",
        "Answers come with citation chips → click to source",
        "Submit to reviewer → audit row + queue entry",
    ], size=12)

    placeholder_box(s, 6.9, 1.25, 6.0, 5.8,
                    "Live screenshot — Gap Register + Copilot\n\nShow:\n• One gap with MEDIUM severity\n• AI-drafted remediation text\n• Copilot answer with citation chips")
    footer(s, 11)


def s12(prs):
    """Reviewer — bullets + PDF placeholder"""
    s = add_slide(prs)
    title_bar(s, "Phase 3: Reviewer — Approve + Export",
              "PDF embeds tamper-evident SHA-256 hash")

    text(s, 0.4, 1.25, 6, 0.4, "REVIEWER LIFECYCLE",
         size=11, bold=True, color=NAVY)
    bullets(s, 0.6, 1.7, 6.0, 5.5, [
        "Reviewer sees submitted runs in queue",
        "Opens a run → sees workspace with Accept / Modify / Reject",
        "Accept → AI verdict approved as-is",
        "Modify → reviewer's text replaces AI verdict (diff stored)",
        "Reject → row excluded from export",
        "Complete review → run lifecycle: APPROVED",
        "Download executive summary → PDF generated",
        "PDF embeds SHA-256 hash of run identity + decisions",
        "Recipient can recompute hash → silent edits visible",
    ], size=12)

    placeholder_box(s, 6.9, 1.25, 6.0, 5.8,
                    "Live screenshot — Executive PDF\n\nShow:\n• Compliance score banner\n• Top gaps table\n• Sign-off block with SHA-256 hash visible")
    footer(s, 12)


def s13(prs):
    """Audit trail"""
    s = add_slide(prs)
    title_bar(s, "Audit Trail — Closes the Loop", "28 canonical event types · append-only · role snapshotted")

    text(s, 0.4, 1.25, 12.5, 0.4, "Every action by every role lands in one append-only table",
         size=12, bold=True, color=NAVY)

    cats = [
        ("AUTH / SESSION  (8)", NAVY,
         ["auth.login", "auth.login_failed", "auth.logout",
          "auth.idle_timeout", "auth.mfa_enrolled", "auth.mfa_reset",
          "auth.backup_codes_regen", "auth.sessions_terminated"]),
        ("ANALYST FLOWS  (6)", ACCENT,
         ["comparison.run", "comparison.complete", "comparison.failed",
          "mapping.run", "mapping.complete", "mapping.failed"]),
        ("REVIEWER  (4)", GREEN,
         ["review.submit", "review.accept", "review.reject", "review.modify"]),
        ("CORPUS  (4)", AMBER,
         ["document.upload", "document.delete",
          "ingestion.complete", "ingestion.failed"]),
        ("QUARANTINE  (3)", RED,
         ["quarantine.flagged", "quarantine.approved", "quarantine.rejected"]),
        ("USER ADMIN  (5)", DARK,
         ["user.created", "user.role_changed", "user.disabled",
          "user.password_reset", "user.password_changed"]),
    ]
    x = 0.4
    y = 1.75
    col = 0
    for name, color, events in cats:
        rect(s, x, y, 4.13, 0.42, color)
        text(s, x, y + 0.02, 4.13, 0.42, name,
             size=10, bold=True, color=WHITE, align='center', anchor='middle')
        rect(s, x, y + 0.44, 4.13, 2.1, GREY_LT)
        text(s, x + 0.15, y + 0.5, 3.85, 2.0, '\n'.join(events),
             size=9, color=BLACK, font='Consolas')
        x += 4.21
        col += 1
        if col >= 3:
            col = 0
            x = 0.4
            y += 2.65

    rect(s, 0.4, 6.85, 12.5, 0.4, AMBER)
    text(s, 0.4, 6.85, 12.5, 0.4,
         "user_role_at_time is SNAPSHOTTED — historical record never silently revises itself",
         size=10, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 13)


def s14(prs):
    """Database schema placeholder"""
    s = add_slide(prs)
    title_bar(s, "Database Schema", "Persistence behind every action")

    text(s, 0.4, 1.25, 12.5, 0.4, "KEY TABLES (8)",
         size=11, bold=True, color=NAVY)

    tables = [
        ("Document",         "Root entity. id · jurisdiction · doc_type · chunk_count · status",  NAVY),
        ("IngestionJob",     "Tracks stage 1-6 + progress %",                                      ACCENT),
        ("QuarantinedChunk", "Flagged chunks: rule_id · tier (A/B) · severity",                    RED),
        ("ComparisonRun",    "pair_key · reg_a · reg_b · topics · status",                         GREEN),
        ("ComparisonResult", "relationship · confidence · citation_verified · hallucination_risk", GREEN),
        ("MappingAnalysis",  "policy_doc · regulations[] · status · gap_count",                    AMBER),
        ("ObligationMapping / Gap", "coverage · severity · remediation · priority",                AMBER),
        ("AuditLog (independent)",  "event_type · user · role_snapshot · ip · timestamp · JSON",   DARK),
    ]
    y = 1.7
    for name, desc, color in tables:
        rect(s, 0.4, y, 3.0, 0.55, color)
        text(s, 0.5, y + 0.05, 2.9, 0.45, name,
             size=11, bold=True, color=WHITE, anchor='middle')
        text(s, 3.5, y, 9.4, 0.55, desc,
             size=10, color=BLACK, anchor='middle')
        y += 0.62

    rect(s, 0.4, 6.85, 12.5, 0.4, NAVY)
    text(s, 0.4, 6.85, 12.5, 0.4,
         "AuditLog stands independent — every event in the system writes a row, no foreign keys",
         size=10, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 14)


def s15(prs):
    """Evaluation — 3 columns"""
    s = add_slide(prs)
    title_bar(s, "Evaluation", "Three independent eval layers")

    blocks = [
        ("RETRIEVAL EVAL", NAVY, "0.95", "hit_rate@5",
         ["LlamaIndex RetrieverEvaluator",
          "8 hand-picked queries +",
          "synthetic Q/A set",
          "",
          "Drops to 0.875 with",
          "in-memory BM25 →",
          "justifies SQLite FTS5"]),
        ("REASONING EVAL", GREEN, "80%", "1st-try verify pass",
         ["Full pipeline test",
          "correction trigger   ~12%",
          "fallback rate            ~3%",
          "citation match        >95%",
          "",
          "Latency p50 ~2s warm",
          "Latency p95 ~12s cold"]),
        ("RAGAS CROSS-CHECK", AMBER, "✓", "industry standard",
         ["Faithfulness",
          "Context precision",
          "Context recall",
          "Answer relevance",
          "",
          "All four passed",
          "industry threshold"]),
    ]
    x = 0.4
    for title, color, big, label, items in blocks:
        rect(s, x, 1.25, 4.13, 0.5, color)
        text(s, x, 1.27, 4.13, 0.5, title,
             size=11, bold=True, color=WHITE, align='center', anchor='middle')
        rect(s, x, 1.85, 4.13, 5.1, GREY_LT)
        text(s, x + 0.15, 2.0, 3.85, 1.3, big,
             size=44, bold=True, color=color, align='center')
        text(s, x + 0.15, 3.3, 3.85, 0.4, label,
             size=11, color=GREY, align='center')
        text(s, x + 0.25, 3.85, 3.7, 3.0, '\n'.join(items),
             size=10, color=BLACK, font='Consolas')
        x += 4.21
    footer(s, 15)


def s16(prs):
    """Conclusion + Future"""
    s = add_slide(prs)
    title_bar(s, "Conclusion & Future Work",
              "Compresses days into minutes without trading speed for trust")

    # Delivered (left)
    text(s, 0.4, 1.25, 6.2, 0.4, "WHAT WAS DELIVERED",
         size=11, bold=True, color=NAVY)
    rect(s, 0.4, 1.7, 6.2, 5.5, GREY_LT)
    delivered = [
        "End-to-end AI compliance platform",
        "Three jurisdictions (BH · IN · KW)",
        "Six core analyst-facing features",
        "Verbatim citation grounding on every output",
        "Seven-tier defence-in-depth shell",
        "Append-only audit log (28 events)",
        "SHA-256 export integrity hash",
        "Evaluated at three independent layers",
        "On-prem · zero data egress",
    ]
    y = 1.9
    for d in delivered:
        text(s, 0.6, y, 0.4, 0.4, "✓",
             size=14, bold=True, color=GREEN)
        text(s, 1.0, y, 5.4, 0.4, d, size=12, color=BLACK)
        y += 0.55

    # Future (right)
    text(s, 6.8, 1.25, 6.2, 0.4, "FUTURE WORK",
         size=11, bold=True, color=NAVY)
    rect(s, 6.8, 1.7, 6.2, 5.5, GREY_LT)
    future = [
        ("Scale to more jurisdictions",       "UAE, Saudi Arabia, EU GDPR"),
        ("Real-time regulatory change feeds", "Auto-update on amendments"),
        ("Adjacent regulated domains",         "AML, cyber risk, op resilience"),
        ("Adversarial AI red-teaming",         "Continuous safety testing"),
        ("Reviewer feedback → AI loop",        "Continuous learning"),
    ]
    y = 1.9
    for name, desc in future:
        text(s, 6.95, y, 0.4, 0.5, "◆",
             size=14, bold=True, color=AMBER)
        text(s, 7.35, y, 5.55, 0.3, name,
             size=12, bold=True, color=BLACK)
        text(s, 7.35, y + 0.32, 5.55, 0.3, desc,
             size=10, color=GREY)
        y += 0.95
    footer(s, 16)


def s17(prs):
    """Challenges + close"""
    s = add_slide(prs)
    title_bar(s, "Challenges & How Solved")

    rows = [
        ("AI hallucination",
         "Citation verifier + DeBERTa NLI + SafeFallback"),
        ("Cross-jurisdictional terminology drift",
         "9-term citation-audited dictionary + synonym expansion"),
        ("Prompt injection in PDFs",
         "Two-tier scanner + fail-closed quarantine"),
        ("On-prem deployment without GPU",
         "CPU-friendly models (BGE-small, MiniLM)"),
        ("Audit-defensibility for regulators",
         "7-tier shell + append-only audit + SHA-256"),
        ("NDA + thesis timeline in parallel",
         "Architecture-first docs + anonymised artefacts"),
    ]
    rect(s, 0.4, 1.25, 12.5, 0.4, NAVY)
    text(s, 0.5, 1.28, 5.5, 0.4, "CHALLENGE",
         size=11, bold=True, color=WHITE, anchor='middle')
    text(s, 6.2, 1.28, 6.5, 0.4, "HOW SOLVED",
         size=11, bold=True, color=WHITE, anchor='middle')

    y = 1.7
    for i, (chal, sol) in enumerate(rows):
        if i % 2 == 0:
            rect(s, 0.4, y, 12.5, 0.78, GREY_LT)
        text(s, 0.5, y, 5.5, 0.78, chal,
             size=11, bold=True, color=BLACK, anchor='middle')
        text(s, 6.2, y, 6.5, 0.78, sol,
             size=10, color=BLACK, anchor='middle')
        y += 0.78

    rect(s, 0.4, 6.85, 12.5, 0.5, GREEN)
    text(s, 0.4, 6.85, 12.5, 0.5,
         "Thank you. Questions?",
         size=16, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 17)


# ════════════════════════════════════════════════════════════════════════════

def main():
    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    builders = [s01, s02, s03, s04, s05, s06, s07, s08, s09,
                s10, s11, s12, s13, s14, s15, s16, s17]
    for i, fn in enumerate(builders, 1):
        print(f'Building slide {i:2d}: {fn.__name__}')
        fn(prs)

    prs.save(str(OUTPUT))
    print(f'\nDone. Saved to {OUTPUT}')
    print(f'Slide count: {len(prs.slides)}')


if __name__ == '__main__':
    main()
