"""Generate the AI Pipeline diagram for the graduation poster (v3).

Clean redesign:
  - Removed the "indexed chunks" cross-lane arrow (implicit, was confusing)
  - "top-5 chunks" arrow now originates from Cross-encoder rerank (not Query)
  - Quarantine sits inline with the injection-scan box, not floating
  - All connectors rectilinear, all labels horizontal
  - SafeFallback in the Reasoning lane, single clear path
"""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.path import Path as MplPath
from matplotlib.patches import FancyArrowPatch, PathPatch


NAVY      = '#002583'
LIGHT     = '#E5E8EF'
MID       = '#6B7280'
AMBER     = '#FFF3D6'
AMBER_B   = '#B07A00'
GREEN     = '#D5EBDF'
GREEN_B   = '#15803D'
RED       = '#FAD4D4'
RED_B     = '#B91C1C'
TEXT      = '#1F2937'


def box(ax, x, y, w, h, label, fill, border, *, fontsize=10, bold=True,
        sublabel=None, sub_fontsize=7.5):
    rect = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle='round,pad=0.35',
        linewidth=1.3, edgecolor=border, facecolor=fill,
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


def varrow(ax, x, y1, y2, *, color=NAVY, lw=1.5):
    a = FancyArrowPatch((x, y1), (x, y2), arrowstyle='-|>', color=color,
                        lw=lw, mutation_scale=14)
    ax.add_patch(a)


def harrow(ax, x1, x2, y, *, color=NAVY, lw=1.5):
    a = FancyArrowPatch((x1, y), (x2, y), arrowstyle='-|>', color=color,
                        lw=lw, mutation_scale=14)
    ax.add_patch(a)


def elbow_path(ax, points, *, color=NAVY, lw=1.5):
    """Draw a rectilinear path through a sequence of points, with arrowhead at end."""
    if len(points) < 2:
        return
    verts = list(points)
    codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(verts) - 1)
    path = MplPath(verts, codes)
    pp = PathPatch(path, facecolor='none', edgecolor=color, lw=lw)
    ax.add_patch(pp)
    # Tiny arrowhead drawn from second-to-last to last point
    x1, y1 = verts[-2]
    x2, y2 = verts[-1]
    head = FancyArrowPatch((x1, y1), (x2, y2),
                            arrowstyle='-|>', color=color, lw=lw,
                            mutation_scale=14)
    ax.add_patch(head)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs' / 'poster'
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(16, 10), dpi=200)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)
    ax.set_aspect('equal')
    ax.axis('off')

    # ── Title ──────────────────────────────────────────────────────────────
    ax.text(50, 57, 'CJPCA AI Pipeline',
            ha='center', va='center', fontsize=15, fontweight='bold',
            color=NAVY)
    ax.text(50, 54,
            'Document → Indexed evidence → Retrieved chunks → Verified output',
            ha='center', va='center', fontsize=10, color=MID,
            style='italic')

    # ── Lane background bands ─────────────────────────────────────────────
    for (x, label) in [
        (1,  'INGESTION'),
        (34, 'HYBRID RETRIEVAL'),
        (67, 'REASONING AGENT'),
    ]:
        bg = mpatches.Rectangle((x, 5), 32, 44, linewidth=0,
                                facecolor=AMBER_B, alpha=0.04)
        ax.add_patch(bg)
        ax.text(x + 16, 50.5, label, ha='center', va='center',
                fontsize=10, fontweight='bold', color=AMBER_B)

    # ── INGESTION lane (left) ─────────────────────────────────────────────
    ing_x = 4
    ing_w = 22
    box(ax, ing_x, 42, ing_w, 5, 'Document upload',
        LIGHT, NAVY, fontsize=10, sublabel='PDF / DOCX via Docling')
    box(ax, ing_x, 34, ing_w, 5, 'Chunking',
        LIGHT, NAVY, fontsize=10, sublabel='Section-aware + recursive')
    box(ax, ing_x, 26, ing_w, 5, 'Two-tier injection scan',
        LIGHT, NAVY, fontsize=10, sublabel='Tier-A regex + Tier-B judge')
    box(ax, ing_x, 18, ing_w, 5, 'Embed + index',
        LIGHT, NAVY, fontsize=10,
        sublabel='BGE-small → ChromaDB + SQLite FTS5')

    # Vertical ingestion arrows
    varrow(ax, ing_x + ing_w / 2, 42, 39)
    varrow(ax, ing_x + ing_w / 2, 34, 31)
    varrow(ax, ing_x + ing_w / 2, 26, 23)

    # Quarantine — full-width sibling box at bottom of the Ingestion lane
    qx, qy, qw, qh = ing_x, 9, ing_w, 5
    box(ax, qx, qy, qw, qh, 'Quarantine',
        RED, RED_B, fontsize=10, sublabel='admin review queue')
    elbow_path(ax,
               [(ing_x + ing_w - 4, 26),
                (ing_x + ing_w - 4, 14)],
               color=RED_B, lw=1.4)
    ax.text(ing_x + ing_w - 3, 19, 'flagged',
            ha='left', va='center', fontsize=7.5, color=RED_B,
            style='italic')

    # ── HYBRID RETRIEVAL lane (middle) ────────────────────────────────────
    box(ax, 40, 42, 20, 5, 'Query',
        AMBER, AMBER_B, fontsize=10,
        sublabel='analyst question + scope')
    box(ax, 35, 33, 13, 5, 'BM25',
        AMBER, AMBER_B, fontsize=9, sublabel='SQLite FTS5')
    box(ax, 52, 33, 13, 5, 'Vector',
        AMBER, AMBER_B, fontsize=9, sublabel='ChromaDB HNSW')
    box(ax, 40, 24, 20, 5, 'RRF fusion',
        AMBER, AMBER_B, fontsize=10, sublabel='reciprocal rank, k=60')
    box(ax, 40, 15, 20, 5, 'Cross-encoder rerank',
        AMBER, AMBER_B, fontsize=10, sublabel='ms-marco MiniLM → top-5')

    # Query → BM25 and Vector (rectilinear split)
    elbow_path(ax, [(50, 42), (50, 40), (41.5, 40), (41.5, 38)],
               color=AMBER_B, lw=1.5)
    elbow_path(ax, [(50, 42), (50, 40), (58.5, 40), (58.5, 38)],
               color=AMBER_B, lw=1.5)
    # BM25 + Vector → RRF fusion (converge)
    elbow_path(ax, [(41.5, 33), (41.5, 31), (50, 31), (50, 29)],
               color=AMBER_B, lw=1.5)
    elbow_path(ax, [(58.5, 33), (58.5, 31), (50, 31), (50, 29)],
               color=AMBER_B, lw=1.5)
    # RRF → Rerank
    varrow(ax, 50, 24, 20, color=AMBER_B)

    # ── REASONING AGENT lane (right) ──────────────────────────────────────
    rea_x = 70
    rea_w = 24
    box(ax, rea_x, 42, rea_w, 5, 'Draft',
        GREEN, GREEN_B, fontsize=10,
        sublabel='LLM generates structured output')
    box(ax, rea_x, 34, rea_w, 5, 'Verify',
        GREEN, GREEN_B, fontsize=10,
        sublabel='Citation verifier + NLI gate')
    box(ax, rea_x, 26, rea_w, 5, 'Correct',
        GREEN, GREEN_B, fontsize=10,
        sublabel='Bounded retry')
    box(ax, rea_x, 18, rea_w, 5, 'Finalise',
        GREEN, GREEN_B, fontsize=10,
        sublabel='Pydantic-validated output')
    box(ax, rea_x + 4, 9, 16, 5, 'SafeFallback',
        RED, RED_B, fontsize=9,
        sublabel='typed-empty result')

    # Reasoning flow: Draft → Verify
    varrow(ax, rea_x + rea_w / 2, 42, 39, color=GREEN_B)
    # Verify → Correct (fail path, left side)
    elbow_path(ax, [(rea_x + 2, 34), (rea_x + 2, 32), (rea_x + 2, 31)],
               color=GREEN_B, lw=1.5)
    ax.text(rea_x + 3.5, 32.5, 'fail',
            ha='left', va='center', fontsize=7.5, color=GREEN_B,
            style='italic')
    # Verify → Finalise (pass path, right side bypass)
    elbow_path(ax, [(rea_x + rea_w - 2, 34),
                    (rea_x + rea_w - 2, 23)],
               color=GREEN_B, lw=1.5)
    ax.text(rea_x + rea_w - 4, 28, 'pass',
            ha='right', va='center', fontsize=7.5, color=GREEN_B,
            style='italic')
    # Correct → Verify (retry loop, far left, with breathing room for label)
    elbow_path(ax, [(rea_x, 29), (rea_x - 2.5, 29),
                    (rea_x - 2.5, 37), (rea_x, 37)],
               color=GREEN_B, lw=1.4)
    ax.text(rea_x - 3.5, 33, 'retry',
            ha='right', va='center', fontsize=7.5, color=GREEN_B,
            style='italic')
    # Correct → SafeFallback (route around the LEFT of Finalise to avoid overlap)
    elbow_path(ax,
               [(rea_x, 28),         # left edge of Correct
                (rea_x - 4, 28),     # go left out of the column
                (rea_x - 4, 11.5),   # go down past Finalise
                (rea_x + 4, 11.5)],  # come back in to SafeFallback's left edge
               color=RED_B, lw=1.4)
    ax.text(rea_x - 4.5, 20, 'retries\nexhausted',
            ha='right', va='center', fontsize=7, color=RED_B,
            style='italic')

    # ── ONE cross-lane connector: rerank → Draft ──────────────────────────
    elbow_path(ax,
               [(60, 17.5),       # right side of rerank box
                (66, 17.5),       # go right
                (66, 44.5),       # go up
                (rea_x, 44.5)],   # arrive at Draft left side
               color=AMBER_B, lw=1.7)
    ax.text(63, 31, 'top-5\nchunks',
            ha='center', va='center', fontsize=8, color=AMBER_B,
            style='italic')

    out = out_dir / 'Figure_PosterAIPipeline.png'
    fig.savefig(out, bbox_inches='tight', facecolor='white',
                edgecolor='none')
    plt.close(fig)
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
