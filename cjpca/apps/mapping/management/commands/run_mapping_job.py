from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run a MappingAnalysis job by primary key (used by subprocess launcher).'

    def add_arguments(self, parser):
        parser.add_argument('analysis_pk', type=int)

    def handle(self, *args, **options):
        from apps.mapping.models import MappingAnalysis
        from apps.mapping.views import _run_mapping_job
        # Re-assert RUNNING in case AppConfig.ready() reset us during startup.
        MappingAnalysis.objects.filter(pk=options['analysis_pk']).update(
            status=MappingAnalysis.RUNNING, error='',
        )
        _run_mapping_job(options['analysis_pk'])
