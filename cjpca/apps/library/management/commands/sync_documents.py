"""
Management command: sync_documents
Reads data/metadata.csv and creates Document records for every file that
exists on disk but is not yet in the Django library.

Usage:
    python manage.py sync_documents
    python manage.py sync_documents --dry-run
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.library.models import Document

# Map metadata.csv Jurisdiction column → Document.jurisdiction constant
JURISDICTION_MAP = {
    'bahrain': Document.BAHRAIN,
    'india':   Document.INDIA,
    'kuwait':  Document.KUWAIT,
    'bbk':     Document.BBK,
    'eu':      Document.EU,
    'saudi':   Document.SAUDI,
    'uae':     Document.UAE,
}

# Document types that belong to internal policies (BBK)
POLICY_TYPES = {
    'internal procedure',
    'internal policy',
    'internal sop',
    'privacy statement',
    'internal guideline',
}

# Where files live on disk (relative to project root = one level up from cjpca/)
PROJECT_ROOT = Path(__file__).resolve().parents[5]
REGULATION_DIRS = {
    'bahrain': PROJECT_ROOT / 'data' / 'regulations' / 'bahrain',
    'india':   PROJECT_ROOT / 'data' / 'regulations' / 'india',
    'kuwait':  PROJECT_ROOT / 'data' / 'regulations' / 'kuwait',
}
POLICIES_DIR = PROJECT_ROOT / 'data' / 'internal_policies'
METADATA_CSV = PROJECT_ROOT / 'data' / 'metadata.csv'


def _find_file(doc_title: str, jurisdiction: str) -> Path | None:
    """Return path to the file on disk, or None if not found."""
    jur_lower = jurisdiction.lower()

    # Try regulation directories
    if jur_lower in REGULATION_DIRS:
        folder = REGULATION_DIRS[jur_lower]
        for ext in ('.pdf', '.docx', '.txt'):
            candidate = folder / f'{doc_title}{ext}'
            if candidate.exists():
                return candidate
        # Also check extra/ subfolder
        for ext in ('.pdf', '.docx', '.txt'):
            candidate = folder / 'extra' / f'{doc_title}{ext}'
            if candidate.exists():
                return candidate

    # Try internal policies dir
    for ext in ('.pdf', '.docx', '.txt'):
        candidate = POLICIES_DIR / f'{doc_title}{ext}'
        if candidate.exists():
            return candidate

    return None


class Command(BaseCommand):
    help = 'Sync data/metadata.csv into the Django Document library.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be created without writing to the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        created = skipped = missing = 0

        with open(METADATA_CSV, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                jur_raw   = row.get('Jurisdiction', '').strip().lower()
                name      = row.get('Regulation Name + Version', '').strip()
                doc_title = row.get('Document Title', '').strip()
                doc_type_raw = row.get('Document Type', '').strip().lower()
                scope     = row.get('Scope Summary', '').strip()

                jurisdiction = JURISDICTION_MAP.get(jur_raw, Document.OTHER)
                doc_type = (
                    Document.POLICY
                    if doc_type_raw in POLICY_TYPES
                    else Document.REGULATION
                )

                # Check file exists on disk
                file_path = _find_file(doc_title, jur_raw)
                if file_path is None:
                    self.stdout.write(
                        self.style.WARNING(f'  MISSING file: {doc_title}')
                    )
                    missing += 1
                    continue

                # Skip if already in DB (match on name + jurisdiction)
                if Document.objects.filter(name=name, jurisdiction=jurisdiction).exists():
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(f'  [dry-run] Would create: {name} ({jurisdiction})')
                    created += 1
                    continue

                Document.objects.create(
                    name=name,
                    full_name=scope,
                    doc_type=doc_type,
                    jurisdiction=jurisdiction,
                    status=Document.INDEXED,
                    chunk_count=0,   # populated later when backend reports back
                    token_count=0,
                    # file left blank — document lives in data/, not media/
                )
                created += 1
                self.stdout.write(f'  Created: {name}')

        label = 'Would create' if dry_run else 'Created'
        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {label}: {created}  |  Already in DB: {skipped}  |  File missing: {missing}'
        ))
