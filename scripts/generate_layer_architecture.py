"""Render the 5-layer architecture diagram for Slide 6 of the demo deck.

Output: demo/slide_assets/Figure_5LayerArchitecture.png
Run:    .venv/Scripts/python.exe scripts/generate_layer_architecture.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyArrowPatch


LAYERS_TOP_DOWN = [
    ("WEB",       "Django  ·  HTMX  ·  Channels",                    "#dbeafe", "#1e3a8a"),
    ("REASONING", "LangGraph  ·  Local Ollama  ·  Pydantic",         "#fed7aa", "#9a3412"),
    ("RETRIEVAL", "BM25  +  Vector  +  RRF  +  Cross-encoder",       "#fef3c7", "#854d0e"),
    ("INGESTION", "Docling  ·  Chunker  ·  Injection Scan  ·  Index", "#ddd6fe", "#5b21b6"),
    ("DATA",      "43 docs  ·  25-field metadata  ·  4 jurisdictions", "#d1fae5", "#065f46"),
]


def render(output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 7.5))

    band_h = 1.15
    gap = 0.18
    name_x = 0.4
    name_w = 2.4
    comp_x = name_x + name_w + 0.25

    layers_bottom_up = list(reversed(LAYERS_TOP_DOWN))

    for i, (name, comps, fill, accent) in enumerate(layers_bottom_up):
        y = i * (band_h + gap)

        band = patches.FancyBboxPatch(
            (0, y), 11, band_h,
            boxstyle="round,pad=0.04,rounding_size=0.18",
            facecolor=fill, edgecolor=accent, linewidth=1.6,
        )
        ax.add_patch(band)

        name_box = patches.FancyBboxPatch(
            (name_x, y + 0.18), name_w, band_h - 0.36,
            boxstyle="round,pad=0.02,rounding_size=0.10",
            facecolor=accent, edgecolor=accent, linewidth=0,
        )
        ax.add_patch(name_box)

        ax.text(
            name_x + name_w / 2, y + band_h / 2,
            name, fontsize=15, fontweight="bold",
            ha="center", va="center", color="white", family="DejaVu Sans",
        )

        ax.text(
            comp_x, y + band_h / 2,
            comps, fontsize=12,
            ha="left", va="center", color="#1f2937", family="DejaVu Sans",
        )

    for i in range(len(layers_bottom_up) - 1):
        y_start = i * (band_h + gap) + band_h + 0.005
        y_end = (i + 1) * (band_h + gap) - 0.005
        arrow = FancyArrowPatch(
            (5.6, y_start), (5.6, y_end),
            arrowstyle="-|>", mutation_scale=18,
            color="#374151", linewidth=1.6, shrinkA=0, shrinkB=0,
        )
        ax.add_patch(arrow)

    total_h = len(layers_bottom_up) * (band_h + gap) - gap

    ax.text(
        5.5, total_h + 0.55,
        "5-Layer Architecture  (bottom-up)",
        fontsize=17, fontweight="bold", ha="center", color="#111827",
    )
    ax.text(
        5.5, total_h + 0.20,
        "Each layer depends only on the one below",
        fontsize=11, ha="center", color="#6b7280", style="italic",
    )

    ax.text(
        11.1, -0.05,
        "data flows upward",
        fontsize=9, ha="right", va="top", color="#9ca3af", style="italic",
    )

    ax.set_xlim(-0.3, 11.3)
    ax.set_ylim(-0.4, total_h + 0.95)
    ax.set_aspect("auto")
    ax.axis("off")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    out = project_root / "demo" / "slide_assets" / "Figure_5LayerArchitecture.png"
    render(out)
