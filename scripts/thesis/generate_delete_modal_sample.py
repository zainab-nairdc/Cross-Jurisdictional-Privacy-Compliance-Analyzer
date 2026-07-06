"""Generate a sample delete confirmation dialog as PNG.

Output: diagrams/Figure_A5_36_DeleteConfirm.png

Mocks the standard delete confirmation modal so the manual can include
a sample image without requiring a real UI capture.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


NAVY = '#002583'
RED = '#B91C1C'
GRAY_LIGHT = '#F4F6FB'
GRAY_BORDER = '#7B8499'
TEXT = '#1F2937'
BACKDROP = '#1F29371F'  # semi-transparent grey backdrop


def main():
    out_dir = Path(__file__).resolve().parents[2] / 'diagrams'
    out_dir.mkdir(exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6), dpi=180)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)
    ax.set_aspect('equal')
    ax.axis('off')

    # Page backdrop (the dimmed page behind the modal)
    ax.add_patch(mpatches.Rectangle((0, 0), 100, 60,
                                     linewidth=0, facecolor='#E5E7EB'))

    # Page content hint (faint)
    ax.text(50, 56, 'Library  >  Bahrain PDPL 2018',
            ha='center', fontsize=8, color='#9CA3AF')

    # Modal card
    modal = mpatches.FancyBboxPatch(
        (22, 12), 56, 36, boxstyle='round,pad=0.6',
        linewidth=1.2, edgecolor=GRAY_BORDER, facecolor='white',
    )
    ax.add_patch(modal)

    # Warning icon (red circle with !)
    icon = mpatches.Circle((30, 39), 2.2, linewidth=0,
                           facecolor=RED, alpha=0.15)
    ax.add_patch(icon)
    ax.text(30, 39, '!', ha='center', va='center',
            fontsize=14, fontweight='bold', color=RED)

    # Title
    ax.text(36, 40, 'Delete this document?',
            fontsize=12, fontweight='bold', color=NAVY)

    # Body
    body = ('This will remove "Bahrain PDPL 2018" together with its '
            '47 chunks and their embeddings from both ChromaDB and '
            'SQLite FTS5. A document.delete row will be written to '
            'the AuditLog with role-at-time evidence. This action '
            'cannot be undone.')
    ax.text(26, 32, body, fontsize=8, color=TEXT, wrap=True,
            verticalalignment='top')

    # Cancel button (outlined)
    cancel = mpatches.FancyBboxPatch(
        (52, 15), 10, 4, boxstyle='round,pad=0.2',
        linewidth=1, edgecolor=GRAY_BORDER, facecolor='white',
    )
    ax.add_patch(cancel)
    ax.text(57, 17, 'Cancel', ha='center', va='center',
            fontsize=9, color=TEXT)

    # Delete button (red filled)
    delete = mpatches.FancyBboxPatch(
        (64, 15), 12, 4, boxstyle='round,pad=0.2',
        linewidth=0, facecolor=RED,
    )
    ax.add_patch(delete)
    ax.text(70, 17, 'Delete', ha='center', va='center',
            fontsize=9, color='white', fontweight='bold')

    out = out_dir / 'Figure_A5_36_DeleteConfirm.png'
    fig.savefig(out, bbox_inches='tight', facecolor='#E5E7EB')
    plt.close(fig)
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
