"""
Management command: process_queued_jobs

Kicks off the ingestion pipeline for any jobs that are stuck in QUEUED or
RUNNING state (e.g. left over from a server restart).

Usage:
    python manage.py process_queued_jobs
    python manage.py process_queued_jobs --job-id 3
"""
import time
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Process queued ingestion jobs via the background pipeline runner.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--job-id', type=int, default=None,
            help='Process a single job by ID instead of all queued jobs.',
        )
        parser.add_argument(
            '--wait', action='store_true',
            help='Block until all launched jobs finish (polls every 5 s).',
        )

    def handle(self, *args, **options):
        from apps.ingestion.models  import IngestionJob
        from apps.ingestion.pipeline import run_job

        if options['job_id']:
            jobs = IngestionJob.objects.filter(pk=options['job_id'])
        else:
            jobs = IngestionJob.objects.filter(
                status__in=[IngestionJob.QUEUED, IngestionJob.RUNNING]
            ).select_related('document')

        job_list = list(jobs)
        if not job_list:
            self.stdout.write('No queued jobs found.')
            return

        self.stdout.write(f'Launching {len(job_list)} job(s)...')
        launched_ids = []
        for job in job_list:
            self.stdout.write(f'  - Job {job.pk}: {job.document.name}')
            run_job(job.pk)
            launched_ids.append(job.pk)

        if options['wait']:
            self.stdout.write('Waiting for jobs to complete...')
            while True:
                remaining = IngestionJob.objects.filter(
                    pk__in=launched_ids,
                    status__in=[IngestionJob.QUEUED, IngestionJob.RUNNING],
                ).count()
                if remaining == 0:
                    break
                self.stdout.write(f'  {remaining} job(s) still running...', ending='\r')
                self.stdout.flush()
                time.sleep(5)
            self.stdout.write('\nAll jobs finished.')
            for job in IngestionJob.objects.filter(pk__in=launched_ids):
                status_display = 'OK' if job.status == IngestionJob.COMPLETE else 'FAILED'
                self.stdout.write(f'  Job {job.pk}: {status_display} — {job.document.name}')
        else:
            self.stdout.write('Jobs launched in background threads. Check the UI for progress.')
