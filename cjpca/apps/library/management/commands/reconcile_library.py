"""
Management command: reconcile_library

Treats the BM25 index as the source of truth for "what the system can
actually retrieve from", and reconciles the Django library.Document table
against it. Three things happen:

1. CREATE Document rows for every doc_title indexed in BM25 that has no
   matching Document. Metadata is pulled from data/metadata.csv when the
   row exists there; otherwise sensible defaults are derived from the
   doc_title prefix (Jurisdiction_Name_Year_*).
2. SYNC `chunk_count` on every Document to match the BM25 reality. Drift
   accumulates because chunk_count is written once at upload time and
   never refreshed when re-ingestion runs out of band.
3. REPORT Documents whose `chunk_doc_title` (= file stem) has zero chunks
   in BM25 — those are "ghost" rows where the library shows a doc but the
   reasoning workflows physically can't see it. We flag these for manual
   review rather than auto-deleting, since they may indicate a partial
   re-ingestion.

Usage:
    python manage.py reconcile_library
    python manage.py reconcile_library --dry-run
"""
import csv
import shutil
import sqlite3
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.library.models import Document

# Project root = two levels above apps/library/management/commands/.../
PROJECT_ROOT = Path(__file__).resolve().parents[5]
DATA_DIR = PROJECT_ROOT / 'data'
METADATA_CSV = DATA_DIR / 'metadata.csv'
BM25_DB = PROJECT_ROOT / 'chroma_data' / 'bm25.db'
MEDIA_DOCS = PROJECT_ROOT / 'cjpca' / 'media' / 'documents'

JURISDICTION_MAP = {
    'bahrain': Document.BAHRAIN,
    'india':   Document.INDIA,
    'kuwait':  Document.KUWAIT,
    'bbk':     Document.BBK,
    'eu':      Document.EU,
    'saudi':   Document.SAUDI,
    'uae':     Document.UAE,
}

# Tokens in metadata.csv "Document Type" that mean internal policy.
POLICY_TYPE_TOKENS = ('policy', 'procedure', 'sop', 'privacy statement', 'guideline')

# Where source files might live (checked in order).
SOURCE_DIRS = [
    DATA_DIR / 'regulations' / 'bahrain',
    DATA_DIR / 'regulations' / 'india',
    DATA_DIR / 'regulations' / 'kuwait',
    DATA_DIR / 'regulations' / 'bahrain' / 'extra',
    DATA_DIR / 'regulations' / 'india' / 'extra',
    DATA_DIR / 'regulations' / 'kuwait' / 'extra',
    DATA_DIR / 'internal_policies',
]
SOURCE_EXTS = ('.pdf', '.docx', '.md', '.txt')


def _load_metadata_csv() -> dict[str, dict]:
    """doc_title -> metadata.csv row."""
    if not METADATA_CSV.exists():
        return {}
    out = {}
    with open(METADATA_CSV, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            title = row.get('Document Title', '').strip()
            if title:
                out[title] = row
    return out


def _bm25_doc_titles() -> dict[str, dict]:
    """doc_title -> {chunk_count, jurisdiction}. Empty dict if BM25 missing."""
    if not BM25_DB.exists():
        return {}
    conn = sqlite3.connect(str(BM25_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            'SELECT doc_title, jurisdiction, COUNT(*) AS n '
            'FROM bm25_index GROUP BY doc_title, jurisdiction'
        ).fetchall()
    finally:
        conn.close()
    out = {}
    for r in rows:
        title = r['doc_title'] or ''
        if not title:
            continue
        out[title] = {'chunk_count': r['n'], 'jurisdiction': (r['jurisdiction'] or '').lower()}
    return out


def _find_source_file(doc_title: str) -> Path | None:
    for d in SOURCE_DIRS:
        for ext in SOURCE_EXTS:
            cand = d / f'{doc_title}{ext}'
            if cand.exists():
                return cand
    return None


def _classify_doc_type(meta_row: dict | None) -> str:
    if not meta_row:
        return Document.REGULATION
    raw = (meta_row.get('Document Type') or '').strip().lower()
    if any(tok in raw for tok in POLICY_TYPE_TOKENS):
        return Document.POLICY
    return Document.REGULATION


def _resolve_jurisdiction(meta_row: dict | None, fallback_bm25_jur: str, doc_title: str) -> str:
    if meta_row:
        raw = (meta_row.get('Jurisdiction') or '').strip().lower()
        if raw in JURISDICTION_MAP:
            return JURISDICTION_MAP[raw]
    if fallback_bm25_jur in JURISDICTION_MAP:
        return JURISDICTION_MAP[fallback_bm25_jur]
    # last resort: guess from doc_title prefix
    prefix = doc_title.split('_', 1)[0].lower()
    return JURISDICTION_MAP.get(prefix, Document.OTHER)


def _display_name(meta_row: dict | None, doc_title: str) -> str:
    if meta_row:
        n = (meta_row.get('Regulation Name + Version') or '').strip()
        if n:
            return n
    return doc_title.replace('_', ' ').strip()


def _existing_by_chunk_doc_title() -> dict[str, Document]:
    """All Documents keyed by their chunk_doc_title (= file stem)."""
    out = {}
    for d in Document.objects.all():
        key = d.chunk_doc_title
        if key:
            out[key] = d
    return out


class Command(BaseCommand):
    help = 'Reconcile library.Document rows against the BM25 index.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing to the database.',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']

        metadata = _load_metadata_csv()
        indexed  = _bm25_doc_titles()
        existing = _existing_by_chunk_doc_title()

        if not indexed:
            self.stdout.write(self.style.ERROR(
                f'BM25 db not found or empty at {BM25_DB}. Aborting.'
            ))
            return

        created, synced, ghosts, missing_files = [], [], [], []

        # ── 1 + 2: walk every indexed doc_title ───────────────────────────────
        MEDIA_DOCS.mkdir(parents=True, exist_ok=True)
        for doc_title, info in sorted(indexed.items()):
            actual_chunks = info['chunk_count']

            doc = existing.get(doc_title)
            if doc is not None:
                # SYNC: chunk_count drift?
                if doc.chunk_count != actual_chunks:
                    synced.append((doc, doc.chunk_count, actual_chunks))
                    if not dry:
                        doc.chunk_count = actual_chunks
                        if doc.status != Document.INDEXED:
                            doc.status = Document.INDEXED
                        doc.save(update_fields=['chunk_count', 'status'])
                continue

            # CREATE: orphan in BM25 with no Document row
            meta_row     = metadata.get(doc_title)
            jurisdiction = _resolve_jurisdiction(meta_row, info['jurisdiction'], doc_title)
            doc_type     = _classify_doc_type(meta_row)
            display_name = _display_name(meta_row, doc_title)

            # Locate + stage the source file under media/documents/ so the
            # link in the library and the doc-viewer download work.
            src = _find_source_file(doc_title)
            if src is None:
                missing_files.append((doc_title, actual_chunks, jurisdiction))
                file_field = ''
            else:
                dest = MEDIA_DOCS / src.name
                if not dest.exists() and not dry:
                    shutil.copy2(src, dest)
                file_field = f'documents/{src.name}'

            extra = {}
            if meta_row:
                extra['issuing_authority'] = (meta_row.get('Issuing Authority') or '').strip()[:255]
                extra['source_url']        = (meta_row.get('Source URL') or '').strip()[:500]
                extra['version']           = (meta_row.get('version') or meta_row.get('Version') or '').strip()[:50]
                extra['notes']             = (meta_row.get('Scope Summary') or '').strip()
                extra['full_name']         = display_name[:500]
                # Effective date — best-effort ISO parse
                eff = (meta_row.get('Effective Date') or '').strip()
                if eff and len(eff) == 10 and eff[4] == '-' and eff[7] == '-':
                    extra['effective_date'] = eff

            created.append({
                'doc_title':    doc_title,
                'name':         display_name,
                'jurisdiction': jurisdiction,
                'doc_type':     doc_type,
                'chunk_count':  actual_chunks,
                'file':         file_field,
            })
            if not dry:
                Document.objects.create(
                    name         = display_name[:255],
                    doc_type     = doc_type,
                    jurisdiction = jurisdiction,
                    status       = Document.INDEXED,
                    chunk_count  = actual_chunks,
                    token_count  = 0,
                    file         = file_field,
                    **extra,
                )

        # ── 3: ghosts — Documents whose chunk_doc_title isn't in BM25 ────────
        for stem, doc in existing.items():
            if stem not in indexed:
                ghosts.append((doc, stem))

        self._report(dry, created, synced, ghosts, missing_files)

    def _report(self, dry, created, synced, ghosts, missing_files):
        prefix = '[dry-run] ' if dry else ''
        write  = self.stdout.write

        write(self.style.MIGRATE_HEADING(f'\n{prefix}CREATED ({len(created)} new Document rows)'))
        for c in created:
            file_note = c['file'] or '(no source file — created with blank file field)'
            write(f"  + {c['doc_title']}  [{c['jurisdiction']}/{c['doc_type']}]  chunks={c['chunk_count']}")
            write(f"       name: {c['name']}")
            write(f"       file: {file_note}")

        write(self.style.MIGRATE_HEADING(f'\n{prefix}SYNCED chunk_count ({len(synced)} rows fixed)'))
        for doc, old, new in synced:
            arrow = '↑' if new > old else '↓'
            write(f'  {arrow} #{doc.pk:3d} {doc.name[:60]:60s}  {old} → {new}')

        write(self.style.MIGRATE_HEADING(f'\nGHOST Documents ({len(ghosts)} rows with 0 BM25 chunks)'))
        write('  These Documents claim a file but the index has no matching chunks.')
        write('  Either the file was renamed, ingestion never completed, or the file')
        write('  was deleted from the index. Manual review recommended.')
        for doc, stem in ghosts:
            write(f'  ⚠ #{doc.pk:3d} {doc.name[:55]:55s}  stem={stem}  claims chunks={doc.chunk_count}')

        if missing_files:
            write(self.style.WARNING(
                f'\nORPHAN doc_titles with no source file ({len(missing_files)})'
            ))
            write('  Indexed in BM25 but no PDF/DOCX/MD on disk. Document row was')
            write('  created with a blank file field — file download will not work.')
            for title, n, jur in missing_files:
                write(f'  ! {title}  [{jur}]  chunks={n}')

        write(self.style.SUCCESS(
            f'\n{prefix}Done. created={len(created)} synced={len(synced)} '
            f'ghosts={len(ghosts)} missing_files={len(missing_files)}'
        ))
        if dry:
            write(self.style.NOTICE('Re-run without --dry-run to apply.'))
