"""Re-check whether approved comparison assessments still match their sources.

    python manage.py check_run_currency              # dry run
    python manage.py check_run_currency --apply
    python manage.py check_run_currency --all --apply

Reads each run's stamped `source_snapshot` and compares it against the live
documents. Writes only `currency_state`, `outdated_reason` and
`currency_checked_at` — never a lifecycle, never a result, never a feedback
signal.

An assessment reaches `current` only on POSITIVE evidence that both sources
still match. Where evidence is missing — most often a document with no content
hash — the answer is `unknown`, not `current`.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Re-check the currency of approved comparison assessments '
            '(dry run by default).')

    def add_arguments(self, parser):
        parser.add_argument('run_id', nargs='?', type=int)
        parser.add_argument('--all', action='store_true',
                            help='check every run, not just approved ones')
        parser.add_argument('--apply', action='store_true',
                            help='persist the verdicts (default is a dry run)')

    def handle(self, *args, **opts):
        from collections import Counter
        from apps.comparison.models import ComparisonRun
        from apps.comparison.assessments import assess_currency, apply_currency

        w = self.stdout.write
        apply_changes = opts['apply']

        if opts['run_id']:
            runs = list(ComparisonRun.objects.filter(pk=opts['run_id'])
                        .select_related('reg_a', 'reg_b'))
            if not runs:
                w(self.style.ERROR(f'No run with id {opts["run_id"]}'))
                return
        elif opts['all']:
            runs = list(ComparisonRun.objects.all().select_related('reg_a', 'reg_b'))
        else:
            runs = list(ComparisonRun.objects
                        .filter(lifecycle__in=[ComparisonRun.APPROVED,
                                               ComparisonRun.SUPERSEDED])
                        .select_related('reg_a', 'reg_b'))

        if not runs:
            w('No runs to check. Approve an assessment first, or pass --all.')
            return

        w(self.style.MIGRATE_HEADING(
            f'\nChecking {len(runs)} run(s)'
            + ('' if apply_changes else '   [DRY RUN]')))

        states, transitions = Counter(), []
        for run in runs:
            before = run.currency_state
            verdict = (apply_currency(run) if apply_changes
                       else assess_currency(run))
            states[verdict.state] += 1
            if verdict.state != before:
                transitions.append((run, before, verdict))

            marker = {'current': '  OK  ', 'outdated': ' STALE', 'unknown': '  ??  '}
            w(f'{marker.get(verdict.state, "  ?   ")} run {run.pk:<5} '
              f'{run.reg_a.name[:26]:28s} -> {run.reg_b.name[:26]:28s} '
              f'{verdict.state}')
            if verdict.reason:
                w(f'          {verdict.reason[:100]}')
            # Surfaced because a fingerprint match that did NOT produce
            # `current` is exactly the empty-hash trap: equal fingerprints,
            # no evidence behind them.
            if verdict.fingerprint_matched and verdict.state != 'current':
                w('          (fingerprints match, but the match rests on '
                  'missing evidence — not proof of sameness)')

        w('')
        w(self.style.MIGRATE_HEADING('Summary'))
        for state in ('current', 'outdated', 'unknown'):
            w(f'  {state:<10} {states.get(state, 0)}')
        if transitions:
            w('')
            w(self.style.WARNING(f'State changes ({len(transitions)}):'))
            for run, before, verdict in transitions:
                w(f'  run {run.pk}: {before} -> {verdict.state}'
                  + (f'  ({verdict.reason[:70]})' if verdict.reason else ''))

        if not apply_changes:
            w(self.style.SUCCESS('\nDry run only — nothing written. Re-run with --apply.'))
        else:
            w(self.style.SUCCESS(f'\n[OK] {len(runs)} run(s) checked'))
