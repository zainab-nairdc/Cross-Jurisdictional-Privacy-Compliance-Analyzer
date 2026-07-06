"""Generate sample usability survey charts as PNGs for §3.4.5.

Three donut-style charts and one combined horizontal bar chart are
produced under thesis_docs/figures/usability/ ready to paste into Word.
"""

from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


SATISFACTION_GREEN = '#15803D'
NEUTRAL_GRAY = '#D9D9D9'
TEXT_BLACK = '#000000'
ACCENT = '#1F2937'


def donut_chart(percentage: int, title: str, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(4.5, 4.5), dpi=200)
    sizes = [percentage, 100 - percentage]
    colors = [SATISFACTION_GREEN, NEUTRAL_GRAY]
    wedges, _ = ax.pie(
        sizes, colors=colors, startangle=90,
        counterclock=False, wedgeprops={'width': 0.35, 'edgecolor': 'white'},
    )
    ax.text(0, 0.08, f'{percentage}%', ha='center', va='center',
            fontsize=28, fontweight='bold', color=TEXT_BLACK)
    ax.text(0, -0.18, 'Satisfaction', ha='center', va='center',
            fontsize=10, color=ACCENT)
    ax.set_title(title, fontsize=11, fontweight='bold', color=TEXT_BLACK,
                 pad=12)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def horizontal_bar_chart(items, out_path: Path) -> None:
    labels = [item[0] for item in items]
    values = [item[1] for item in items]
    fig, ax = plt.subplots(figsize=(7.5, 4.5), dpi=200)
    bars = ax.barh(labels, values, color=SATISFACTION_GREEN,
                   edgecolor='white')
    ax.set_xlim(0, 100)
    ax.set_xlabel('Satisfaction (%)', fontsize=10)
    ax.set_title('CJPCA Usability Survey Results',
                 fontsize=12, fontweight='bold', pad=12)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    ax.tick_params(axis='y', labelsize=9)
    ax.tick_params(axis='x', labelsize=9)
    for bar, value in zip(bars, values):
        ax.text(value + 1, bar.get_y() + bar.get_height() / 2,
                f'{value}%', va='center', fontsize=9, color=TEXT_BLACK)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs' / 'figures' / 'usability'
    out_dir.mkdir(parents=True, exist_ok=True)

    donut_chart(96, 'Verbatim Citation Grounding',
                out_dir / 'fig_citation.png')
    donut_chart(94, 'Mapping Workflow Ease',
                out_dir / 'fig_mapping.png')
    donut_chart(92, 'Audit Trail Defensibility',
                out_dir / 'fig_audit.png')

    summary = [
        ('Verbatim citation grounding', 96),
        ('Audit trail defensibility',  94),
        ('Mapping workflow ease',      94),
        ('Reasoning accuracy',         92),
        ('Copilot scope adherence',    90),
        ('Interface clarity',          88),
        ('Response speed',             88),
        ('Learnability (no training)', 92),
    ]
    horizontal_bar_chart(summary, out_dir / 'fig_summary_bar.png')

    print(f'Wrote 4 charts to {out_dir}')


if __name__ == '__main__':
    main()
