from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Delete all failed records across comparisons, mappings, ingestion jobs, and documents.'

    def handle(self, *args, **options):
        from apps.comparison.models import ComparisonRun
        from apps.mapping.models import MappingAnalysis
        from apps.ingestion.models import IngestionJob
        from apps.library.models import Document

        # Failed comparison runs (cascades to ComparisonResult)
        runs = ComparisonRun.objects.filter(status__in=['failed', 'partially_failed'])
        run_count = runs.count()
        runs.delete()
        self.stdout.write(f'  Deleted {run_count} failed comparison run(s)')

        # Failed mapping analyses (cascades to ObligationMapping)
        analyses = MappingAnalysis.objects.filter(status='failed')
        analysis_count = analyses.count()
        analyses.delete()
        self.stdout.write(f'  Deleted {analysis_count} failed mapping analysis/analyses')

        # Failed ingestion jobs
        jobs = IngestionJob.objects.filter(status='failed')
        job_count = jobs.count()
        jobs.delete()
        self.stdout.write(f'  Deleted {job_count} failed ingestion job(s)')

        # Failed documents (and their ingestion jobs via cascade)
        docs = Document.objects.filter(status='failed')
        doc_count = docs.count()
        docs.delete()
        self.stdout.write(f'  Deleted {doc_count} failed document(s)')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. Removed {run_count + analysis_count + job_count + doc_count} failed record(s) total.'
        ))
