"""Generate a sample backup-folder screenshot as PNG.

Output: diagrams/Figure_A5_38_BackupFolder.png

Mocks a Windows File Explorer window showing the three data store
snapshots side by side: db.sqlite3, chroma_data/, and media/.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


NAVY = '#002583'
TEXT = '#1F2937'
MUTED = '#6B7280'
BORDER = '#D1D5DB'
ROW_HOVER = '#F3F4F6'
HEADER_BG = '#F9FAFB'
FOLDER_YELLOW = '#FCD34D'
FOLDER_BORDER = '#D97706'
FILE_BLUE = '#60A5FA'
FILE_BORDER = '#2563EB'


def folder_icon(ax, x, y, size=2.4):
    # Folder back tab
    tab = mpatches.FancyBboxPatch(
        (x, y + size * 0.55), size * 0.55, size * 0.25,
        boxstyle='round,pad=0.05',
        linewidth=0.6, edgecolor=FOLDER_BORDER, facecolor=FOLDER_YELLOW,
    )
    ax.add_patch(tab)
    # Folder body
    body = mpatches.FancyBboxPatch(
        (x, y + size * 0.05), size, size * 0.65,
        boxstyle='round,pad=0.05',
        linewidth=0.7, edgecolor=FOLDER_BORDER, facecolor=FOLDER_YELLOW,
    )
    ax.add_patch(body)


def file_icon(ax, x, y, size=2.4):
    # File body
    body = mpatches.FancyBboxPatch(
        (x + size * 0.1, y), size * 0.8, size,
        boxstyle='round,pad=0.05',
        linewidth=0.7, edgecolor=FILE_BORDER, facecolor='white',
    )
    ax.add_patch(body)
    # Folded corner
    corner = mpatches.Polygon(
        [(x + size * 0.65, y + size),
         (x + size * 0.9, y + size),
         (x + size * 0.9, y + size * 0.75)],
        closed=True, linewidth=0.6,
        edgecolor=FILE_BORDER, facecolor='#DBEAFE',
    )
    ax.add_patch(corner)
    # File-format label
    ax.text(x + size * 0.5, y + size * 0.35, 'DB',
            ha='center', va='center', fontsize=7,
            fontweight='bold', color=FILE_BORDER)


def main():
    out_dir = Path(__file__).resolve().parents[2] / 'diagrams'
    out_dir.mkdir(exist_ok=True)

    fig, ax = plt.subplots(figsize=(13, 7), dpi=180)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)
    ax.set_aspect('equal')
    ax.axis('off')

    # Window frame
    window = mpatches.FancyBboxPatch(
        (1, 1), 98, 58, boxstyle='round,pad=0.4',
        linewidth=1.2, edgecolor=BORDER, facecolor='white',
    )
    ax.add_patch(window)

    # Title bar
    titlebar = mpatches.Rectangle((1, 53), 98, 6, linewidth=0,
                                   facecolor=HEADER_BG)
    ax.add_patch(titlebar)
    ax.text(4, 56, 'cjpca_backup_2026_05_16',
            fontsize=10, fontweight='bold', color=TEXT, va='center')
    # Window controls
    for i, ch in enumerate(['—', '□', '✕']):
        ax.text(91 + i * 2.5, 56, ch, fontsize=9, color=MUTED, va='center')

    # Address bar
    address = mpatches.FancyBboxPatch(
        (3, 47), 85, 4, boxstyle='round,pad=0.2',
        linewidth=0.5, edgecolor=BORDER, facecolor='white',
    )
    ax.add_patch(address)
    ax.text(5, 49, ('D:\\Cross-Jurisdictional Privacy Compliance Analyzer\\'
                    'cjpca_backup_2026_05_16'),
            fontsize=8, color=TEXT, va='center')

    # Search box
    search = mpatches.FancyBboxPatch(
        (90, 47), 7, 4, boxstyle='round,pad=0.2',
        linewidth=0.5, edgecolor=BORDER, facecolor='white',
    )
    ax.add_patch(search)
    ax.text(91, 49, 'Search', fontsize=7, color=MUTED, va='center',
            style='italic')

    # Column headers
    headers_y = 42
    hr = mpatches.Rectangle((3, headers_y - 1), 94, 3.5, linewidth=0,
                             facecolor=HEADER_BG)
    ax.add_patch(hr)
    for x, label in [(5, 'Name'), (45, 'Date modified'),
                     (65, 'Type'), (82, 'Size')]:
        ax.text(x, headers_y + 0.7, label, fontsize=8,
                fontweight='bold', color=TEXT, va='center')

    # Row 1 — chroma_data/
    row1_y = 36
    folder_icon(ax, 5, row1_y, size=2.4)
    ax.text(9, row1_y + 1.2, 'chroma_data',
            fontsize=10, fontweight='bold', color=TEXT, va='center')
    ax.text(45, row1_y + 1.2, '16/05/2026  18:02',
            fontsize=9, color=TEXT, va='center')
    ax.text(65, row1_y + 1.2, 'File folder',
            fontsize=9, color=TEXT, va='center')
    ax.text(82, row1_y + 1.2, '482 MB',
            fontsize=9, color=TEXT, va='center')

    # Row 2 — media/
    row2_y = 30
    folder_icon(ax, 5, row2_y, size=2.4)
    ax.text(9, row2_y + 1.2, 'media',
            fontsize=10, fontweight='bold', color=TEXT, va='center')
    ax.text(45, row2_y + 1.2, '16/05/2026  18:02',
            fontsize=9, color=TEXT, va='center')
    ax.text(65, row2_y + 1.2, 'File folder',
            fontsize=9, color=TEXT, va='center')
    ax.text(82, row2_y + 1.2, '127 MB',
            fontsize=9, color=TEXT, va='center')

    # Row 3 — db.sqlite3
    row3_y = 24
    file_icon(ax, 5, row3_y, size=2.4)
    ax.text(9, row3_y + 1.2, 'db.sqlite3',
            fontsize=10, fontweight='bold', color=TEXT, va='center')
    ax.text(45, row3_y + 1.2, '16/05/2026  18:02',
            fontsize=9, color=TEXT, va='center')
    ax.text(65, row3_y + 1.2, 'SQLite database',
            fontsize=9, color=TEXT, va='center')
    ax.text(82, row3_y + 1.2, '34.2 MB',
            fontsize=9, color=TEXT, va='center')

    # Row 4 — env file
    row4_y = 18
    file_icon(ax, 5, row4_y, size=2.4)
    ax.text(9, row4_y + 1.2, '.env',
            fontsize=10, fontweight='bold', color=TEXT, va='center')
    ax.text(45, row4_y + 1.2, '16/05/2026  18:02',
            fontsize=9, color=TEXT, va='center')
    ax.text(65, row4_y + 1.2, 'ENV file',
            fontsize=9, color=TEXT, va='center')
    ax.text(82, row4_y + 1.2, '2 KB',
            fontsize=9, color=TEXT, va='center')

    # Status bar
    statusbar = mpatches.Rectangle((1, 1), 98, 4, linewidth=0,
                                    facecolor=HEADER_BG)
    ax.add_patch(statusbar)
    ax.text(4, 3, '4 items',
            fontsize=9, color=MUTED, va='center')
    ax.text(96, 3, 'Backup complete',
            fontsize=9, color='#15803D', va='center', ha='right',
            fontweight='bold')

    out = out_dir / 'Figure_A5_38_BackupFolder.png'
    fig.savefig(out, bbox_inches='tight', facecolor='#E5E7EB',
                edgecolor='none')
    plt.close(fig)
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
