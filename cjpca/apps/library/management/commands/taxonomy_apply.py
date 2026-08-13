"""Show the taxonomy change an approved suggestion would require.

    python manage.py taxonomy_apply 7                  # print the patch
    python manage.py taxonomy_apply 7 --out patch.txt  # save it for review
    python manage.py taxonomy_apply --list             # what is awaiting release
    python manage.py taxonomy_apply 7 --mark-active    # AFTER committing it

THIS COMMAND NEVER WRITES reasoning/taxonomy.py.

That is the whole point of it. The official taxonomy is human-edited source
code because a change to it alters TAXONOMY_VERSION, which decides whether
every stored classification in the corpus is still valid. A process that could
edit the file automatically would be able to invalidate the entire corpus
without anyone reviewing the change.

So the flow is:

    approve (in the UI or here)  ->  status = approved_pending_release
    this command                 ->  prints the exact source change
    a human edits + commits      ->  TAXONOMY_VERSION changes
    --mark-active                ->  VERIFIES the topic is really there,
                                     then marks the suggestion active

`--mark-active` refuses if the topic is not in the live taxonomy, so `active`
can never claim something the source file does not back.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Print the proposed reasoning/taxonomy.py change for an approved '
            'topic suggestion. Never writes the file.')

    def add_arguments(self, parser):
        parser.add_argument('suggestion_id', nargs='?', type=int)
        parser.add_argument('--list', action='store_true',
                            help='list suggestions awaiting taxonomy release')
        parser.add_argument('--out', type=str, default=None,
                            help='write the patch to this file for review '
                                 '(never taxonomy.py)')
        parser.add_argument('--mark-active', action='store_true',
                            help='confirm the change has been committed; '
                                 'verifies the topic exists before marking it')

    def handle(self, *args, **opts):
        from pathlib import Path
        from apps.library.models import TopicSuggestion as TS
        from apps.library.suggestions import build_patch, mark_active
        from reasoning import taxonomy

        w = self.stdout.write

        if opts['list']:
            pending = TS.objects.filter(status=TS.APPROVED_PENDING_RELEASE)
            if not pending:
                w('No suggestions are awaiting taxonomy release.')
                return
            w(self.style.MIGRATE_HEADING('Awaiting taxonomy release:'))
            for s in pending:
                w(f'  #{s.pk:<5} {s.proposed_name:<40} -> {s.target_leaf}')
                w(f'         {s.occurrence_count} occurrence(s), '
                  f'expects {s.expected_taxonomy_version}')
            w(f'\nCurrent taxonomy version: {taxonomy.TAXONOMY_VERSION}')
            return

        if not opts['suggestion_id']:
            w(self.style.ERROR('Give a suggestion id, or --list'))
            return

        try:
            s = TS.objects.get(pk=opts['suggestion_id'])
        except TS.DoesNotExist:
            w(self.style.ERROR(f'No suggestion with id {opts["suggestion_id"]}'))
            return

        if opts['mark_active']:
            try:
                mark_active(s)
            except ValueError as exc:
                w(self.style.ERROR(f'Refused: {exc}'))
                return
            w(self.style.SUCCESS(
                f'[OK] Suggestion #{s.pk} marked ACTIVE — {s.target_leaf} is '
                f'in the official taxonomy at {taxonomy.TAXONOMY_VERSION}'))
            return

        if s.status != TS.APPROVED_PENDING_RELEASE:
            w(self.style.WARNING(
                f'Suggestion #{s.pk} is {s.status!r}, not '
                f'{TS.APPROVED_PENDING_RELEASE!r}. Showing the patch anyway, '
                f'but it should be approved by a reviewer first.'))

        patch = s.proposed_patch or build_patch(s)
        w('')
        w(patch)
        w('')

        if opts['out']:
            target = Path(opts['out'])
            if target.name == 'taxonomy.py':
                w(self.style.ERROR(
                    'Refusing to write to a file named taxonomy.py. This '
                    'command produces a change for a human to apply; it does '
                    'not apply it.'))
                return
            target.write_text(patch, encoding='utf-8')
            w(self.style.SUCCESS(f'[OK] Patch written to {target} for review.'))

        w(self.style.WARNING(
            'reasoning/taxonomy.py was NOT modified. Apply the change by hand, '
            'commit it, then run:\n'
            f'    manage.py taxonomy_apply {s.pk} --mark-active'))
