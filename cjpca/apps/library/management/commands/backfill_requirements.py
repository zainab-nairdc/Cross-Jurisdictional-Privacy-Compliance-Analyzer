"""Rebuild a canonical requirement baseline from existing analysis rows.

Every ObligationMapping ever produced cites a regulatory chunk and quotes it
verbatim. That citation is the trustworthy part of a legacy row — far more so
than `obligation_text`, which across older runs holds coverage commentary
("Cross-border disposal gap.") rather than a requirement. So the baseline is
built from what past runs GROUNDED themselves in, not from what they concluded:

    one canonical Requirement per (regulation, source chunk)
    text taken from regulation_evidence, the verbatim regulatory quote
    every mapping linked to its requirement through the nullable FK

Nothing existing is modified. No ObligationMapping field is rewritten, no Gap is
touched, no approved finding changes. The only write to mapping rows is setting
the previously-null `requirement` FK.

Rows whose source chunk or evidence is missing are NOT given an invented
requirement — their FK stays null and they are reported.

Dry run is the default; pass --apply to write.

    python manage.py backfill_requirements
    python manage.py backfill_requirements --apply
"""

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Build canonical Requirements from existing ObligationMapping rows (dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='write the changes (default is a dry run)')

    def handle(self, *args, **opts):
        from apps.library.models import Requirement
        from apps.library.requirements import make_key, _normalise
        from apps.mapping.models import ObligationMapping, Gap

        w = self.stdout.write
        apply_changes = opts['apply']

        mappings = list(ObligationMapping.objects.all()
                        .select_related('regulation').order_by('pk'))
        total = len(mappings)

        # Group by the historical key: (regulation, source chunk). Deliberately
        # not by text — see the module docstring.
        groups: dict = defaultdict(list)
        no_chunk, no_evidence = [], []
        for m in mappings:
            chunk = (m.regulation_chunk_id or '').strip()
            evid  = (m.regulation_evidence or '').strip()
            if not chunk:
                no_chunk.append(m)
                continue
            if not evid:
                no_evidence.append(m)
                continue
            groups[(m.regulation_id, chunk)].append(m)

        linkable = sum(len(v) for v in groups.values())

        # Where rows quote DIFFERENT spans of the same chunk, the longest quote
        # is the canonical one: it is the most complete verbatim extent of the
        # same provision. This picks among quotes of one chunk — it does not
        # merge distinct requirements, and it is deterministic.
        variant_groups = {k: v for k, v in groups.items()
                          if len({_normalise(m.regulation_evidence) for m in v}) > 1}

        already = Requirement.objects.filter(extraction_source=Requirement.MIGRATED).count()
        already_linked = ObligationMapping.objects.filter(requirement__isnull=False).count()

        w(self.style.MIGRATE_HEADING('\nBACKFILL REPORT' + ('' if apply_changes else '  (DRY RUN)')))
        w(f'  existing obligation mappings          : {total}')
        w(f'  mappings with a usable chunk+evidence : {linkable}')
        w(f'  canonical requirements to exist after : {len(groups)}')
        w(f'  mappings that will be linked          : {linkable}')
        w(f'  mappings missing regulation_evidence  : {len(no_evidence)}')
        w(f'  mappings missing source chunk id      : {len(no_chunk)}')
        w(f'  chunks quoted with differing spans    : {len(variant_groups)}'
          f'  (canonical quote = longest)')
        w(f'  migrated requirements already present : {already}')
        w(f'  mappings already linked               : {already_linked}')

        per_req = Counter(len(v) for v in groups.values())
        w('\n  mappings per canonical requirement:')
        for n in sorted(per_req):
            w(f'    {n} mapping(s) -> {per_req[n]} requirement(s)')

        if no_chunk or no_evidence:
            w(self.style.WARNING('\n  LEFT UNLINKED (no requirement invented):'))
            for m in (no_chunk + no_evidence)[:20]:
                why = 'no chunk id' if not (m.regulation_chunk_id or '').strip() else 'no evidence'
                w(f'    mapping #{m.pk} run={m.analysis_id} {m.article_ref[:30]!r} — {why}')

        if not apply_changes:
            w(self.style.SUCCESS('\nDry run only — nothing written. Re-run with --apply.'))
            return

        # Snapshot the invariants we promise not to disturb.
        gap_before = list(Gap.objects.order_by('pk')
                          .values_list('pk', 'priority', 'severity', 'remediation_text'))
        text_before = dict(ObligationMapping.objects.values_list('pk', 'obligation_text'))

        created = linked = 0
        with transaction.atomic():
            for (reg_id, chunk), rows in groups.items():
                key = make_key(chunk)          # chunk-scoped: the historical key
                # Longest quote wins, ties broken lexicographically so the pick
                # is deterministic and the backfill is repeatable.
                canonical = sorted(((r.regulation_evidence or '').strip() for r in rows),
                                   key=lambda s: (len(s), s))[-1]
                ref = next((r.article_ref for r in rows if r.article_ref), '')
                topics = next((r.topics for r in rows if r.topics), [])

                req, was_created = Requirement.objects.get_or_create(
                    regulation_id=reg_id, key=key,
                    defaults={
                        'text':              canonical,
                        'title':             canonical[:300],
                        'article_ref':       (ref or '')[:100],
                        'source_chunk_id':   chunk[:64],
                        'source_quote':      canonical,
                        'topics':            topics or [],
                        'extraction_source': Requirement.MIGRATED,
                    },
                )
                created += 1 if was_created else 0
                for r in rows:
                    if r.requirement_id != req.pk:
                        # The ONLY write to an existing row: the previously-null FK.
                        ObligationMapping.objects.filter(pk=r.pk).update(requirement=req)
                        linked += 1

        gap_after = list(Gap.objects.order_by('pk')
                         .values_list('pk', 'priority', 'severity', 'remediation_text'))
        text_after = dict(ObligationMapping.objects.values_list('pk', 'obligation_text'))

        w(self.style.MIGRATE_HEADING('\nAPPLIED'))
        w(f'  requirements created : {created}')
        w(f'  mappings linked      : {linked}')
        w(f'  gaps unchanged       : {gap_before == gap_after}')
        w(f'  obligation_text unchanged : {text_before == text_after}')
        if gap_before != gap_after or text_before != text_after:
            raise SystemExit(self.style.ERROR(
                'ABORT: the backfill altered data it must not touch.'))
        w(self.style.SUCCESS(
            f'\n[OK] {Requirement.objects.count()} canonical requirements; '
            f'{ObligationMapping.objects.filter(requirement__isnull=False).count()}'
            f'/{total} mappings linked'))
