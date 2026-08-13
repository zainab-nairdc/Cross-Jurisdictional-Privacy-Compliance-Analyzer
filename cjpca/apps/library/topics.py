"""Persistence of requirement topic assignments.

The classification pass proper lives in `reasoning.requirement_classify`; this
module owns what happens to its output: ranking, replacement, and keeping the
`Requirement.topics` compatibility mirror in step.

Three properties this module is responsible for:

  EXTRACTION IS UNAFFECTED. Nothing here writes to a Requirement's text, quote,
  key or provenance. A classification failure costs a classification — the
  legal text extracted from the regulation is untouched either way, and a
  requirement that cannot be classified is still a valid requirement.

  HUMAN DECISIONS SURVIVE. Reclassification replaces model-generated
  assignments and never touches `assignment=HUMAN` rows. A person's decision
  is not something an automated pass gets to overwrite.

  UNRESOLVED IS NOT UNCLASSIFIED. A concept no official topic represents is
  kept (assignment=SUGGESTED, blank topic) as input to the Phase 3 review
  workflow. A requirement with nothing to classify simply has no rows. Merging
  the two would either bury genuine taxonomy gaps or flood review with noise.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path

_BASE = Path(__file__).resolve().parents[3]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from reasoning import taxonomy                                    # noqa: E402
from reasoning.requirement_classify import (                      # noqa: E402
    MAX_TOPICS, classify_requirement,
)

logger = logging.getLogger(__name__)


# Ordering buckets. A HUMAN assignment outranks a model one regardless of the
# model's confidence — a person's decision is not competing with a guess.
# Beyond that, rank follows confidence, with a deterministic name tie-break so
# the same inputs always produce the same ranks.
#
# rank=0 does NOT mean "the only correct topic". Every MATCHED row is a real
# assignment; rank orders them, it does not grade them.
_BUCKET = {'human': 0, 'matched': 1, 'suggested': 2, 'unclassified': 3}


def _sort_key(row: dict) -> tuple:
    return (
        _BUCKET.get(row['assignment'], 9),
        -float(row.get('confidence') or 0.0),
        row.get('topic') or '',
        row.get('subcategory') or '',
        row.get('model_concept') or '',
    )


def plan_assignments(classification, *, max_topics: int = MAX_TOPICS) -> list[dict]:
    """Turn a RequirementClassification into ranked, deduplicated row dicts.

    Pure: no database access, so the dry-run path and the write path compute
    exactly the same thing and cannot drift.
    """
    from apps.library.models import RequirementTopic as RT

    rows: list[dict] = []
    seen_leaves: set = set()
    seen_concepts: set = set()

    for concept in classification.concepts:
        res = concept.resolution

        if res.is_matched:
            if res.leaf in seen_leaves:
                continue                       # already assigned
            seen_leaves.add(res.leaf)
            rows.append({
                'topic':             res.topic,
                'subcategory':       res.subcategory,
                'assignment':        RT.MATCHED,
                'resolution_method': res.method,
                'confidence':        res.confidence,
                'model_concept':     res.concept[:200],
                'evidence':          concept.evidence[:500],
                'reason':            '',
                'why_insufficient':  '',
            })
            continue

        # Not matched. Keyed by normalised wording so one model saying
        # "data minimisation" and "Data Minimisation" in one reply does not
        # produce two open concepts for the same idea.
        key = taxonomy.normalise_concept(res.concept)
        if not key or key in seen_concepts:
            continue

        if res.is_unresolved:
            # A meaningful concept the taxonomy does not represent. Preserved
            # for human review — this creates NO taxonomy entry.
            seen_concepts.add(key)
            rows.append({
                'topic':             '',
                'subcategory':       '',
                'assignment':        RT.SUGGESTED,
                'resolution_method': RT.NONE,
                'confidence':        res.confidence,
                'model_concept':     res.concept[:200],
                'evidence':          concept.evidence[:500],
                'reason':            concept.reason[:500],
                'why_insufficient':  concept.why_insufficient[:500],
            })
            continue

        # UNCLASSIFIED. A bare decline ("none", "n/a") records nothing — there
        # is no concept to keep. A concept rejected on CONFIDENCE is kept,
        # because "the model proposed retention at 0.15" is evidence about the
        # model that a reviewer may want, and it is explicitly not an official
        # topic.
        if taxonomy.is_no_fit(res.concept):
            continue
        seen_concepts.add(key)
        rows.append({
            'topic':             '',
            'subcategory':       '',
            'assignment':        RT.UNCLASSIFIED,
            'resolution_method': RT.NONE,
            'confidence':        res.confidence,
            'model_concept':     res.concept[:200],
            'evidence':          concept.evidence[:500],
            'reason':            '',
            'why_insufficient':  '',
        })

    official = [r for r in rows if r['assignment'] == RT.MATCHED]
    if len(official) > max_topics:
        # Bounds MODEL OUTPUT only; the schema imposes no limit. Dropping the
        # least-confident is the least-bad clip, and it is logged rather than
        # silent so an over-eager model is visible instead of looking like a
        # genuinely twelve-topic requirement.
        official.sort(key=_sort_key)
        dropped = official[max_topics:]
        logger.info('clipping %d topic(s) beyond max_topics=%d',
                    len(dropped), max_topics)
        drop_ids = {id(d) for d in dropped}
        rows = [r for r in rows if id(r) not in drop_ids]

    rows.sort(key=_sort_key)
    for i, row in enumerate(rows):
        row['rank'] = i
    return rows


def sync_topics_mirror(requirement) -> list[str]:
    """Rebuild `Requirement.topics` from the authoritative rows.

    The mirror holds OFFICIAL matched topic tags only, in rank order,
    deduplicated. Unresolved model concepts never enter it — putting them there
    would recreate the uncontrolled free-text vocabulary this phase exists to
    replace, in the very field that used to hold it.

    Writes only that one field, so it can never disturb extraction data.
    """
    from apps.library.models import RequirementTopic as RT

    tags: list[str] = []
    for row in (requirement.topic_assignments
                .filter(assignment__in=RT.OFFICIAL_ASSIGNMENTS)
                .exclude(topic='').order_by('rank', 'id')):
        if row.topic not in tags:
            tags.append(row.topic)

    if requirement.topics != tags:
        requirement.topics = tags
        requirement.save(update_fields=['topics', 'updated_at'])
    return tags


def _ingest_suggestions(requirement, classification, rows, *, embed_fn=None) -> int:
    """Route unresolved concepts into the review queue and link the rows.

    Runs AFTER persistence and is best-effort: a failure here must not undo a
    classification that otherwise succeeded. The suggestion queue is a review
    convenience; the RequirementTopic row is the record, and it already exists
    by this point.
    """
    from apps.library.models import RequirementTopic as RT
    from apps.library.suggestions import ingest_unresolved

    by_concept = {c.resolution.concept: c for c in classification.concepts}
    linked = 0
    for row in rows:
        if row.assignment != RT.SUGGESTED:
            continue
        concept = by_concept.get(row.model_concept)
        if concept is None:
            continue
        try:
            suggestion, _created = ingest_unresolved(
                concept.resolution,
                requirement      = requirement,
                evidence_quote   = requirement.source_quote or requirement.text,
                reason           = concept.reason,
                why_insufficient = concept.why_insufficient,
                chunk_node_id    = requirement.source_chunk_id or '',
                embed_fn         = embed_fn,
            )
        except Exception:
            logger.exception('suggestion intake failed for requirement %s',
                             requirement.pk)
            continue
        if suggestion is not None:
            row.suggestion = suggestion
            row.save(update_fields=['suggestion', 'updated_at'])
            linked += 1
    return linked


def apply_classification(requirement, classification, *,
                         max_topics: int = MAX_TOPICS,
                         embed_fn=None, ingest_suggestions: bool = True) -> dict:
    """Persist a classification, replacing this requirement's model-generated rows.

    Replacement rather than merge, deliberately: a re-run under a new taxonomy
    or a better prompt should leave the requirement holding what the CURRENT
    classifier believes, not an accumulation of everything every past run ever
    proposed. Merging would make assignments impossible to attribute and
    impossible to retract.

    `assignment=HUMAN` rows are exempt — they are neither deleted nor
    overwritten, and a model row that would collide with one is dropped so the
    human's version stands.

    A failed classification (ok=False) writes NOTHING and leaves existing rows
    in place: a technical failure is not evidence that the previous assignments
    were wrong.
    """
    from django.db import transaction
    from apps.library.models import RequirementTopic as RT

    result = {'created': 0, 'deleted': 0, 'kept_human': 0, 'skipped_human': 0,
              'ok': classification.ok, 'error': classification.error}

    if not classification.ok:
        return result

    planned = plan_assignments(classification, max_topics=max_topics)

    with transaction.atomic():
        human_rows = list(requirement.topic_assignments.filter(assignment=RT.HUMAN))
        result['kept_human'] = len(human_rows)
        human_leaves = {(r.topic, r.subcategory) for r in human_rows}
        human_concepts = {taxonomy.normalise_concept(r.model_concept)
                          for r in human_rows if not r.topic}

        deleted, _ = (requirement.topic_assignments
                      .exclude(assignment=RT.HUMAN).delete())
        result['deleted'] = deleted

        to_create = []
        for row in planned:
            if row['topic'] and (row['topic'], row['subcategory']) in human_leaves:
                result['skipped_human'] += 1
                continue
            if (not row['topic'] and
                    taxonomy.normalise_concept(row['model_concept']) in human_concepts):
                result['skipped_human'] += 1
                continue
            to_create.append(RT(
                requirement       = requirement,
                topic             = row['topic'],
                subcategory       = row['subcategory'],
                confidence        = row['confidence'],
                assignment        = row['assignment'],
                model_concept     = row['model_concept'],
                resolution_method = row['resolution_method'],
                evidence          = row['evidence'],
                reason            = row['reason'],
                why_insufficient  = row['why_insufficient'],
                taxonomy_version  = classification.taxonomy_version,
                model_version     = classification.model_version,
                rank              = 0,          # rewritten by _renumber below
            ))
        RT.objects.bulk_create(to_create)
        result['created'] = len(to_create)

        _renumber(requirement)

    sync_topics_mirror(requirement)

    if ingest_suggestions:
        result['suggestions_linked'] = _ingest_suggestions(
            requirement, classification,
            list(requirement.topic_assignments.filter(assignment=RT.SUGGESTED)),
            embed_fn=embed_fn)
    return result


def _renumber(requirement) -> None:
    """Recompute rank across ALL of a requirement's rows, human ones included.

    Done after insertion rather than on the planned rows, because human rows
    are not part of the plan and must still take their place in the ordering.
    """
    rows = list(requirement.topic_assignments.all())
    rows.sort(key=lambda r: _sort_key({
        'assignment':    r.assignment,
        'confidence':    r.confidence,
        'topic':         r.topic,
        'subcategory':   r.subcategory,
        'model_concept': r.model_concept,
    }))
    for i, row in enumerate(rows):
        if row.rank != i:
            row.rank = i
            row.save(update_fields=['rank'])


def classify_and_store(requirement, *, chat=None, embed_fn=None,
                       max_topics: int = MAX_TOPICS, dry_run: bool = True) -> dict:
    """Classify one requirement and, unless dry_run, persist the result."""
    classification = classify_requirement(
        requirement, chat=chat, embed_fn=embed_fn, max_topics=max_topics)
    planned = plan_assignments(classification, max_topics=max_topics) \
        if classification.ok else []

    out = {'requirement': requirement.pk, 'ok': classification.ok,
           'error': classification.error, 'planned': planned}
    if not dry_run:
        out.update(apply_classification(requirement, classification,
                                        max_topics=max_topics,
                                        embed_fn=embed_fn))
    return out


# ── human review actions ────────────────────────────────────────────────────
#
# Every one of these writes `assignment=HUMAN`, which is what makes the
# decision durable: apply_classification() deletes model rows and rebuilds
# them, but never touches a HUMAN row. Provenance is the mechanism — NOT a
# confidence of 1.0, which would be a lie about a measurement and would be
# silently overwritten by the next run anyway.

def add_human_topic(requirement, topic, subcategory='', *, note='',
                    replaces=None):
    """Assign an official topic by hand. Returns the row.

    Validated against the live taxonomy, so a person cannot introduce a tag
    the vocabulary does not contain any more than the model can.
    """
    from apps.library.models import RequirementTopic as RT

    topic = (topic or '').strip()
    subcategory = (subcategory or '').strip()
    if not taxonomy.is_valid(topic, subcategory or None):
        raise ValueError(f'{topic}/{subcategory} is not an official taxonomy leaf')

    row, _created = RT.objects.update_or_create(
        requirement = requirement,
        topic       = topic,
        subcategory = subcategory,
        defaults = {
            'assignment':        RT.HUMAN,
            'resolution_method': RT.HUMAN_M,
            # The model's number does not survive a human decision: it
            # measured the model's certainty, not the reviewer's.
            'confidence':        0.0,
            'evidence':          note[:500],
            'model_concept':     '',
            'taxonomy_version':  taxonomy.TAXONOMY_VERSION,
            'model_version':     '',
            'suggestion':        None,
        },
    )
    if replaces is not None:
        RT.objects.filter(pk=replaces, requirement=requirement).exclude(
            assignment=RT.HUMAN).delete()
    _renumber(requirement)
    sync_topics_mirror(requirement)
    return row


def remove_topic(requirement, assignment_id) -> bool:
    """Remove ONE assignment. The requirement's other topics are untouched.

    Multi-topic means removals are per-assignment: deleting "security" from a
    requirement that is also "retention" must leave retention standing.
    """
    from apps.library.models import RequirementTopic as RT
    deleted, _ = RT.objects.filter(pk=assignment_id,
                                   requirement=requirement).delete()
    if deleted:
        _renumber(requirement)
        sync_topics_mirror(requirement)
    return bool(deleted)


def mark_unclassified(requirement, *, note='') -> int:
    """Record a human judgement that nothing in the taxonomy applies.

    Clears model rows and leaves ONE human-owned unclassified marker, so the
    decision is visible and is not mistaken for a requirement that simply has
    not been classified yet.
    """
    from apps.library.models import RequirementTopic as RT

    removed, _ = requirement.topic_assignments.exclude(
        assignment=RT.HUMAN).delete()
    requirement.topic_assignments.filter(assignment=RT.HUMAN).delete()
    RT.objects.create(
        requirement       = requirement,
        topic             = '',
        subcategory       = '',
        assignment        = RT.HUMAN,
        resolution_method = RT.HUMAN_M,
        model_concept     = '',
        evidence          = note[:500],
        taxonomy_version  = taxonomy.TAXONOMY_VERSION,
        rank              = 0,
    )
    sync_topics_mirror(requirement)
    return removed


def classify_requirements_for_regulation(
        regulation, *, chat=None, embed_fn=None, dry_run: bool = True,
        max_topics: int = MAX_TOPICS, limit: int | None = None,
        on_requirement=None) -> dict:
    """Classify every requirement of one regulation. Dry run by DEFAULT.

    Never raises for a single bad requirement: a failure is counted and the
    pass continues, because one unclassifiable requirement must not cost the
    classification of the rest.
    """
    from apps.library.models import Requirement

    qs = Requirement.objects.filter(regulation=regulation).order_by('pk')
    if limit:
        qs = qs[:limit]
    requirements = list(qs)

    report = {
        'regulation': regulation.name, 'regulation_id': regulation.pk,
        'requirements': len(requirements), 'dry_run': dry_run,
        'classified': 0, 'failed': 0,
        'zero_topic': 0, 'one_topic': 0, 'multi_topic': 0,
        'matched': 0, 'suggested': 0, 'unclassified_concepts': 0,
        'low_confidence': 0, 'created': 0,
        'by_topic': Counter(), 'by_method': Counter(),
        'unresolved_concepts': Counter(),
        'multi_examples': [], 'errors': Counter(),
        'taxonomy_version': taxonomy.TAXONOMY_VERSION,
    }

    for req in requirements:
        try:
            outcome = classify_and_store(
                req, chat=chat, embed_fn=embed_fn,
                max_topics=max_topics, dry_run=dry_run)
        except Exception as exc:
            logger.exception('classification failed for requirement %s', req.pk)
            report['failed'] += 1
            report['errors'][type(exc).__name__] += 1
            continue

        if not outcome['ok']:
            report['failed'] += 1
            report['errors'][outcome['error'][:60] or 'unknown'] += 1
            continue

        report['classified'] += 1
        report['created'] += outcome.get('created', 0)
        planned = outcome['planned']
        official = [r for r in planned if r['assignment'] == 'matched']

        if not official:
            report['zero_topic'] += 1
        elif len(official) == 1:
            report['one_topic'] += 1
        else:
            report['multi_topic'] += 1
            if len(report['multi_examples']) < 12:
                report['multi_examples'].append({
                    'requirement': req.pk,
                    'article_ref': req.article_ref,
                    'text':        (req.text or '')[:150],
                    'topics':      [(r['topic'], r['subcategory'],
                                     round(r['confidence'], 2),
                                     r['resolution_method'])
                                    for r in official],
                })

        for row in planned:
            if row['assignment'] == 'matched':
                report['matched'] += 1
                report['by_topic'][row['topic']] += 1
                report['by_method'][row['resolution_method']] += 1
            elif row['assignment'] == 'suggested':
                report['suggested'] += 1
                report['unresolved_concepts'][
                    taxonomy.normalise_concept(row['model_concept'])] += 1
            elif row['assignment'] == 'unclassified':
                report['unclassified_concepts'] += 1
                if row['confidence'] < taxonomy.MIN_CONCEPT_CONFIDENCE:
                    report['low_confidence'] += 1

        if on_requirement:
            on_requirement(req, outcome)

    return report
