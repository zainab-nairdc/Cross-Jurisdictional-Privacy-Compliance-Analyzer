"""End-to-end self-test for regulation version management (feasibility).

Simulates the whole flow with throwaway records, then cleans up:
  1. create two versions of a regulation (v1, v2) sharing an identity
  2. an analyst runs a comparison on v1 and a reviewer APPROVES it
  3. v2 supersedes v1  -> v1 becomes 'superseded', v2 'in_force'
  4. the approved analysis that used v1 is flagged 're-review recommended'
  5. version_family links the two together

Run:  python manage.py version_selftest
      python manage.py version_selftest --keep
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Exercise regulation version management end-to-end with throwaway records.'

    def add_arguments(self, parser):
        parser.add_argument('--keep', action='store_true', help='keep the demo rows')

    def handle(self, *args, **opts):
        from apps.library.models import Document
        from apps.comparison.models import ComparisonRun, ComparisonResult
        w = self.stdout.write

        other = Document.objects.filter(doc_type='regulation').exclude(document_id='TEST-VER').first()
        if not other:
            w('Need at least one regulation document to run the self-test.')
            return

        v1 = Document.objects.create(name='TEST Reg (2022)', doc_type='regulation',
                                     document_id='TEST-VER', version='2022', jurisdiction='other')
        v2 = Document.objects.create(name='TEST Reg (2025 amendment)', doc_type='regulation',
                                     document_id='TEST-VER', version='2025', jurisdiction='other')

        run = ComparisonRun.objects.create(pair_key='vertest', reg_a=v1, reg_b=other,
                                           topics=['governance'], status='complete')
        appr = ComparisonResult.objects.create(
            run=run, citation_a='TEST Reg (2022) — Article 5', citation_b=f'{other.name} — Art. X',
            relationship='equivalent', lifecycle=ComparisonResult.APPROVED)

        w(self.style.MIGRATE_HEADING('\n1) Two versions created'))
        w(f'   v1 status: {v1.version_status}   v2 status: {v2.version_status}')

        w(self.style.MIGRATE_HEADING('2) A reviewer APPROVED a comparison that used v1'))
        w(f'   approved analyses referencing v1: {v1.affected_approved_analyses().count()}')

        w(self.style.MIGRATE_HEADING('3) v2 supersedes v1'))
        affected = v1.supersede_with(v2)
        v1.refresh_from_db(); v2.refresh_from_db()
        w(f'   v1 status -> {v1.version_status}   (superseded_by = {v1.superseded_by})')
        w(f'   v2 status -> {v2.version_status}   (parent = {v2.parent_regulation})')

        w(self.style.MIGRATE_HEADING('4) Change-impact — approved work that now needs re-review'))
        for r in affected:
            w(f'   ⚠ re-review: run #{r.run_id}  "{r.citation_a}"')

        w(self.style.MIGRATE_HEADING('5) version_family links them'))
        fam = list(v2.version_family().values_list('name', flat=True))
        w(f'   v2 family: {fam}')

        ok = (v1.version_status == 'superseded' and v2.version_status == 'in_force'
              and affected.count() == 1 and 'TEST Reg (2022)' in fam)
        w(self.style.SUCCESS('\n✓ VERSION MANAGEMENT OK') if ok else self.style.ERROR('\n✗ flow incomplete'))

        if not opts['keep']:
            run.delete()            # cascades to the result
            v1.delete(); v2.delete()
            w('\n(cleaned up demo rows — pass --keep to retain them)')
