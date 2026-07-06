"""Build the CJPCA demo deck FROM SCRATCH using the template's brand colors.

Strategy:
1. Load the template (we'll inherit slide master, fonts, color palette)
2. Strip every existing slide (53 of them — all Slidesgo placeholders)
3. Build 17 clean main slides + 5 algorithm backup slides
4. Save as CJPCA_Demo_Deck.pptx

Each slide is built with explicit boxes, tables, and text — no relying on the
template's existing visual placeholders.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / 'demo' / '202202017_demo.pptx'
OUTPUT   = ROOT / 'demo' / 'CJPCA_Demo_Deck_v2.pptx'


# ── Brand palette (from template's color scheme) ────────────────────────────
NAVY        = RGBColor(0x00, 0x25, 0x83)
DARK_NAVY   = RGBColor(0x00, 0x3B, 0xA3)
LIGHT_BLUE  = RGBColor(0x4A, 0x8C, 0xFF)
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
BLACK       = RGBColor(0x1F, 0x29, 0x37)
GREY_LIGHT  = RGBColor(0xEF, 0xEF, 0xEF)
GREY_MID    = RGBColor(0xCB, 0xCB, 0xCB)
GREY_DARK   = RGBColor(0x6B, 0x72, 0x80)
GREEN       = RGBColor(0x15, 0x80, 0x3D)
AMBER       = RGBColor(0xB0, 0x7A, 0x00)
RED         = RGBColor(0xB9, 0x1C, 0x1C)
CODE_BG     = RGBColor(0x1E, 0x1E, 0x1E)
CODE_TEXT   = RGBColor(0xC8, 0xF5, 0xC8)

# Standard slide is 13.33 x 7.5 inches (widescreen 16:9)


# ── Helpers ─────────────────────────────────────────────────────────────────

def strip_slides(prs):
    """Remove every slide from the presentation, keeping layouts/masters."""
    sldIdLst = prs.slides._sldIdLst
    for sld in list(sldIdLst):
        sldIdLst.remove(sld)


def add_slide(prs):
    """Add a blank slide using the BLANK layout."""
    blank_layout = prs.slide_layouts[10]   # BLANK layout
    return prs.slides.add_slide(blank_layout)


def rect(slide, x, y, w, h, fill, line=None, shadow=False):
    """Add a filled rectangle in inches."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line:
        shape.line.color.rgb = line
        shape.line.width = Pt(0.5)
    else:
        shape.line.fill.background()
    if not shadow:
        shape.shadow.inherit = False
    return shape


def text(slide, x, y, w, h, content, *,
         size=12, bold=False, color=BLACK, align='left',
         anchor='top', font='Calibri'):
    """Add a text box. Content can be a string (with \n) or a list of strings."""
    align_map = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}
    anchor_map = {'top': MSO_ANCHOR.TOP, 'middle': MSO_ANCHOR.MIDDLE, 'bottom': MSO_ANCHOR.BOTTOM}

    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.05)
    tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = anchor_map[anchor]

    lines = content if isinstance(content, list) else content.split('\n')
    for i, line in enumerate(lines):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.alignment = align_map[align]
        run = p.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = font
    return tb


def placeholder(slide, x, y, w, h, label, kind='DIAGRAM'):
    """Add a dashed-outline placeholder box for the user to drop content into.

    kind = 'DIAGRAM' | 'SCREENSHOT' | 'PSEUDOCODE' | 'CHART'
    """
    # Dashed outline using a rectangle with dotted line
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(0xFA, 0xFA, 0xFA)
    shape.line.color.rgb = GREY_MID
    shape.line.width = Pt(1.5)
    # Make it dashed
    from pptx.oxml.ns import qn
    ln = shape.line._get_or_add_ln()
    prstDash = ln.find(qn('a:prstDash'))
    if prstDash is None:
        prstDash = ln.makeelement(qn('a:prstDash'), {'val': 'dash'})
        ln.append(prstDash)
    else:
        prstDash.set('val', 'dash')
    shape.shadow.inherit = False

    # Inner label
    icon_map = {
        'DIAGRAM':    '⬛',
        'SCREENSHOT': '📷',
        'PSEUDOCODE': '⚙',
        'CHART':      '📊',
    }
    text(slide, x, y + h/2 - 0.5, w, 0.5, icon_map.get(kind, '◆'),
         size=28, color=GREY_MID, align='center')
    text(slide, x, y + h/2 + 0.05, w, 0.4,
         f"[ {kind} PLACEHOLDER ]",
         size=11, bold=True, color=GREY_DARK, align='center')
    text(slide, x, y + h/2 + 0.4, w, 0.4, label,
         size=9, color=GREY_DARK, align='center')


def title_bar(slide, title, subtitle=None):
    """Standard navy title bar at top of slide."""
    rect(slide, 0, 0, 13.33, 1.0, NAVY)
    text(slide, 0.4, 0.15, 12.5, 0.5, title,
         size=22, bold=True, color=WHITE, anchor='middle')
    if subtitle:
        text(slide, 0.4, 0.6, 12.5, 0.4, subtitle,
             size=11, color=RGBColor(0xCF, 0xDB, 0xF5), anchor='middle')


def footer(slide, n, total=17):
    """Tiny footer with slide number + project tag."""
    text(slide, 0.4, 7.15, 6, 0.3, "CJPCA · Viva Demo · 20 May 2026",
         size=8, color=GREY_DARK)
    text(slide, 12.4, 7.15, 0.9, 0.3, f"{n} / {total}",
         size=8, color=GREY_DARK, align='right')


# ════════════════════════════════════════════════════════════════════════════
# SLIDE BUILDERS — 17 main + 5 backup
# ════════════════════════════════════════════════════════════════════════════

def slide_01_title(prs):
    s = add_slide(prs)
    rect(s, 0, 0, 13.33, 7.5, NAVY)
    rect(s, 0, 4.7, 13.33, 0.04, LIGHT_BLUE)

    text(s, 1.0, 1.0, 11, 0.4,
         "IT8X99  ·  PROJECT DEMONSTRATION  ·  VIVA",
         size=11, color=LIGHT_BLUE, bold=True)

    text(s, 1.0, 1.6, 11, 1.2, "Cross-Jurisdictional Privacy",
         size=44, bold=True, color=WHITE)
    text(s, 1.0, 2.7, 11, 1.2, "Compliance Analyzer",
         size=44, bold=True, color=WHITE)

    text(s, 1.0, 4.0, 11, 0.5,
         "AI-assisted regulatory compliance for cross-border banking",
         size=16, color=GREY_LIGHT)

    text(s, 1.0, 5.0, 11, 1.2,
         ["Student            Zainab Ayman Abdulmajeed Isa Hammad",
          "CLP Company   Nasser Centre — AI Research & Development Centre",
          "Date                  20 May 2026"],
         size=13, color=WHITE)

    # NDA banner
    rect(s, 1.0, 6.4, 11.3, 0.7, RGBColor(0xFF, 0xC1, 0x07))
    text(s, 1.2, 6.45, 11, 0.6,
         "This project is under an NDA. Architecture, live functionality, and pseudocode are demonstrated; source code is not shown.",
         size=11, bold=True, color=BLACK, anchor='middle')


def slide_02_problem(prs):
    s = add_slide(prs)
    title_bar(s, "The Problem",
              "Banks across multiple jurisdictions face a growing compliance challenge")

    bullets = [
        "•  Banks operating across multiple regulatory jurisdictions face a growing operational challenge.",
        "",
        "•  Privacy laws differ in terminology and obligations — Bahrain calls them 'data subjects';",
        "    India calls them 'data principals'.",
        "",
        "•  Compliance teams currently interpret and map regulations against internal policies by hand.",
        "",
        "•  The process is slow, error-prone, and exposes the bank to regulatory penalties.",
        "",
        "",
        "Three jurisdictions in scope:",
    ]
    text(s, 0.7, 1.4, 12, 4.5, '\n'.join(bullets), size=15, color=BLACK)

    # Jurisdiction badges
    flags = [
        ("BAHRAIN",  "PDPL Law 30/2018 + 11 PDPA Orders",     NAVY),
        ("INDIA",    "DPDPA 2023 + RBI directions",            DARK_NAVY),
        ("KUWAIT",   "DPPR + CITRA frameworks",                LIGHT_BLUE),
    ]
    x = 0.7
    for name, sub, color in flags:
        rect(s, x, 5.8, 4.1, 0.95, color)
        text(s, x, 5.9, 4.1, 0.35, name, size=12, bold=True, color=WHITE, align='center')
        text(s, x + 0.1, 6.3, 3.9, 0.4, sub, size=9, color=WHITE, align='center')
        x += 4.2
    footer(s, 2)


def slide_03_aim_features(prs):
    s = add_slide(prs)
    title_bar(s, "Project Aim & Features",
              "Six features delivered, three partial or out of scope — visual status below")

    # AIM box (left half)
    rect(s, 0.4, 1.2, 5.5, 5.8, GREY_LIGHT)
    text(s, 0.6, 1.35, 5.2, 0.4, "THE AIM",
         size=10, bold=True, color=NAVY)
    text(s, 0.6, 1.8, 5.2, 4.5,
         "Equip compliance teams with an AI workspace that completes "
         "cross-jurisdictional regulatory review in minutes — with every "
         "AI finding grounded in a real regulatory clause and routed "
         "through reviewer sign-off before release.",
         size=14, color=BLACK)

    # AIM punchline
    rect(s, 0.6, 5.7, 5.1, 1.2, NAVY)
    text(s, 0.75, 5.85, 4.9, 0.4, "The contribution:",
         size=10, bold=True, color=WHITE)
    text(s, 0.75, 6.2, 4.9, 0.7,
         "Compress compliance review from days into minutes, without trading speed for trust.",
         size=11, color=WHITE)

    # FEATURES with status (right half)
    text(s, 6.2, 1.2, 6.7, 0.4, "FEATURES & STATUS",
         size=10, bold=True, color=NAVY)

    features = [
        ('✓', 'Cross-jurisdictional regulation comparison',   'DELIVERED', GREEN),
        ('✓', 'Policy-to-regulation coverage mapping',         'DELIVERED', GREEN),
        ('✓', 'Gap register + severity + AI remediation',      'DELIVERED', GREEN),
        ('✓', 'Citation-backed Copilot chat',                  'DELIVERED', GREEN),
        ('✓', 'Human-in-the-loop reviewer queue',              'DELIVERED', GREEN),
        ('✓', 'Analytics + audit dashboards',                  'DELIVERED', GREEN),
        ('✓', '7-tier defence-in-depth security shell',        'DELIVERED', GREEN),
        ('✓', 'Append-only audit log + SHA-256 export',        'DELIVERED', GREEN),
        ('⚠', 'Cross-jurisdictional auto-routing (V1)',        'PARTIAL',   AMBER),
        ('⚠', 'Arabic-language corpus support',                'PARTIAL',   AMBER),
        ('✗', 'Multi-tenant deployment',                        'NOT SCOPED', RED),
    ]
    y = 1.65
    for icon, label, status, color in features:
        text(s, 6.2, y, 0.35, 0.42, icon, size=15, bold=True, color=color)
        text(s, 6.6, y, 4.8, 0.42, label, size=11, color=BLACK, anchor='middle')
        text(s, 11.4, y, 1.5, 0.42, status, size=8.5, bold=True, color=color,
             align='right', anchor='middle')
        y += 0.46
    footer(s, 3)


def slide_04_client_fit(prs):
    s = add_slide(prs)
    title_bar(s, "Where I Fit In",
              "Internship at Nasser Centre · Banking client under NDA")

    # Top: parent org
    rect(s, 3.5, 1.5, 6.3, 1.0, NAVY)
    text(s, 3.5, 1.55, 6.3, 0.4, "Nasser Centre for Science & Technology",
         size=14, bold=True, color=WHITE, align='center')
    text(s, 3.5, 1.95, 6.3, 0.5, "Artificial Intelligence Research & Development Centre",
         size=11, color=GREY_LIGHT, align='center')

    # Down arrow
    text(s, 6.5, 2.55, 0.3, 0.4, "▼", size=20, color=NAVY, align='center')

    # Two children
    rect(s, 1.0, 3.1, 5.4, 1.7, GREY_LIGHT)
    text(s, 1.0, 3.2, 5.4, 0.4, "Project supervisors", size=12, bold=True, color=NAVY, align='center')
    text(s, 1.1, 3.65, 5.2, 1.1,
         "Qabas Elayan · Mohammed Albasri\n\nArchitectural review and technical guidance throughout the build",
         size=10, color=GREY_DARK, align='center')

    rect(s, 6.9, 3.1, 5.4, 1.7, LIGHT_BLUE)
    text(s, 6.9, 3.2, 5.4, 0.4, "Sole technical builder (me)",
         size=12, bold=True, color=WHITE, align='center')
    text(s, 7.0, 3.65, 5.2, 1.1,
         "End-to-end design, implementation,\nevaluation, and on-premises deployment.\nEvery technical decision was eval-driven.",
         size=10, color=WHITE, align='center')

    # Bank client at bottom
    text(s, 6.5, 4.95, 0.3, 0.4, "▼", size=20, color=AMBER, align='center')
    rect(s, 3.5, 5.4, 6.3, 1.4, AMBER)
    text(s, 3.5, 5.5, 6.3, 0.4, "Banking client (under NDA)",
         size=14, bold=True, color=WHITE, align='center')
    text(s, 3.6, 5.95, 6.1, 0.85,
         "Use-case sponsor · Document corpus owner · Compliance team end-user",
         size=10, color=WHITE, align='center')
    footer(s, 4)


def slide_05_tech_stack(prs):
    s = add_slide(prs)
    title_bar(s, "Technology Stack — Chosen vs Alternatives",
              "Every tech choice was eval-driven, not a default")

    # Header row
    rect(s, 0.4, 1.2, 12.5, 0.42, NAVY)
    text(s, 0.5, 1.22, 2.6, 0.42, "CATEGORY", size=10, bold=True, color=WHITE, anchor='middle')
    text(s, 3.2, 1.22, 3.5, 0.42, "CHOSEN", size=10, bold=True, color=WHITE, anchor='middle')
    text(s, 6.8, 1.22, 6.0, 0.42, "REJECTED — REASON",   size=10, bold=True, color=WHITE, anchor='middle')

    rows = [
        ("Web framework",   "Django 5",                    "FastAPI — no built-in admin / RBAC / ORM"),
        ("Vector DB",       "ChromaDB",                    "Pinecone — paid SaaS, breaks zero-egress"),
        ("Keyword search",  "SQLite FTS5",                 "In-memory BM25 — drops hit@5 0.95 → 0.875"),
        ("Embedding",       "BGE-small-en-v1.5",           "OpenAI ada — paid + cloud, breaks NDA"),
        ("Reranker",        "ms-marco-MiniLM",             "BGE-reranker-large — MiniLM beat it on our corpus"),
        ("LLM primary",     "Claude Haiku 4.5 (OpenRouter)", "GPT-4o-mini — eval'd worse on verbatim citation"),
        ("LLM fallback",    "Ollama llama3.2:1b (local)",  "Cloud-only — fails on internet outage"),
        ("Reasoning fw",    "LangGraph",                   "Linear LangChain — no loops for verify-correct cycle"),
        ("Hallucination",   "DeBERTa-v3 NLI cross-encoder", "LLM-as-judge — too slow / expensive per row"),
        ("PDF parser",      "Docling",                     "PyPDF — loses headers and tables"),
    ]
    y = 1.65
    for i, (cat, chosen, why) in enumerate(rows):
        if i % 2 == 0:
            rect(s, 0.4, y, 12.5, 0.46, GREY_LIGHT)
        text(s, 0.5, y, 2.6, 0.46, cat, size=10, bold=True, color=BLACK, anchor='middle')
        text(s, 3.2, y, 3.5, 0.46, chosen, size=10, bold=True, color=NAVY, anchor='middle')
        text(s, 6.8, y, 6.0, 0.46, why, size=9, color=GREY_DARK, anchor='middle')
        y += 0.46
    footer(s, 5)


def slide_06_architecture(prs):
    s = add_slide(prs)
    title_bar(s, "System Architecture",
              "Five layers built bottom-up · AI pipeline runs through three lanes")

    # LEFT — 5-layer architecture stack
    text(s, 0.4, 1.25, 6, 0.4, "5-LAYER ARCHITECTURE (built bottom-up)",
         size=11, bold=True, color=NAVY)

    layers = [
        ("WEB",        "Django (10 apps) · HTMX · Alpine · Channels", LIGHT_BLUE),
        ("REASONING",  "LangGraph · Claude Haiku · Ollama · Pydantic", NAVY),
        ("RETRIEVAL",  "BM25 (FTS5) + Vector (Chroma) + RRF + Rerank", DARK_NAVY),
        ("INGESTION",  "Docling · Chunker · Injection Scan · Embed · Index", AMBER),
        ("DATA",       "43 documents · 25-field metadata · 4 jurisdictions", GREEN),
    ]
    y = 1.75
    for name, desc, color in layers:
        rect(s, 0.4, y, 6.2, 0.95, color)
        text(s, 0.55, y + 0.1, 5.9, 0.35, name,
             size=12, bold=True, color=WHITE)
        text(s, 0.55, y + 0.45, 5.9, 0.45, desc,
             size=9, color=WHITE)
        y += 1.02

    # RIGHT — AI pipeline 3 lanes
    text(s, 6.9, 1.25, 6, 0.4, "AI PIPELINE — 3 EXECUTION LANES",
         size=11, bold=True, color=NAVY)

    lanes = [
        ("INGESTION", "Documents → Chunks", "Two-tier injection scan\nat ingest boundary", AMBER),
        ("RETRIEVAL", "Query → Top-K chunks", "BM25 + Vector + RRF\n+ Cross-encoder rerank", NAVY),
        ("REASONING", "Chunks → Verified output", "Draft → Verify → Correct\n→ Finalise / Fallback", GREEN),
    ]
    x = 6.9
    for name, top, bottom, color in lanes:
        rect(s, x, 1.75, 2.0, 4.6, color)
        text(s, x, 1.85, 2.0, 0.4, name,
             size=10, bold=True, color=WHITE, align='center')
        text(s, x + 0.1, 2.4, 1.8, 1.0, top,
             size=9, color=WHITE, align='center')
        rect(s, x + 0.25, 3.6, 1.5, 0.02, WHITE)
        text(s, x + 0.1, 3.8, 1.8, 1.5, bottom,
             size=8, color=WHITE, align='center')
        x += 2.05

    # Bottom callout
    rect(s, 0.4, 6.8, 12.5, 0.4, NAVY)
    text(s, 0.4, 6.8, 12.5, 0.4,
         "Each layer only works if the one below it works. Bottom-up construction.",
         size=10, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 6)


def slide_07_security(prs):
    s = add_slide(prs)
    title_bar(s, "Security Architecture",
              "Defence-in-depth shell · 7 independent tiers between internet and compliance evidence")

    # Header
    rect(s, 0.4, 1.2, 12.5, 0.4, NAVY)
    text(s, 0.5, 1.22, 0.6, 0.4, "TIER",     size=10, bold=True, color=WHITE, anchor='middle')
    text(s, 1.15, 1.22, 2.2, 0.4, "LAYER",   size=10, bold=True, color=WHITE, anchor='middle')
    text(s, 3.4, 1.22, 5.3, 0.4, "MECHANISM", size=10, bold=True, color=WHITE, anchor='middle')
    text(s, 8.75, 1.22, 4.1, 0.4, "BLOCKS",   size=10, bold=True, color=WHITE, anchor='middle')

    tiers = [
        ("T7", "Network perimeter",   "TLS 1.3 · HSTS preload · GeoFence · Caddy", "Out-of-region traffic"),
        ("T6", "Identity & access",   "django-axes lockout · TOTP MFA · force-enroll", "Brute force · stolen pwds"),
        ("T5", "Authorisation",       "RBAC (Analyst / Reviewer / Admin)",          "Wrong-role data access"),
        ("T4", "Application hardening","CSP · CSRF · 12-char pwds · secure cookies", "XSS · CSRF · session hijack"),
        ("T3", "Content defence",     "Two-tier prompt-injection scanner",          "Prompt injection in PDFs"),
        ("T2", "AI safety",           "Citation verifier · NLI gate · SafeFallback",  "Hallucinated AI output"),
        ("T1", "Forensic layer",      "AuditLog (28 events) · SHA-256 export hash", "Silent tampering"),
    ]
    y = 1.62
    for i, (tier, layer, mech, blocks) in enumerate(tiers):
        if i % 2 == 0:
            rect(s, 0.4, y, 12.5, 0.6, GREY_LIGHT)
        text(s, 0.5, y, 0.6, 0.6, tier,
             size=14, bold=True, color=NAVY, align='center', anchor='middle')
        text(s, 1.15, y, 2.2, 0.6, layer,
             size=10, bold=True, color=BLACK, anchor='middle')
        text(s, 3.4, y, 5.3, 0.6, mech,
             size=9, color=BLACK, anchor='middle')
        text(s, 8.75, y, 4.1, 0.6, blocks,
             size=9, color=RED, anchor='middle')
        y += 0.6

    # Bottom callout
    rect(s, 0.4, 6.8, 12.5, 0.4, NAVY)
    text(s, 0.4, 6.8, 12.5, 0.4,
         "Each tier independently rejects threats that bypass the layer above. No single failure compromises the whole.",
         size=10, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 7)


def slide_08_journey(prs):
    s = add_slide(prs)
    title_bar(s, "The User Journey",
              "Admin sets up · Analyst works · Reviewer signs off · Every action audited")

    roles = [
        ("PHASE 1",  "ADMIN",
         ["Create users + assign roles",
          "Trigger forced MFA enrollment",
          "Upload documents",
          "Approve quarantined chunks",
          "Monitor full audit log"],
         NAVY),
        ("PHASE 2",  "ANALYST",
         ["Run cross-jurisdictional comparison",
          "Map internal policies to regulations",
          "Review AI-drafted gap remediation",
          "Ask citation-backed Copilot",
          "Submit work to reviewer"],
         LIGHT_BLUE),
        ("PHASE 3",  "REVIEWER",
         ["See submitted work in queue",
          "Accept / Modify / Reject each row",
          "Export executive summary PDF",
          "PDF embeds SHA-256 audit hash",
          "Approved rows ship as evidence"],
         GREEN),
    ]
    x = 0.5
    for phase, role, items, color in roles:
        rect(s, x, 1.3, 4.1, 0.8, color)
        text(s, x, 1.32, 4.1, 0.3, phase,
             size=10, color=WHITE, align='center', bold=True)
        text(s, x, 1.6, 4.1, 0.4, role,
             size=18, bold=True, color=WHITE, align='center')

        rect(s, x, 2.1, 4.1, 4.6, GREY_LIGHT)
        bullets = ["•  " + i for i in items]
        text(s, x + 0.15, 2.3, 3.9, 4.3, '\n\n'.join(bullets),
             size=11, color=BLACK)
        x += 4.25

    # Bottom: audit banner spans width
    rect(s, 0.5, 6.85, 12.3, 0.5, AMBER)
    text(s, 0.5, 6.85, 12.3, 0.5,
         "Every action across all three roles → AuditLog (append-only, 28 canonical event types)",
         size=11, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 8)


def slide_09_admin(prs):
    s = add_slide(prs)
    title_bar(s, "Phase 1: Admin — Setup",
              "Live demo: user creation · MFA enrollment · quarantine review")

    # LEFT — 6-stage ingestion pipeline
    text(s, 0.4, 1.25, 6.2, 0.4, "6-STAGE INGESTION PIPELINE",
         size=11, bold=True, color=NAVY)

    stages = [
        ("1", "PARSE",          "Docling · no OCR · preserves headers"),
        ("2", "CHUNK",          "Markdown headers + parent-child fallback"),
        ("3", "INJECTION SCAN", "Tier A regex + Tier B LLM judge + fail-closed"),
        ("4", "EMBED",          "BGE-small + jurisdiction prefix"),
        ("5", "INDEX",          "ChromaDB + SQLite FTS5 dual write"),
        ("6", "READY",          "Status → INDEXED (atomic transaction)"),
    ]
    y = 1.7
    for num, name, desc in stages:
        rect(s, 0.4, y, 0.55, 0.75, NAVY)
        text(s, 0.4, y, 0.55, 0.75, num,
             size=22, bold=True, color=WHITE, align='center', anchor='middle')
        rect(s, 1.0, y, 5.6, 0.75, GREY_LIGHT)
        text(s, 1.15, y + 0.05, 5.4, 0.35, name,
             size=11, bold=True, color=NAVY)
        text(s, 1.15, y + 0.4, 5.4, 0.35, desc,
             size=9, color=GREY_DARK)
        y += 0.82

    # RIGHT — Live demo plan
    text(s, 7.0, 1.25, 6, 0.4, "LIVE DEMO — ADMIN ACTIONS",
         size=11, bold=True, color=NAVY)

    actions = [
        ("01", "User creation",
         "Create a new analyst account · forced password-change + MFA enrollment on first login"),
        ("02", "MFA enrollment",
         "TOTP secret + QR code shown · backup tokens issued · enforced by middleware (not view code)"),
        ("03", "Document upload",
         "Upload a PDF · WebSocket streams 6-stage progress · safe chunks indexed, suspicious chunks quarantined"),
        ("04", "Quarantine review",
         "3 chunks flagged: INST_OVERRIDE, FORCED_VERDICT, SAFETY_BYPASS · admin approves or rejects"),
        ("05", "Audit oversight",
         "Full visibility into all 28 canonical event types across all roles"),
    ]
    y = 1.7
    for num, name, desc in actions:
        rect(s, 7.0, y, 0.55, 0.85, AMBER)
        text(s, 7.0, y, 0.55, 0.85, num,
             size=12, bold=True, color=WHITE, align='center', anchor='middle')
        text(s, 7.65, y + 0.02, 5.5, 0.35, name,
             size=11, bold=True, color=BLACK)
        text(s, 7.65, y + 0.38, 5.5, 0.5, desc,
             size=9, color=GREY_DARK)
        y += 0.95

    footer(s, 9)


def slide_10_comparison(prs):
    s = add_slide(prs)
    title_bar(s, "Phase 2A: Analyst — Cross-Jurisdictional Comparison",
              "Live demo + lift the curtain: hybrid retrieval and the verification gate")

    # LEFT — Hybrid retrieval diagram
    text(s, 0.4, 1.25, 6, 0.4, "HYBRID RETRIEVAL",
         size=11, bold=True, color=NAVY)

    rect(s, 0.4, 1.7, 2.85, 1.0, NAVY)
    text(s, 0.4, 1.75, 2.85, 0.4, "VECTOR PATH",
         size=10, bold=True, color=WHITE, align='center')
    text(s, 0.5, 2.15, 2.65, 0.55,
         "BGE-small + juris prefix\nChromaDB cosine · top-20",
         size=8, color=WHITE, align='center')

    rect(s, 3.4, 1.7, 2.85, 1.0, NAVY)
    text(s, 3.4, 1.75, 2.85, 0.4, "BM25 PATH",
         size=10, bold=True, color=WHITE, align='center')
    text(s, 3.5, 2.15, 2.65, 0.55,
         "OR-fused tokens · FTS5\nfilter pushdown · top-20",
         size=8, color=WHITE, align='center')

    # Down arrows
    text(s, 1.55, 2.7, 0.3, 0.4, "▼", size=16, color=NAVY, align='center')
    text(s, 4.55, 2.7, 0.3, 0.4, "▼", size=16, color=NAVY, align='center')

    rect(s, 0.4, 3.1, 5.85, 0.55, AMBER)
    text(s, 0.4, 3.1, 5.85, 0.55, "RRF FUSION  (k=60)",
         size=12, bold=True, color=WHITE, align='center', anchor='middle')

    text(s, 3.0, 3.65, 0.3, 0.4, "▼", size=16, color=AMBER, align='center')

    rect(s, 0.4, 4.05, 5.85, 0.55, GREEN)
    text(s, 0.4, 4.05, 5.85, 0.55, "CROSS-ENCODER RERANK (ms-marco-MiniLM)",
         size=11, bold=True, color=WHITE, align='center', anchor='middle')

    text(s, 3.0, 4.6, 0.3, 0.4, "▼", size=16, color=GREEN, align='center')

    rect(s, 0.4, 5.0, 5.85, 0.55, RGBColor(0x4A, 0x4A, 0x4A))
    text(s, 0.4, 5.0, 5.85, 0.55, "Top-K chunks → LangGraph reasoning",
         size=10, bold=True, color=WHITE, align='center', anchor='middle')

    text(s, 0.4, 5.75, 6, 1.0,
         "▸ Filter pushdown to BOTH databases — LLM physically\n   cannot see out-of-scope chunks (SQL constraint, not prompt).\n\n▸ Eval-validated: hit_rate@5 = 0.95",
         size=9, bold=True, color=NAVY)

    # RIGHT — Verification gate pseudocode
    text(s, 6.8, 1.25, 6, 0.4, "VERIFICATION GATE (pseudocode)",
         size=11, bold=True, color=NAVY)
    rect(s, 6.8, 1.7, 6.1, 5.0, CODE_BG)

    pseudocode = """verify_obligation(obligation, retrieved):

    # 1. Structural check
    quote = obligation.exact_quote
    chunk = lookup(obligation.chunk_id)

    if quote not in chunk.content:
        # 2. Cross-chunk recovery
        for c in retrieved:
            if quote in c.content:
                auto_correct(chunk_id = c.id)
                return VERIFIED
        return UNVERIFIED

    # 3. NLI semantic check
    entail = DeBERTa(chunk, ai_summary)
    risk = 1 - entail

    # 4. Drop pure inventions
    if no_citation and risk > 0.90:
        drop_obligation()

    return VERIFIED"""
    text(s, 6.95, 1.85, 5.95, 4.85, pseudocode,
         size=10, color=CODE_TEXT, font='Consolas')

    text(s, 6.8, 6.85, 6.1, 0.3,
         "▸ Three independent grounding signals — ALL must hold",
         size=9, bold=True, color=NAVY)
    footer(s, 10)


def slide_11_mapping(prs):
    s = add_slide(prs)
    title_bar(s, "Phase 2B: Analyst — Mapping + Copilot + Submit",
              "Live demo · Gap Register with AI remediation · Citation-backed Copilot")

    # LEFT — Policy-driven auto-routing flow
    text(s, 0.4, 1.25, 6, 0.4, "POLICY-DRIVEN AUTO-ROUTING",
         size=11, bold=True, color=NAVY)

    steps = [
        ("Read what topics the POLICY covers", "via chunk_tags sidecar"),
        ("Read what topics the REGULATION covers", "same classifier"),
        ("Intersect: topics in BOTH", "→ eligible set"),
        ("Per topic: topic-scoped mapping pass", "filter pushdown both sides"),
        ("Skip topics policy covers but reg doesn't", "audit note"),
    ]
    y = 1.7
    for i, (text_main, text_sub) in enumerate(steps, 1):
        rect(s, 0.4, y, 0.55, 0.75, NAVY)
        text(s, 0.4, y, 0.55, 0.75, str(i),
             size=22, bold=True, color=WHITE, align='center', anchor='middle')
        rect(s, 1.0, y, 5.6, 0.75, GREY_LIGHT)
        text(s, 1.15, y + 0.05, 5.4, 0.4, text_main,
             size=10.5, bold=True, color=BLACK)
        text(s, 1.15, y + 0.4, 5.4, 0.35, text_sub,
             size=9, color=GREY_DARK)
        y += 0.85

    text(s, 0.4, 6.05, 6.2, 0.9,
         "Methodology: a retention policy never gets falsely scored 'Not Covered' against breach-notification clauses, because the system never asks that question.",
         size=9, color=NAVY, bold=True)

    # RIGHT — What analyst sees
    text(s, 6.8, 1.25, 6, 0.4, "WHAT THE ANALYST SEES",
         size=11, bold=True, color=NAVY)

    items = [
        ("Gap Register",
         "Each gap: regulation citation + severity\nbadge (LOW/MED/HIGH) + AI-drafted remediation"),
        ("AI Remediation Drafting",
         "LLM proposes how to fix each gap. Analyst can\nedit before submitting. Provenance tracked."),
        ("Citation-Backed Copilot",
         "Ask: 'What does PDPL say about access rights?'\n→ Answer with citation chips linking to source"),
        ("Document Viewer",
         "Click citation chip → opens viewer with the\ncited section highlighted in context"),
        ("Submit to Reviewer",
         "Click 'Send to reviewer' → handoff fires\naudit row + appears on reviewer's queue"),
    ]
    y = 1.7
    for name, desc in items:
        text(s, 6.8, y, 6, 0.3, "▸ " + name,
             size=11, bold=True, color=AMBER)
        text(s, 7.05, y + 0.3, 5.8, 0.7, desc,
             size=9, color=BLACK)
        y += 1.05

    footer(s, 11)


def slide_12_reviewer(prs):
    s = add_slide(prs)
    title_bar(s, "Phase 3: Reviewer — Approve + Export",
              "Live demo · Reviewer signs off · PDF embeds tamper-evident SHA-256 hash")

    # Top — lifecycle state machine
    text(s, 0.4, 1.25, 12.5, 0.4, "LIFECYCLE STATE MACHINE",
         size=11, bold=True, color=NAVY)

    states = [
        ("DRAFT",     NAVY,        "Created by\nanalyst's\nworkflow"),
        ("REVIEWED",  LIGHT_BLUE,  "Analyst clicks\n'Send to reviewer'\n+ audit row"),
        ("APPROVED",  GREEN,       "Reviewer accepts\n(or modifies\nwith diff stored)"),
        ("EXPORTED",  AMBER,       "Reviewer downloads\nPDF with embedded\nSHA-256 hash"),
    ]
    x = 0.4
    for state, color, desc in states:
        rect(s, x, 1.7, 2.95, 1.15, color)
        text(s, x, 1.78, 2.95, 0.4, state,
             size=14, bold=True, color=WHITE, align='center')
        text(s, x + 0.1, 2.18, 2.75, 0.65, desc,
             size=9, color=WHITE, align='center')
        x += 3.13

    # Arrows
    for ax in [3.4, 6.55, 9.68]:
        text(s, ax, 2.15, 0.18, 0.4, "▶", size=15, bold=True, color=DARK_NAVY)

    # Bottom — SHA-256 explanation with code
    text(s, 0.4, 3.1, 12.5, 0.4, "SHA-256 EXPORT INTEGRITY",
         size=11, bold=True, color=NAVY)
    rect(s, 0.4, 3.55, 12.5, 3.0, CODE_BG)

    sha_code = """audit_hash(run):

    payload = JOIN("|", [
        run.class_name,                  # 'ComparisonRun'
        str(run.pk),                     # '107'
        run.status,                      # 'complete'
        str(run.completed_at),           # ISO timestamp
        str(run.submitted_for_review_at),
        str(run.created_by_id)
    ])

    return SHA256(payload).hexdigest()[:16]   # embedded in PDF footer"""
    text(s, 0.6, 3.7, 12.0, 2.8, sha_code,
         size=10.5, color=CODE_TEXT, font='Consolas')

    rect(s, 0.4, 6.65, 12.5, 0.45, AMBER)
    text(s, 0.4, 6.65, 12.5, 0.45,
         "Not a digital signature — TAMPER EVIDENCE. Recipient recomputes hash against DB row. Silent edits → hashes diverge.",
         size=10, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 12)


def slide_13_audit(prs):
    s = add_slide(prs)
    title_bar(s, "The Audit Trail Closes the Loop",
              "28 canonical event types · append-only · user role snapshotted at action time")

    text(s, 0.4, 1.25, 12.5, 0.4,
         "Every action by every role lands in one append-only table",
         size=11, bold=True, color=NAVY)

    categories = [
        ("AUTH / SESSION (8)", NAVY,
         "auth.login\nauth.login_failed\nauth.logout\nauth.idle_timeout\nauth.mfa_enrolled\nauth.mfa_reset\nauth.backup_codes_regen\nauth.sessions_terminated"),
        ("ANALYST FLOWS (6)", LIGHT_BLUE,
         "comparison.run\ncomparison.complete\ncomparison.failed\nmapping.run\nmapping.complete\nmapping.failed"),
        ("REVIEWER (4)", GREEN,
         "review.submit\nreview.accept\nreview.reject\nreview.modify"),
        ("CORPUS (4)", AMBER,
         "document.upload\ndocument.delete\ningestion.complete\ningestion.failed"),
        ("QUARANTINE (3)", RED,
         "quarantine.flagged\nquarantine.approved\nquarantine.rejected"),
        ("USER ADMIN (5)", DARK_NAVY,
         "user.created\nuser.role_changed\nuser.disabled\nuser.password_reset\nuser.password_changed"),
    ]
    x = 0.4
    y = 1.75
    col = 0
    for name, color, events in categories:
        rect(s, x, y, 4.13, 0.4, color)
        text(s, x, y + 0.02, 4.13, 0.4, name,
             size=10, bold=True, color=WHITE, align='center', anchor='middle')
        rect(s, x, y + 0.42, 4.13, 2.2, GREY_LIGHT)
        text(s, x + 0.15, y + 0.5, 3.85, 2.1, events,
             size=8.5, color=BLACK, font='Consolas')
        x += 4.21
        col += 1
        if col >= 3:
            col = 0
            x = 0.4
            y += 2.7

    rect(s, 0.4, 6.7, 12.5, 0.5, AMBER)
    text(s, 0.4, 6.7, 12.5, 0.5,
         "user_role_at_time is SNAPSHOTTED — historical record never silently revises itself",
         size=10, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 13)


def slide_14_database(prs):
    s = add_slide(prs)
    title_bar(s, "Database Schema",
              "Persistence behind the user journey · indexed · append-only audit log")

    # Document (root, top centre)
    rect(s, 5.0, 1.4, 3.3, 0.85, NAVY)
    text(s, 5.0, 1.45, 3.3, 0.35, "Document", size=13, bold=True, color=WHITE, align='center')
    text(s, 5.0, 1.78, 3.3, 0.45,
         "id · jurisdiction · doc_type\nchunk_count · status",
         size=9, color=WHITE, align='center')

    # Three branches
    rect(s, 0.6, 3.0, 3.3, 0.85, LIGHT_BLUE)
    text(s, 0.6, 3.05, 3.3, 0.35, "IngestionJob", size=12, bold=True, color=WHITE, align='center')
    text(s, 0.6, 3.4, 3.3, 0.45,
         "stage (1-6) · progress_pct\nstatus · WebSocket-streamed",
         size=9, color=WHITE, align='center')

    rect(s, 0.6, 4.1, 3.3, 0.85, RED)
    text(s, 0.6, 4.15, 3.3, 0.35, "QuarantinedChunk", size=12, bold=True, color=WHITE, align='center')
    text(s, 0.6, 4.5, 3.3, 0.45,
         "rule_id · tier (A/B)\nseverity · decided_by",
         size=9, color=WHITE, align='center')

    rect(s, 5.0, 3.0, 3.3, 0.85, GREEN)
    text(s, 5.0, 3.05, 3.3, 0.35, "ComparisonRun", size=12, bold=True, color=WHITE, align='center')
    text(s, 5.0, 3.4, 3.3, 0.45,
         "pair_key · reg_a · reg_b\ntopics · status",
         size=9, color=WHITE, align='center')

    rect(s, 5.0, 4.1, 3.3, 0.85, GREEN)
    text(s, 5.0, 4.15, 3.3, 0.35, "ComparisonResult", size=12, bold=True, color=WHITE, align='center')
    text(s, 5.0, 4.5, 3.3, 0.45,
         "relationship · confidence\ncitation_verified · hall_risk",
         size=9, color=WHITE, align='center')

    rect(s, 9.4, 3.0, 3.3, 0.85, AMBER)
    text(s, 9.4, 3.05, 3.3, 0.35, "MappingAnalysis", size=12, bold=True, color=WHITE, align='center')
    text(s, 9.4, 3.4, 3.3, 0.45,
         "policy_doc · regulations[]\nstatus · gap_count",
         size=9, color=WHITE, align='center')

    rect(s, 9.4, 4.1, 3.3, 0.85, AMBER)
    text(s, 9.4, 4.15, 3.3, 0.35, "ObligationMapping → Gap", size=11, bold=True, color=WHITE, align='center')
    text(s, 9.4, 4.5, 3.3, 0.45,
         "coverage · severity\nremediation · priority",
         size=9, color=WHITE, align='center')

    # AuditLog independent at bottom
    rect(s, 0.6, 5.5, 12.1, 1.3, DARK_NAVY)
    text(s, 0.6, 5.55, 12.1, 0.45, "AuditLog (append-only)",
         size=15, bold=True, color=WHITE, align='center')
    text(s, 0.6, 6.0, 12.1, 0.8,
         "event_type · user · user_role_at_time (SNAPSHOTTED) · ip · timestamp · description · change_detail (JSON)\nIndexed on (user, timestamp) and (event_type, timestamp) · 28 canonical event types · no UPDATE / DELETE paths",
         size=10, color=WHITE, align='center')

    footer(s, 14)


def slide_15_evaluation(prs):
    s = add_slide(prs)
    title_bar(s, "Evaluation",
              "Three independent eval layers · empirical justification for every design choice")

    # Three columns
    blocks = [
        ("RETRIEVAL EVAL", NAVY,
         "hit_rate @ top-5",
         "0.95",
         ["LlamaIndex RetrieverEvaluator",
          "8 hand-picked + synthetic Q/A",
          "spans 4 jurisdictions",
          "",
          "Drops to 0.875 with in-memory BM25",
          "→ empirical justification for FTS5"]),
        ("REASONING EVAL", GREEN,
         "first-try verify pass",
         "80%",
         ["End-to-end pipeline test",
          "correction trigger     ~12%",
          "fallback rate                ~3%",
          "citation match            >95%",
          "",
          "Latency p50 ~2s warm",
          "Latency p95 ~12s cold"]),
        ("RAGAS CROSS-CHECK", AMBER,
         "industry standard",
         "✓",
         ["Faithfulness check",
          "Context precision",
          "Context recall",
          "Answer relevance",
          "",
          "Same queries cross-checked",
          "against RAGAS framework"]),
    ]
    x = 0.4
    for title, color, label, big, items in blocks:
        rect(s, x, 1.25, 4.13, 0.5, color)
        text(s, x, 1.27, 4.13, 0.5, title,
             size=11, bold=True, color=WHITE, align='center', anchor='middle')

        rect(s, x, 1.85, 4.13, 5.0, GREY_LIGHT)
        text(s, x + 0.15, 2.0, 3.85, 0.35, label,
             size=10, color=GREY_DARK, align='center')
        text(s, x + 0.15, 2.4, 3.85, 1.2, big,
             size=42, bold=True, color=color, align='center')
        text(s, x + 0.15, 4.0, 3.85, 2.5, '\n'.join(items),
             size=10, color=BLACK, font='Consolas')
        x += 4.21
    footer(s, 15)


def slide_16_conclusion(prs):
    s = add_slide(prs)
    title_bar(s, "Conclusion & Future Work",
              "Compresses compliance review from days into minutes without trading speed for trust")

    # LEFT — Delivered
    text(s, 0.4, 1.25, 6.2, 0.4, "WHAT WAS DELIVERED",
         size=11, bold=True, color=NAVY)
    rect(s, 0.4, 1.7, 6.2, 5.3, GREY_LIGHT)
    delivered = [
        "✓  End-to-end AI compliance platform",
        "✓  Three jurisdictions (BH · IN · KW)",
        "✓  Six core analyst-facing features",
        "✓  Verbatim citation grounding always",
        "✓  Seven-tier defence-in-depth shell",
        "✓  Append-only audit log (28 events)",
        "✓  SHA-256 export integrity hash",
        "✓  Evaluated at three eval layers",
        "✓  On-premises · zero data egress",
    ]
    y = 1.95
    for d in delivered:
        text(s, 0.6, y, 5.9, 0.4, d, size=13, color=BLACK)
        y += 0.55

    # RIGHT — Future
    text(s, 6.8, 1.25, 6.2, 0.4, "FUTURE WORK",
         size=11, bold=True, color=NAVY)
    rect(s, 6.8, 1.7, 6.2, 5.3, GREY_LIGHT)
    future = [
        ("◆", "Scale to more jurisdictions", "UAE, Saudi Arabia, EU GDPR"),
        ("◆", "Real-time regulatory change feeds", "Auto-update on amendments"),
        ("◆", "Adjacent regulated domains", "AML, cyber risk, op resilience"),
        ("◆", "Adversarial AI red-teaming", "Continuous safety testing"),
        ("◆", "Reviewer feedback → AI loop", "Continuous learning improvement"),
    ]
    y = 1.95
    for icon, name, desc in future:
        text(s, 7.0, y, 0.3, 0.5, icon,
             size=13, bold=True, color=AMBER)
        text(s, 7.4, y, 5.5, 0.35, name,
             size=12, bold=True, color=BLACK)
        text(s, 7.4, y + 0.35, 5.5, 0.4, desc,
             size=10, color=GREY_DARK)
        y += 1.0
    footer(s, 16)


def slide_17_challenges(prs):
    s = add_slide(prs)
    title_bar(s, "Challenges Faced & How Solved",
              "Six challenges, each paired with the engineering response")

    rect(s, 0.4, 1.25, 12.5, 0.42, NAVY)
    text(s, 0.5, 1.27, 5.7, 0.42, "CHALLENGE",
         size=11, bold=True, color=WHITE, anchor='middle')
    text(s, 6.4, 1.27, 6.5, 0.42, "HOW SOLVED",
         size=11, bold=True, color=WHITE, anchor='middle')

    rows = [
        ("AI hallucination",
         "Three gates: verbatim citation verifier + DeBERTa NLI + SafeFallback"),
        ("Cross-jurisdictional terminology drift",
         "9-term citation-audited dictionary; query-time synonym expansion"),
        ("Prompt injection in regulatory PDFs",
         "Two-tier scanner (regex + LLM judge); fail-closed quarantine"),
        ("On-prem deployment, no GPU",
         "CPU-friendly model picks (BGE, MiniLM) — beat larger models on our corpus"),
        ("Audit-defensibility for regulators",
         "7-tier shell + append-only AuditLog + SHA-256 export hash"),
        ("NDA + thesis timeline in parallel",
         "Architecture-first documentation, anonymised artefacts, diagrams for viva"),
    ]
    y = 1.7
    for i, (challenge, solution) in enumerate(rows):
        if i % 2 == 0:
            rect(s, 0.4, y, 12.5, 0.78, GREY_LIGHT)
        text(s, 0.5, y, 5.7, 0.78, challenge,
             size=11, bold=True, color=BLACK, anchor='middle')
        text(s, 6.4, y, 6.5, 0.78, solution,
             size=10, color=BLACK, anchor='middle')
        y += 0.78

    rect(s, 0.4, 6.85, 12.5, 0.55, GREEN)
    text(s, 0.4, 6.85, 12.5, 0.55,
         "Thank you. Questions?",
         size=16, bold=True, color=WHITE, align='center', anchor='middle')
    footer(s, 17)


# ════════════════════════════════════════════════════════════════════════════
# BACKUP SLIDES (hidden, jump-to during Q&A)
# ════════════════════════════════════════════════════════════════════════════

def backup_intro(prs):
    s = add_slide(prs)
    rect(s, 0, 0, 13.33, 7.5, NAVY)
    text(s, 1, 2.5, 11, 0.6,
         "B A C K U P   S L I D E S",
         size=18, color=LIGHT_BLUE, bold=True, align='center')
    text(s, 1, 3.2, 11, 1.2,
         "Algorithm Deep Dives",
         size=40, bold=True, color=WHITE, align='center')
    text(s, 1, 4.5, 11, 0.5,
         "For Q&A — pseudocode + diagrams ready to jump to",
         size=14, color=GREY_LIGHT, align='center')


def backup_injection_scanner(prs):
    s = add_slide(prs)
    title_bar(s, "BACKUP — Two-Tier Injection Scanner",
              "Fast regex + LLM judge with fail-closed quarantine")
    rect(s, 0.4, 1.2, 12.5, 5.7, CODE_BG)

    code = """scan_chunk(content):

    # Tier A — regex rules (every chunk, ~97% stop here)
    for rule in [INST_OVERRIDE, ROLE_HIJACK, FORCED_VERDICT,
                 SAFETY_BYPASS, DEV_MODE_TRIGGER, PROMPT_LEAK,
                 FAKE_DELIMITER, BASE64_BLOB, SUSPICIOUS_URL]:
        if rule.pattern.search(content):
            return FLAGGED(tier=A, rule=rule)

    # Heuristic: only run Tier B on borderline chunks
    if not is_tier_b_candidate(content):
        return SAFE

    # Tier B — primary LLM judge (OpenRouter Claude Haiku 4.5)
    verdict = openrouter_judge(content)     # spotlight tagged
    if verdict == ATTACK:  return FLAGGED(tier=B)
    if verdict == SAFE:    return SAFE

    # Primary unreachable → fallback to local Ollama
    verdict = ollama_judge(content)
    if verdict == ATTACK:  return FLAGGED(tier=B)
    if verdict == SAFE:    return SAFE

    # BOTH judges unreachable → FAIL CLOSED
    return FLAGGED(tier=B, rule=JUDGE_UNAVAILABLE,
                   severity='medium')        # quarantine for admin review"""
    text(s, 0.6, 1.4, 12.1, 5.5, code,
         size=11, color=CODE_TEXT, font='Consolas')


def backup_hybrid_rrf(prs):
    s = add_slide(prs)
    title_bar(s, "BACKUP — Hybrid Retrieval + Reciprocal Rank Fusion",
              "BM25 + Vector merged with RRF, then cross-encoder rerank")
    rect(s, 0.4, 1.2, 12.5, 5.7, CODE_BG)

    code = """hybrid_search(query, top_k=5, jurisdiction=None, doc_titles=None):

    # 1. Cross-jurisdictional synonym expansion
    expanded = term_dictionary.expand(query)

    # 2. Parallel retrieval — BOTH apply filter pushdown
    vec = chroma.search(
        embedding = bge_small.encode(expanded, prefix='QUERY:'),
        filter    = {jurisdiction, doc_titles, topic},   # WHERE clause
        top_k     = 20,
    )
    bm25 = sqlite_fts5.search(
        query  = or_fuse_tokens(expanded),
        filter = {jurisdiction, doc_titles, topic},      # WHERE clause
        top_k  = 20,
    )

    # 3. Reciprocal Rank Fusion (k=60)
    fused = defaultdict(float)
    for rank, doc in enumerate(vec):   fused[doc.id] += 1 / (60 + rank)
    for rank, doc in enumerate(bm25):  fused[doc.id] += 1 / (60 + rank)
    candidates = top_20(fused)

    # 4. Cross-encoder rerank against ORIGINAL query (not expanded)
    reranked = ms_marco_MiniLM.rerank(query, candidates)
    return reranked[:top_k]"""
    text(s, 0.6, 1.4, 12.1, 5.5, code,
         size=11, color=CODE_TEXT, font='Consolas')


def backup_policy_auto_routing(prs):
    s = add_slide(prs)
    title_bar(s, "BACKUP — Policy-Driven Auto-Routing",
              "Methodologically correct mapping — the policy decides what to map against")
    rect(s, 0.4, 1.2, 12.5, 5.7, CODE_BG)

    code = """map_policy_coverage_auto(policy_docs, jurisdiction):

    # 1. What topics does the POLICY actually cover?
    policy_topics = topics_for_docs(policy_docs)

    # 2. Backfill classifier on-demand if not tagged
    if not policy_topics:
        classify_policy_chunks_on_demand(policy_docs)
        policy_topics = topics_for_docs(policy_docs)

    # 3. What does the REGULATION cover?
    reg_topics = topics_for_jurisdiction(jurisdiction)

    # 4. Intersect — only map topics in BOTH
    eligible = policy_topics ∩ reg_topics
    skipped  = policy_topics - reg_topics
              # → audit note: 'policy covers X but reg doesn't address X'

    # 5. Per-topic mapping passes with filter pushdown
    items = []
    for topic in eligible:
        sub = map_policy_coverage(
            query        = topic.label,
            jurisdiction = jurisdiction,
            topic        = topic,                  # pushdown filter
            doc_titles_policy = policy_docs,
        )
        items.extend(sub.items)

    return PolicyMappingReport(items, summary, skipped_topics=skipped)"""
    text(s, 0.6, 1.4, 12.1, 5.5, code,
         size=10.5, color=CODE_TEXT, font='Consolas')


def backup_audit_hash(prs):
    s = add_slide(prs)
    title_bar(s, "BACKUP — Audit Log + SHA-256 Tamper Evidence",
              "Append-only by convention · 16-char hash in PDF footer")
    rect(s, 0.4, 1.2, 12.5, 5.7, CODE_BG)

    code = """# Every security-relevant action — best-effort, never raises

log_event(user, action, request, target_type, target_id, description, metadata):
    try:
        AuditLog.create(
            event_type        = action,                          # indexed
            user              = user if authenticated else NULL,
            user_role_at_time = user.profile.role,               # SNAPSHOT
            ip_address        = extract_ip(request),             # X-Forwarded-For
            timestamp         = NOW,                             # indexed
            description       = description,
            related_object_type = target_type,
            related_object_id   = target_id,
            change_detail     = metadata,                        # JSON
        )
    except Exception: log.warning(...)    # never blocks business flow


# On export — SHA-256 over identity + decision metadata

audit_hash(run):
    payload = '|'.join([
        run.class_name,                # 'ComparisonRun'
        str(run.pk),                   # '107'
        run.status,                    # 'complete'
        str(run.completed_at),
        str(run.submitted_for_review_at),
        str(run.created_by_id),
    ])
    return SHA256(payload.encode()).hexdigest()[:16]"""
    text(s, 0.6, 1.4, 12.1, 5.5, code,
         size=10.5, color=CODE_TEXT, font='Consolas')


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    print('Copying template (for color scheme + layouts)...')
    shutil.copy(str(TEMPLATE), str(OUTPUT))

    print('Loading...')
    prs = Presentation(str(OUTPUT))
    print(f'  Original slide count: {len(prs.slides)}')

    print('Stripping all existing slides...')
    strip_slides(prs)
    print(f'  After strip: {len(prs.slides)} slides')

    print('Building 17 main slides...')
    main_builders = [
        slide_01_title,      slide_02_problem,    slide_03_aim_features,
        slide_04_client_fit, slide_05_tech_stack, slide_06_architecture,
        slide_07_security,   slide_08_journey,    slide_09_admin,
        slide_10_comparison, slide_11_mapping,    slide_12_reviewer,
        slide_13_audit,      slide_14_database,   slide_15_evaluation,
        slide_16_conclusion, slide_17_challenges,
    ]
    for i, fn in enumerate(main_builders, 1):
        print(f'  S{i:2d}  {fn.__name__}')
        fn(prs)

    print('Building 5 backup slides...')
    backup_builders = [
        backup_intro, backup_injection_scanner, backup_hybrid_rrf,
        backup_policy_auto_routing, backup_audit_hash,
    ]
    for fn in backup_builders:
        print(f'  BACKUP  {fn.__name__}')
        fn(prs)

    print(f'Saving {OUTPUT}...')
    prs.save(str(OUTPUT))
    print(f'DONE. Final slide count: {len(prs.slides)}')


if __name__ == '__main__':
    main()
