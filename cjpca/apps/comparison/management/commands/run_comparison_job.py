from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run a ComparisonRun job by primary key (used by subprocess launcher).'

    def add_arguments(self, parser):
        parser.add_argument('run_pk', type=int)
        parser.add_argument('--include-orphans', action='store_true', default=False)
        parser.add_argument('--articles-a', nargs='*', default=None)
        parser.add_argument('--articles-b', nargs='*', default=None)

    def handle(self, *args, **options):
        from apps.comparison.models import ComparisonRun
        from apps.comparison.views import _run_comparison_background
        # Re-assert RUNNING in case AppConfig.ready() reset us during startup.
        ComparisonRun.objects.filter(pk=options['run_pk']).update(
            status=ComparisonRun.RUNNING, error_message='',
        )
        _run_comparison_background(
            run_pk=options['run_pk'],
            include_orphans=options['include_orphans'],
            articles_a=options['articles_a'],
            articles_b=options['articles_b'],
        )
