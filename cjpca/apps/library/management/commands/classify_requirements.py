"""Assign official taxonomy topics to a regulation's requirements.

    python manage.py classify_requirements 151            # dry run
    python manage.py classify_requirements 151 --apply
    python manage.py classify_requirements --all
    python manage.py classify_requirements --all --semantic

Dry run by default, matching `extract_requirements` and `detect_references`.

A requirement may receive ZERO, ONE, or SEVERAL topics — several is normal and
correct. Concepts that no official topic represents are reported as UNRESOLVED
and are never forced into the nearest existing topic; they become input to the
human review workflow, and nothing here can add anything to the official
taxonomy.

Separate from extraction: this reads stored Requirements and writes only their
topic assignments. It cannot alter or delete a requirement, so a classification
failure never costs legal text.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Classify a regulation\'s requirements into official taxonomy '
            'topics (multi-topic, dry run by default).')

    def add_arguments(self, parser):
        parser.add_argument('document_id', nargs='?', type=int)
        parser.add_argument('--all', action='store_true',
                            help='every regulation that has requirements')
        parser.add_argument('--apply', action='store_true',
                            help='write (default is a dry run)')
        parser.add_argument('--semantic', action='store_true',
                            help='enable the embedding-based resolution step '
                                 '(loads the embedding model)')
        parser.add_argument('--limit', type=int, default=None,
                            help='classify at most N requirements per regulation')
        parser.add_argument('--max-topics', type=int, default=None,
                            help='cap on topics per requirement in MODEL output')

    def handle(self, *args, **opts):
        from collections import Counter
        from django.db.models import Count
        from apps.library.models import Document, RequirementTopic
        from apps.library.topics import classify_requirements_for_regulation
        from reasoning import taxonomy
        from reasoning.requirement_classify import MAX_TOPICS

        w = self.stdout.write
        apply_changes = opts['apply']
        max_topics = opts['max_topics'] or MAX_TOPICS

        embed_fn = None
        if opts['semantic']:
            embed_fn = taxonomy.default_embed_fn()
            w('Semantic resolution enabled (embedding model will load on '
              'first unresolved concept).')

        if opts['all']:
            docs = list(Document.objects.annotate(n=Count('requirements'))
                        .filter(n__gt=0).order_by('name'))
        elif opts['document_id']:
            docs = list(Document.objects.filter(pk=opts['document_id']))
            if not docs:
                w(self.style.ERROR(f'No document with id {opts["document_id"]}'))
                return
        else:
            w(self.style.ERROR('Give a document id or --all'))
            return

        agg = Counter()
        by_topic, unresolved, by_method = Counter(), Counter(), Counter()
        multi_examples, all_errors = [], Counter()

        for doc in docs:
            rep = classify_requirements_for_regulation(
                doc, dry_run=not apply_changes, embed_fn=embed_fn,
                max_topics=max_topics, limit=opts['limit'])
            if not rep['requirements']:
                continue

            w(self.style.MIGRATE_HEADING(
                f'\n{doc.name}  (id={doc.pk}, {doc.jurisdiction})'
                + ('' if apply_changes else '   [DRY RUN]')))
            w(f'  requirements          : {rep["requirements"]}')
            w(f'  classified / failed   : {rep["classified"]} / {rep["failed"]}')
            w(f'  zero / one / multi    : {rep["zero_topic"]} / '
              f'{rep["one_topic"]} / {rep["multi_topic"]}')
            w(f'  official assignments  : {rep["matched"]}')
            w(f'  unresolved concepts   : {rep["suggested"]}')
            if rep['unclassified_concepts']:
                w(f'  low-confidence drops  : {rep["unclassified_concepts"]}')
            if apply_changes:
                w(f'  rows written          : {rep["created"]}')
            if rep['errors']:
                for why, n in rep['errors'].most_common(3):
                    w(self.style.WARNING(f'      {n:>3}x {why}'))

            for key in ('requirements', 'classified', 'failed', 'zero_topic',
                        'one_topic', 'multi_topic', 'matched', 'suggested',
                        'unclassified_concepts', 'low_confidence', 'created'):
                agg[key] += rep[key]
            by_topic.update(rep['by_topic'])
            by_method.update(rep['by_method'])
            unresolved.update(rep['unresolved_concepts'])
            all_errors.update(rep['errors'])
            multi_examples.extend(rep['multi_examples'])

        # ── corpus-level summary ──
        w('')
        w(self.style.MIGRATE_HEADING('═' * 66))
        w(self.style.MIGRATE_HEADING('CORPUS SUMMARY'))
        w(self.style.MIGRATE_HEADING('═' * 66))
        total = agg['classified']
        w(f'  taxonomy version        : {taxonomy.TAXONOMY_VERSION}')
        w(f'  requirements seen       : {agg["requirements"]}')
        w(f'  classified / failed     : {total} / {agg["failed"]}')
        if total:
            avg = agg['matched'] / total
            w(f'  avg topics/requirement  : {avg:.2f}')
            w(f'  zero-topic requirements : {agg["zero_topic"]} '
              f'({100*agg["zero_topic"]/total:.0f}%)')
            w(f'  one-topic requirements  : {agg["one_topic"]} '
              f'({100*agg["one_topic"]/total:.0f}%)')
            w(f'  multi-topic requirements: {agg["multi_topic"]} '
              f'({100*agg["multi_topic"]/total:.0f}%)')
        w(f'  official assignments    : {agg["matched"]}')
        w(f'  unresolved concepts     : {agg["suggested"]}')
        w(f'  low-confidence drops    : {agg["low_confidence"]}')

        if by_method:
            w('\n  resolution method:')
            for m, n in by_method.most_common():
                w(f'      {m:<12} {n}')

        if by_topic:
            w('\n  most common resolved topics:')
            for t, n in by_topic.most_common(12):
                w(f'      {n:>4}x {t}  ({taxonomy.topic_label(t)})')

        if unresolved:
            w('\n  most common UNRESOLVED concepts '
              '(candidates for human review — NOT official topics):')
            for c, n in unresolved.most_common(20):
                w(f'      {n:>4}x {c!r}')
        else:
            w('\n  no unresolved concepts — every concept the model produced '
              'mapped onto the existing taxonomy.')

        if multi_examples:
            w('\n  examples of genuinely multi-topic requirements:')
            for ex in multi_examples[:8]:
                w(f'      req#{ex["requirement"]} {ex["article_ref"][:40]}')
                w(f'        {ex["text"][:110]}')
                w('        -> ' + ', '.join(
                    f'{t}/{s or "-"} ({c}, {m})' for t, s, c, m in ex['topics']))

        if all_errors:
            w('\n  failures:')
            for why, n in all_errors.most_common(6):
                w(f'      {n:>4}x {why}')

        if not apply_changes:
            w(self.style.SUCCESS(
                '\nDry run only — nothing written. Re-run with --apply.'))
        else:
            w(self.style.SUCCESS(
                f'\n[OK] {RequirementTopic.objects.count()} topic assignments '
                f'in the store'))
