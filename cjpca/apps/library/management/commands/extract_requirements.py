"""Extract canonical requirements for a regulation version.

    python manage.py extract_requirements 98            # dry run
    python manage.py extract_requirements 98 --apply
    python manage.py extract_requirements --all --apply

Regulation side only: this reads one document's indexed provisions and writes
Requirement rows. It never sees a policy, never produces a coverage verdict, and
is not connected to the comparison pipeline.
"""

from collections import Counter

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Extract canonical Requirements from a regulation (dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('document_id', nargs='?', type=int)
        parser.add_argument('--all', action='store_true',
                            help='every regulation with no native requirements yet')
        parser.add_argument('--apply', action='store_true',
                            help='write (default is a dry run)')

    def handle(self, *args, **opts):
        from apps.library.models import Document, Requirement
        from apps.library.extraction import extract_for_regulation

        w = self.stdout.write
        apply_changes = opts['apply']

        if opts['all']:
            docs = list(Document.objects.filter(doc_type=Document.REGULATION,
                                                superseded=False))
        elif opts['document_id']:
            docs = list(Document.objects.filter(pk=opts['document_id']))
            if not docs:
                w(self.style.ERROR(f'No document with id {opts["document_id"]}'))
                return
        else:
            w(self.style.ERROR('Give a document id or --all'))
            return

        for doc in docs:
            w(self.style.MIGRATE_HEADING(
                f'\n{doc.name}  (id={doc.pk}, {doc.jurisdiction})'
                + ('' if apply_changes else '   [DRY RUN]')))
            # nli left unset on purpose — see _MAX_UNSUPPORTED in
            # reasoning.requirement_extract. The hard gate is the structural
            # check that the quote occurs verbatim in its source chunk.
            rep = extract_for_regulation(doc, dry_run=not apply_changes)
            if not rep['total_chunks']:
                w(self.style.WARNING(
                    f'  no indexed chunks for {doc.chunk_doc_title!r} — skipped'
                    ' (ingest the document first)'))
                continue
            w(f'  indexed chunks            : {rep["total_chunks"]}')
            w(f'  obligation-bearing chunks : {rep["candidate_chunks"]}')
            w(f'  chunks that yielded a rule: {rep["chunks_with_output"]}')
            if apply_changes:
                w(f'  requirements created      : {rep["created"]}')
                w(f'  already present           : {rep["existing"]}')
            else:
                w(f'  requirements WOULD create : {rep["would_create"]}')
            w(f'  model output rejected     : {rep["rejected_candidates"]}')
            if rep['rejection_reasons']:
                for why, n in Counter(rep['rejection_reasons']).most_common(5):
                    w(f'      {n:>3}x {why}')
            if rep['migrated_overlap']:
                w(self.style.WARNING(
                    f'  chunks that ALSO have a migrated requirement: '
                    f'{len(rep["migrated_overlap"])}'))
                w('      (migrated rows left untouched — resolve by hand)')
                for o in rep['migrated_overlap'][:5]:
                    w(f'      chunk {o["chunk"][:12]} migrated#{o["migrated_requirement_id"]}'
                      f' native#{o["native_requirement_id"]}')

        if not apply_changes:
            w(self.style.SUCCESS('\nDry run only — nothing written. Re-run with --apply.'))
        else:
            w(self.style.SUCCESS(
                f'\n[OK] {Requirement.objects.filter(extraction_source=Requirement.LLM).count()}'
                f' natively-extracted requirements in the store'))
