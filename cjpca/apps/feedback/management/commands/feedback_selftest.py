"""End-to-end self-test for the RAG feedback loop (feasibility).

Simulates the whole loop with throwaway records, then cleans up:
  1. create a comparison run + result (an AI-produced obligation)
  2. a reviewer APPROVES it            -> FeedbackSignal + GoldExemplar created
  3. a reviewer REJECTS another        -> FeedbackSignal (no gold)
  4. retrieve gold for the topic       -> proves it's reusable
  5. build the few-shot block          -> proves it can be injected into a prompt

Run:  python manage.py feedback_selftest
      python manage.py feedback_selftest --keep   (don't delete the demo rows)
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Exercise the RAG feedback loop end-to-end with throwaway records.'

    def add_arguments(self, parser):
        parser.add_argument('--keep', action='store_true', help='keep the demo rows')

    def handle(self, *args, **opts):
        from apps.library.models import Document
        from apps.comparison.models import ComparisonRun, ComparisonResult
        from apps.feedback.models import FeedbackSignal, GoldExemplar
        from apps.feedback.services import capture_comparison_transition, gold_for_topic, build_fewshot

        w = self.stdout.write
        docs = list(Document.objects.filter(doc_type='regulation')[:2])
        if len(docs) < 2:
            w('Need at least 2 regulation documents to run the self-test.')
            return
        a, b = docs[0], docs[1]

        run = ComparisonRun.objects.create(pair_key='selftest', reg_a=a, reg_b=b,
                                           topics=['lawful_basis'], status='complete')
        approved = ComparisonResult.objects.create(
            run=run, citation_a=f'{a.name} — Article 6', citation_b=f'{b.name} — Article 4',
            relationship='equivalent', confidence=0.9, similarity_score=0.88,
            principle_ids=['lawful_basis'],
            practical_conclusion='A single lawful-basis register + privacy governance policy satisfies both.',
            compliance_impact='None', shared_controls=['Records of Processing Activities', 'Lawful-basis register'],
        )
        rejected = ComparisonResult.objects.create(
            run=run, citation_a=f'{a.name} — Recital 3', citation_b='',
            relationship='additional_in_a', confidence=0.4, principle_ids=['lawful_basis'],
        )

        w(self.style.MIGRATE_HEADING('\n1) Reviewer APPROVES the strong row'))
        capture_comparison_transition(approved, 'approved', actor=None)
        w(self.style.MIGRATE_HEADING('2) Reviewer REJECTS the weak row'))
        capture_comparison_transition(rejected, 'rejected', actor=None)

        sigs = FeedbackSignal.objects.filter(source_id__in=[approved.pk, rejected.pk])
        gold = GoldExemplar.objects.filter(source_id=approved.pk)
        w(f'\n   FeedbackSignals captured : {sigs.count()}  ({", ".join(s.kind for s in sigs)})')
        w(f'   GoldExemplars created    : {gold.count()}  (only APPROVED promoted)')

        w(self.style.MIGRATE_HEADING('\n3) Loop closes — retrieve approved exemplars for the topic'))
        found = gold_for_topic('lawful_basis')
        w(f'   gold_for_topic("lawful_basis") -> {len(found)} exemplar(s)')

        w(self.style.MIGRATE_HEADING('\n4) Few-shot block that would be injected into the next comparison'))
        block = build_fewshot('lawful_basis')
        w('   ' + (block.replace('\n', '\n   ') if block else '(empty)'))

        ok = sigs.count() == 2 and gold.count() == 1 and bool(block)
        try:
            # ASCII only: a non-cp1252 glyph here raises UnicodeEncodeError on a
            # Windows console, which previously aborted the command BEFORE the
            # cleanup below and left demo rows in the real database.
            w(self.style.SUCCESS('\n[PASS] FEEDBACK LOOP OK') if ok
              else self.style.ERROR('\n[FAIL] loop incomplete'))
        finally:
            if not opts['keep']:
                FeedbackSignal.objects.filter(source_id__in=[approved.pk, rejected.pk]).delete()
                GoldExemplar.objects.filter(source_id=approved.pk).delete()
                run.delete()   # cascades to the results
                w('\n(cleaned up demo rows — pass --keep to retain them)')
