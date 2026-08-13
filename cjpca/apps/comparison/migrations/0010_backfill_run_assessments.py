"""Backfill assessment identity onto runs that predate source-version tracking.

What this DOES:
  - gives every existing run an `assessment_key`, so historical runs group
    with any future re-run of the same question;
  - records a snapshot of the documents as they stand TODAY, flagged
    `backfilled: true`;
  - derives a run-level `lifecycle` from the per-result review state, but
    conservatively.

What this deliberately does NOT do:

  It never sets `source_fingerprint`, and it never sets `currency_state` to
  `current`. These runs were executed before anything recorded which document
  versions were compared, so their currency is genuinely unknowable — a
  backfilled snapshot describes the documents NOW, which is not evidence of
  what was compared THEN. Leaving the fingerprint empty means such a run can
  never match a reuse lookup by accident.

  It also never sets `lifecycle = approved`, even for runs whose every result
  was approved individually. Approving forty obligation rows is not the same
  act as certifying the assessment, and a machine must not perform that act
  retroactively on a human's behalf. Those runs land in `in_review` and wait
  for a person to confirm them.

Nothing is deleted or overwritten. Reversing this migration clears only the
fields it populated.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    ComparisonRun = apps.get_model('comparison', 'ComparisonRun')
    Document      = apps.get_model('library', 'Document')

    # Historical models carry no custom properties, so family_root_id and
    # content_hash access are done by hand here rather than via the live model.
    def family_root(doc):
        seen, cur = set(), doc
        while cur.version_of_id and cur.version_of_id not in seen:
            seen.add(cur.pk)
            try:
                cur = Document.objects.get(pk=cur.version_of_id)
            except Document.DoesNotExist:
                break
        return cur.pk

    def descriptor(doc):
        if doc is None:
            return {}
        return {
            'pk': doc.pk,
            'document_id': doc.document_id or '',
            'name': doc.name,
            'version': doc.version or '',
            'jurisdiction': doc.jurisdiction or '',
            'content_hash': doc.content_hash or '',
            'chunk_doc_title': '',
            'family_root': family_root(doc),
            'superseded': bool(doc.superseded),
        }

    import hashlib
    import json

    def sha(payload):
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(',', ':'))
            .encode('utf-8')).hexdigest()

    for run in ComparisonRun.objects.select_related('reg_a', 'reg_b'):
        topics = sorted({str(t).strip() for t in (run.topics or []) if str(t).strip()})
        scope = {'mode': 'topics' if topics else 'full', 'topics': topics}

        run.assessment_key = sha({
            'v': 1,
            'a': family_root(run.reg_a) if run.reg_a_id else None,
            'b': family_root(run.reg_b) if run.reg_b_id else None,
            'orientation': 'a_to_b',
            'scope': scope,
        })[:40]

        run.source_snapshot = {
            'schema': 1,
            'orientation': 'a_to_b',
            'reg_a': descriptor(run.reg_a),
            'reg_b': descriptor(run.reg_b),
            'scope': {**scope, 'include_orphans': False},
            'engine': {'model': '', 'prompt': '', 'taxonomy': ''},
            # The flag that stops anything treating this as verified evidence.
            'backfilled': True,
            'backfill_note': (
                'Reconstructed from current document state. This run predates '
                'source-version tracking, so the versions actually compared '
                'were not recorded and its currency cannot be established.'),
        }

        # Left empty on purpose — see the module docstring.
        run.source_fingerprint = ''
        run.currency_state = 'unknown'
        run.outdated_reason = ''

        # Conservative lifecycle: anything a human explicitly handed to a
        # reviewer is `in_review`; everything else stays `draft`. Never
        # `approved` — that is a decision only a person can make.
        lifecycles = list(run.results.values_list('lifecycle', flat=True))
        decided = bool(lifecycles) and all(l != 'draft' for l in lifecycles)
        if run.submitted_for_review_at or decided:
            run.lifecycle = 'in_review'
        else:
            run.lifecycle = 'draft'

        run.version_no = 0
        run.save(update_fields=[
            'assessment_key', 'source_snapshot', 'source_fingerprint',
            'currency_state', 'outdated_reason', 'lifecycle', 'version_no'])


def unbackfill(apps, schema_editor):
    ComparisonRun = apps.get_model('comparison', 'ComparisonRun')
    ComparisonRun.objects.update(
        assessment_key='', source_snapshot={}, source_fingerprint='',
        currency_state='unknown', outdated_reason='', lifecycle='draft',
        version_no=0)


class Migration(migrations.Migration):

    dependencies = [
        ('comparison', '0009_comparisonrun_approved_at_comparisonrun_approved_by_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
