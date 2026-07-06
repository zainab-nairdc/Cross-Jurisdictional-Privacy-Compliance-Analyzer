"""Generate the System Design diagram for the graduation poster (v2).

Cleaner redesign:
  - Title outside the security shell (no overlap)
  - Security controls listed as a top banner inside the shell
  - Vertical flow with no crossing arrows
  - Storage feeds AI pipeline cleanly from below
  - Verification gates positioned as the AI-safety surface
  - Wider boxes, more breathing room
"""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch


NAVY      = '#002583'
NAVY_DARK = '#001A5F'
LIGHT     = '#E5E8EF'
MID       = '#6B7280'
WHITE     = '#FFFFFF'
AMBER     = '#FFF3D6'
AMBER_B   = '#B07A00'
GREEN     = '#D5EBDF'
GREEN_B   = '#15803D'
PURPLE    = '#E5DDF7'
PURPLE_B  = '#5E3FBE'
TEXT      = '#1F2937'


def box(ax, x, y, w, h, label, fill, border, *, fontsize=11, bold=True,
        sublabel=None, sub_fontsize=8):
    rect = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle='round,pad=0.4',
        linewidth=1.4, edgecolor=border, facecolor=fill,
    )
    ax.add_patch(rect)
    if sublabel:
        ax.text(x + w / 2, y + h * 0.65, label, ha='center', va='center',
                fontsize=fontsize, color=TEXT,
                fontweight='bold' if bold else 'normal')
        ax.text(x + w / 2, y + h * 0.28, sublabel, ha='center', va='center',
                fontsize=sub_fontsize, color=MID, style='italic')
    else:
        ax.text(x + w / 2, y + h / 2, label, ha='center', va='center',
                fontsize=fontsize, color=TEXT,
                fontweight='bold' if bold else 'normal')


def arrow(ax, x1, y1, x2, y2, color=NAVY, lw=1.6, style='->'):
    a = FancyArrowPatch((x1, y1), (x2, y2),
                        arrowstyle=style, color=color, lw=lw,
                        mutation_scale=16,
                        connectionstyle='arc3,rad=0')
    ax.add_patch(a)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs' / 'poster'
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(15, 11), dpi=200)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 90)
    ax.set_aspect('equal')
    ax.axis('off')

    # ── Title outside the shell ────────────────────────────────────────────
    ax.text(50, 86, 'CJPCA System Architecture',
            ha='center', va='center', fontsize=15, fontweight='bold',
            color=NAVY)

    # ── Defence-in-depth shell (dashed outer border) ───────────────────────
    shell = mpatches.FancyBboxPatch(
        (3, 3), 94, 78, boxstyle='round,pad=1.0',
        linewidth=2.5, edgecolor=NAVY, facecolor='none',
        linestyle=(0, (8, 4)),
    )
    ax.add_patch(shell)

    # Security banner (top of the shell, inside)
    sec_band = mpatches.Rectangle(
        (5, 75), 90, 4, linewidth=0, facecolor=NAVY, alpha=0.08,
    )
    ax.add_patch(sec_band)
    ax.text(50, 77.7,
            'D E F E N C E - I N - D E P T H   S E C U R I T Y   S H E L L',
            ha='center', va='center', fontsize=9.5, fontweight='bold',
            color=NAVY)
    ax.text(50, 75.7,
            'TLS 1.3   ·   GeoFence   ·   django-axes lockout   ·   '
            'TOTP MFA   ·   Role-Based Access   ·   CSP   ·   Append-only AuditLog',
            ha='center', va='center', fontsize=8.2, color=NAVY,
            style='italic')

    # ── Tier 1: Users (three columns) ──────────────────────────────────────
    box(ax,  8, 64, 24, 7, 'Analyst',
        LIGHT, NAVY,
        sublabel='Runs comparisons + mappings', sub_fontsize=8)
    box(ax, 38, 64, 24, 7, 'Reviewer',
        LIGHT, NAVY,
        sublabel='Approves / modifies / rejects', sub_fontsize=8)
    box(ax, 68, 64, 24, 7, 'Administrator',
        LIGHT, NAVY,
        sublabel='Users, quarantine, audit', sub_fontsize=8)

    # Arrows: users → web layer
    arrow(ax, 20, 64, 20, 60.5)
    arrow(ax, 50, 64, 50, 60.5)
    arrow(ax, 80, 64, 80, 60.5)

    # ── Tier 2: Web layer (full-width bar) ─────────────────────────────────
    web = mpatches.FancyBboxPatch(
        (8, 53), 84, 7, boxstyle='round,pad=0.4',
        linewidth=1.4, edgecolor=NAVY_DARK, facecolor=NAVY,
    )
    ax.add_patch(web)
    ax.text(50, 57.5, 'Web Layer',
            ha='center', va='center', fontsize=12, color='white',
            fontweight='bold')
    ax.text(50, 54.5,
            'Django (10 apps)   ·   HTMX   ·   Alpine.js   ·   Copilot dock',
            ha='center', va='center', fontsize=9, color='white',
            style='italic')

    # Arrows: web layer → AI pipeline (three down arrows)
    arrow(ax, 20, 53, 20, 49)
    arrow(ax, 50, 53, 50, 49)
    arrow(ax, 80, 53, 80, 49)

    # ── Tier 3: AI Pipeline (three horizontal stages) ─────────────────────
    box(ax,  6, 40, 25, 9, 'Ingestion',
        AMBER, AMBER_B,
        sublabel='Docling parse · chunking ·\ntwo-tier injection scan',
        sub_fontsize=8)
    box(ax, 37.5, 40, 25, 9, 'Hybrid Retrieval',
        AMBER, AMBER_B,
        sublabel='BM25 + Vector + RRF +\ncross-encoder rerank',
        sub_fontsize=8)
    box(ax, 69, 40, 25, 9, 'Reasoning Agent',
        AMBER, AMBER_B,
        sublabel='LangGraph state machine\nDraft → Verify → Correct',
        sub_fontsize=8)

    # Horizontal flow arrows between AI stages
    arrow(ax, 31, 44.5, 37.5, 44.5, color=AMBER_B, lw=2.2)
    arrow(ax, 62.5, 44.5, 69, 44.5, color=AMBER_B, lw=2.2)

    # ── Tier 4: Verification Gates (highlighted as AI-safety surface) ─────
    box(ax, 25, 27, 50, 8, 'Verification Gates',
        GREEN, GREEN_B,
        sublabel='Verbatim citation verifier   ·   NLI hallucination gate   ·   SafeFallback',
        sub_fontsize=9)

    # Reasoning agent → Verification (straight down)
    arrow(ax, 81.5, 40, 70, 35, color=GREEN_B, lw=2.0)
    # Verification → back up to web layer (verified output)
    arrow(ax, 30, 35, 30, 53, color=GREEN_B, lw=2.0, style='-|>')

    # ── Tier 5: Storage (three columns at bottom) ──────────────────────────
    box(ax,  8, 9, 24, 9, 'ChromaDB',
        PURPLE, PURPLE_B,
        sublabel='Vector index\n(HNSW, BGE-small)',
        sub_fontsize=8)
    box(ax, 38, 9, 24, 9, 'SQLite FTS5',
        PURPLE, PURPLE_B,
        sublabel='BM25 keyword index\nwith jurisdiction filter',
        sub_fontsize=8)
    box(ax, 68, 9, 24, 9, 'AuditLog',
        PURPLE, PURPLE_B,
        sublabel='Append-only · 28 actions\nSHA-256 export chain',
        sub_fontsize=8)

    # Storage feeds Hybrid Retrieval (Chroma + FTS5 both feed up)
    arrow(ax, 20, 18, 45, 40, color=PURPLE_B, lw=1.5)
    arrow(ax, 50, 18, 50, 40, color=PURPLE_B, lw=1.5)
    # AuditLog receives writes (from verification + web actions)
    arrow(ax, 50, 27, 80, 18, color=PURPLE_B, lw=1.5)

    # ── Legend ─────────────────────────────────────────────────────────────
    legend_y = 4.5
    items = [
        ('User', LIGHT, NAVY),
        ('Web', NAVY, NAVY_DARK),
        ('AI', AMBER, AMBER_B),
        ('Safety', GREEN, GREEN_B),
        ('Storage', PURPLE, PURPLE_B),
    ]
    x_start = 8
    for i, (label, fill, border) in enumerate(items):
        x = x_start + i * 17
        sq = mpatches.Rectangle((x, legend_y - 0.6), 2, 1.5,
                                 linewidth=1, edgecolor=border,
                                 facecolor=fill)
        ax.add_patch(sq)
        text_color = 'white' if fill == NAVY else TEXT
        ax.text(x + 3.5, legend_y + 0.15, label, ha='left', va='center',
                fontsize=9, color=TEXT)

    out = out_dir / 'Figure_PosterSystemDesign.png'
    fig.savefig(out, bbox_inches='tight', facecolor='white',
                edgecolor='none')
    plt.close(fig)
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
