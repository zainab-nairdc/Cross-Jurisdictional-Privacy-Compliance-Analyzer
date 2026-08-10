"""Mark a regulation version as superseded by a newer one.

Usage:
  python manage.py version_supersede <old> <new>
      <old> / <new> = a document pk, or part of its name.

Reports the approved analyses that referenced the old version and now need
re-review. The old version is kept (superseded, not deleted).
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Supersede one regulation version with a newer one; report affected approved analyses.'

    def add_arguments(self, parser):
        parser.add_argument('old', help='pk or name fragment of the version being superseded')
        parser.add_argument('new', help='pk or name fragment of the new in-force version')

    def handle(self, *args, **opts):
        from apps.library.models import Document
        w = self.stdout.write

        def resolve(token, label):
            token = token.strip()
            if token.isdigit():
                d = Document.objects.filter(pk=int(token)).first()
            else:
                matches = Document.objects.filter(name__icontains=token, doc_type=Document.REGULATION)
                if matches.count() > 1:
                    raise CommandError(f'"{token}" matches {matches.count()} documents — be more specific or use the pk:\n'
                                       + '\n'.join(f'  {m.pk}: {m.name}' for m in matches[:10]))
                d = matches.first()
            if not d:
                raise CommandError(f'No document found for {label} = "{token}".')
            return d

        old = resolve(opts['old'], 'old')
        new = resolve(opts['new'], 'new')
        if old.pk == new.pk:
            raise CommandError('old and new resolve to the same document.')

        affected = old.supersede_with(new)
        w(self.style.SUCCESS(f'\n✓ "{old.name}" is now superseded by "{new.name}".'))
        w(f'  old version status: {old.version_status}   new version status: {new.version_status}')
        n = affected.count() if affected is not None else 0
        if n:
            w(self.style.WARNING(f'\n⚠ {n} approved analysis/es referenced the old version — re-review recommended:'))
            for r in affected:
                w(f'   • run #{r.run_id}: {r.citation_a}  ↔  {r.citation_b or "—"}')
        else:
            w('\n  No approved analyses referenced the old version.')
