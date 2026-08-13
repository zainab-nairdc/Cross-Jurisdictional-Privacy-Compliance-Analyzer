"""Compute the missing content hashes that currency detection depends on.

    python manage.py backfill_content_hashes            # dry run
    python manage.py backfill_content_hashes --apply

`Document.content_hash` is written in exactly one place — the guided upload
wizard's finalize step. Every document that arrived by any other route (the
full_ingest command, seeding scripts, uploads predating the field) has none,
which is most of the corpus. Currency detection compares stored hashes, and
two EMPTY hashes are not evidence of sameness, so an unhashed document makes
its run unverifiable.

WHAT A BACKFILLED HASH DOES AND DOES NOT PROVE

  It proves: from now on, a change to this file's bytes is detectable.
  It does NOT prove: what the file contained when an earlier comparison ran.

That distinction is the whole point. A hash computed today cannot retroactively
establish what a historical run was based on, so backfilling does NOT make
existing runs verifiable — those keep an empty hash in their own snapshot and
stay `unknown`. This command makes FUTURE runs verifiable.

Non-destructive: writes `content_hash` only where it is currently empty and a
readable file exists. Never overwrites an existing hash, and never touches
versions, supersession, lifecycle, or any comparison run.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Compute Document.content_hash where it is missing and the file is '
            'readable (dry run by default).')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='write the hashes (default is a dry run)')
        parser.add_argument('--limit', type=int, default=None,
                            help='process at most N documents')

    def handle(self, *args, **opts):
        from apps.library.models import Document

        w = self.stdout.write
        apply_changes = opts['apply']

        qs = Document.objects.all().order_by('pk')
        total = qs.count()
        # Only documents whose hash is empty are candidates. An existing hash is
        # never recomputed: overwriting it would change what every snapshot
        # taken since is compared against.
        candidates = list(qs.filter(content_hash=''))
        if opts['limit']:
            candidates = candidates[:opts['limit']]

        w(self.style.MIGRATE_HEADING(
            f'\nDocuments: {total} · already hashed: {total - qs.filter(content_hash="").count()} '
            f'· missing a hash: {len(candidates)}'
            + ('' if apply_changes else '   [DRY RUN]')))

        hashed, skipped = [], []
        for doc in candidates:
            if not doc.file or not doc.file.name:
                skipped.append((doc, 'no file attached'))
                continue
            try:
                digest = doc.compute_content_hash()
            except Exception as exc:
                skipped.append((doc, f'hashing failed: {type(exc).__name__}'))
                continue
            if not digest:
                # compute_content_hash returns '' for a missing/unreadable file.
                skipped.append((doc, 'file recorded but not readable on disk'))
                continue
            hashed.append((doc, digest))
            if apply_changes:
                doc.content_hash = digest
                doc.save(update_fields=['content_hash'])

        w('')
        if hashed:
            w(self.style.MIGRATE_HEADING(
                f'{"Hashed" if apply_changes else "Would hash"} ({len(hashed)}):'))
            for doc, digest in hashed[:40]:
                w(f'  {doc.pk:<5} {doc.name[:46]:48s} {digest[:16]}')
            if len(hashed) > 40:
                w(f'  … and {len(hashed) - 40} more')

        if skipped:
            w('')
            w(self.style.WARNING(f'Cannot hash ({len(skipped)}):'))
            from collections import Counter
            for reason, n in Counter(r for _, r in skipped).most_common():
                w(f'  {n:>4}  {reason}')
            for doc, reason in skipped[:15]:
                w(f'      {doc.pk:<5} {doc.name[:46]:48s} {reason}')

        w('')
        w(self.style.WARNING(
            'A hash computed now proves nothing about what a PAST comparison '
            'used. Runs stamped before their document was hashed keep an empty '
            'hash in their own snapshot and stay "cannot verify currency" — '
            'that is correct, not a defect.'))

        if not apply_changes:
            w(self.style.SUCCESS('\nDry run only — nothing written. Re-run with --apply.'))
        else:
            remaining = Document.objects.filter(content_hash='').count()
            w(self.style.SUCCESS(
                f'\n[OK] {len(hashed)} hashed · {remaining} document(s) still '
                f'without a hash'))
