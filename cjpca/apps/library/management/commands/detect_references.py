"""Detect and resolve legal cross-references for a regulation's requirements.

    python manage.py detect_references 151            # dry run
    python manage.py detect_references 151 --apply
    python manage.py detect_references --all
    python manage.py detect_references --all --apply --prune

Dry run by default, matching `extract_requirements`. References are derived
data produced by a heuristic detector, so writing them is a decision rather
than a side effect of inspecting them.

Reads a regulation's requirements and their source quotes, and writes
RequirementReference rows. It never touches Requirement rows, never reads a
policy, and produces no coverage verdict.

Re-runnable: rows are keyed on the fields fixed at detection time, so a second
run refreshes resolutions rather than duplicating references.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Detect legal cross-references in a regulation\'s requirements '
            '(dry run by default).')

    def add_arguments(self, parser):
        parser.add_argument('document_id', nargs='?', type=int)
        parser.add_argument('--all', action='store_true',
                            help='every regulation that has requirements')
        parser.add_argument('--apply', action='store_true',
                            help='write (default is a dry run)')
        parser.add_argument('--prune', action='store_true',
                            help='with --apply, drop regex-detected rows the '
                                 'current detector no longer produces')
        parser.add_argument('--samples', type=int, default=8,
                            help='how many detected references to print per '
                                 'regulation (default 8, 0 for none)')

    def handle(self, *args, **opts):
        from django.db.models import Count
        from apps.library.models import Document, RequirementReference
        from apps.library.references import detect_references_for_regulation

        w = self.stdout.write
        apply_changes = opts['apply']

        if opts['all']:
            docs = list(Document.objects
                        .annotate(n=Count('requirements'))
                        .filter(n__gt=0).order_by('name'))
        elif opts['document_id']:
            docs = list(Document.objects.filter(pk=opts['document_id']))
            if not docs:
                w(self.style.ERROR(f'No document with id {opts["document_id"]}'))
                return
        else:
            w(self.style.ERROR('Give a document id or --all'))
            return

        if opts['prune'] and not apply_changes:
            w(self.style.WARNING('--prune has no effect without --apply'))

        totals = {'detected': 0, 'resolved': 0, 'ambiguous': 0,
                  'unresolved': 0, 'created': 0, 'updated': 0, 'pruned': 0}

        for doc in docs:
            rep = detect_references_for_regulation(
                doc, dry_run=not apply_changes, prune=opts['prune'])
            if not rep['requirements']:
                continue

            w(self.style.MIGRATE_HEADING(
                f'\n{doc.name}  (id={doc.pk}, {doc.jurisdiction})'
                + ('' if apply_changes else '   [DRY RUN]')))
            w(f'  requirements              : {rep["requirements"]}')
            w(f'  numbered articles indexed : {rep["indexed_articles"]}')
            if not rep['indexed_articles']:
                w(self.style.WARNING(
                    '  no numbered provisions in the index — internal '
                    'references cannot resolve for this document'))
            w(f'  references detected       : {rep["detected"]}')
            w(f'      resolved   : {rep["resolved"]}')
            w(f'      ambiguous  : {rep["ambiguous"]}')
            w(f'      unresolved : {rep["unresolved"]}')
            if rep['by_kind']:
                w('  by kind  : ' + ', '.join(
                    f'{k}={v}' for k, v in sorted(rep['by_kind'].items())))
            if rep['by_scope']:
                w('  by scope : ' + ', '.join(
                    f'{k}={v}' for k, v in sorted(rep['by_scope'].items())))
            if apply_changes:
                w(f'  rows created / updated    : '
                  f'{rep["created"]} / {rep["updated"]}')
                if rep['pruned']:
                    w(f'  stale rows pruned         : {rep["pruned"]}')

            limit = opts['samples']
            if limit and rep['samples']:
                w('  sample:')
                for s in rep['samples'][:limit]:
                    extra = (f' [{s["candidates"]} candidates]'
                             if s['candidates'] else '')
                    w(f'      {s["status"]:<10} {s["ref_text"][:44]!r:<48}'
                      f' n={s["ref_number"] or "-":<9}{extra}')
                    w(f'                 {s["note"][:96]}')

            for k in totals:
                totals[k] += rep.get(k, 0)

        w('')
        w(self.style.MIGRATE_HEADING('Totals'))
        w(f'  detected {totals["detected"]} | resolved {totals["resolved"]} | '
          f'ambiguous {totals["ambiguous"]} | unresolved {totals["unresolved"]}')

        if not apply_changes:
            w(self.style.SUCCESS(
                '\nDry run only — nothing written. Re-run with --apply.'))
        else:
            w(self.style.SUCCESS(
                f'\n[OK] {RequirementReference.objects.count()} references in '
                f'the store ({totals["created"]} created, '
                f'{totals["updated"]} updated this run)'))
