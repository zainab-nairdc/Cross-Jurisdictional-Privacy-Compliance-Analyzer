"""The human-controlled route from a model's unresolved concept to an official topic.

Two jobs, and the hard part of each is refusing to act:

  INTAKE      decide whether an unresolved concept deserves a suggestion at
              all. Most do not. A concept reaches here only after
              resolve_concept() has already failed against the official
              vocabulary and its aliases, and intake then checks it against
              every open suggestion before creating anything. Without that,
              "storage limitation", "data retention" and "data storage period"
              become three proposals for a topic the taxonomy already has.

  LIFECYCLE   move a suggestion through review WITHOUT ever making it official.
              Nothing in this module writes to reasoning/taxonomy.py. Approval
              produces a PATCH — the exact source change a person would have to
              commit — and stops. `mark_active()` then refuses unless that
              change has actually landed, so the database can never claim a
              topic is official when the source file says otherwise.

The asymmetry is deliberate. Creating a suggestion is cheap and reversible;
adding an official topic is neither, because every classification stamped with
a taxonomy version depends on that vocabulary being stable.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parents[3]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from reasoning import taxonomy                                    # noqa: E402

logger = logging.getLogger(__name__)


# How many independent observations before a suggestion is treated as
# high-signal in the review queue. Configurable rather than hard-coded because
# it is a product judgement, not a fact — and because the 7B model has been
# measured producing different proposals on identical input, so a single
# occurrence is noise.
#
# Reaching the threshold does NOT promote anything. It changes the ORDER of the
# review queue and nothing else; a human still approves every topic.
DEFAULT_OCCURRENCE_THRESHOLD = 8


def occurrence_threshold() -> int:
    from django.conf import settings
    return int(getattr(settings, 'TOPIC_SUGGESTION_THRESHOLD',
                       DEFAULT_OCCURRENCE_THRESHOLD))


# Words a model returns when it is naming the KIND of text in front of it
# rather than a compliance topic. "definition" was observed in the Phase 2 dry
# run being proposed as a new official topic; it is a structural label, and a
# taxonomy of them would be useless. Distinct from taxonomy's no-fit tokens,
# which are the model explicitly declining.
_STRUCTURAL_ARTEFACTS = frozenset({
    'definition', 'definitions', 'requirement', 'requirements', 'provision',
    'provisions', 'regulation', 'regulations', 'law', 'laws', 'act', 'article',
    'articles', 'section', 'sections', 'clause', 'clauses', 'paragraph',
    'schedule', 'preamble', 'scope', 'general', 'general provisions',
    'introduction', 'purpose', 'title', 'commencement', 'interpretation',
    'obligation', 'obligations', 'rule', 'rules', 'policy', 'compliance',
})


def slugify_concept(name: str) -> str:
    """'Automated Decision-Making' -> 'automated_decision_making'.

    The same shape as the tags already in TAXONOMY, so a generated patch drops
    into the source file without a human having to rename anything.
    """
    norm = taxonomy.normalise_concept(name)
    return re.sub(r'\s+', '_', norm).strip('_')[:64]


def is_structural_artefact(concept: str) -> bool:
    """Is this the model naming a kind of text rather than a compliance topic?"""
    return taxonomy.normalise_concept(concept) in _STRUCTURAL_ARTEFACTS


# ── intake ──────────────────────────────────────────────────────────────────

def should_suggest(resolution) -> tuple[bool, str]:
    """May this ConceptResolution become a TopicSuggestion? Plus the reason.

    Every gate here is a refusal, and each one exists because letting it
    through produces taxonomy spam:

      - already matched      the taxonomy covers it. Not a gap.
      - explicit no-fit      the model declined. Not a concept.
      - below the floor      a guess. Not evidence of anything.
      - structural artefact  "definition" is a kind of text, not a topic.
      - too short/long       not a topic name.
    """
    if resolution is None:
        return False, 'no resolution'
    if resolution.is_matched:
        return False, f'already covered by official topic {resolution.leaf}'
    if resolution.status == taxonomy.UNCLASSIFIED:
        return False, 'model reported no meaningful topic'
    if taxonomy.is_no_fit(resolution.concept):
        return False, 'no-fit token, not a concept'
    if resolution.confidence < taxonomy.MIN_CONCEPT_CONFIDENCE:
        return False, (f'confidence {resolution.confidence:.2f} below floor '
                       f'{taxonomy.MIN_CONCEPT_CONFIDENCE}')
    if is_structural_artefact(resolution.concept):
        return False, 'structural artefact, not a compliance topic'
    norm = taxonomy.normalise_concept(resolution.concept)
    if len(norm) < 3:
        return False, 'concept too short to be a topic name'
    if len(norm) > 120:
        return False, 'concept too long to be a topic name'
    return True, ''


def find_matching_suggestion(concept: str, *, embed_fn=None):
    """An OPEN suggestion this concept already belongs to, or None.

    The dedup ladder, cheapest first:
      1. exact slug
      2. exact stored model_concept on any evidence row
      3. normalised name equality against proposed_name
      4. semantic similarity against open proposals, when an embedder is
         supplied and it clears the same threshold+margin gate resolve_concept
         uses — so this is never fuzzier than official matching is.

    Returns None rather than guessing when two suggestions match equally well:
    merging the wrong pair is harder to undo than leaving two open.
    """
    from apps.library.models import TopicSuggestion as TS

    norm = taxonomy.normalise_concept(concept)
    if not norm:
        return None
    slug = slugify_concept(concept)
    open_qs = TS.objects.filter(status__in=TS.OPEN_STATUSES)

    hit = open_qs.filter(proposed_slug=slug).first()
    if hit:
        return hit

    hit = open_qs.filter(evidence__model_concept__iexact=concept).first()
    if hit:
        return hit

    for candidate in open_qs:
        if taxonomy.normalise_concept(candidate.proposed_name) == norm:
            return candidate

    if embed_fn is None:
        return None

    candidates = list(open_qs)
    if not candidates:
        return None
    try:
        vectors = embed_fn([concept] + [c.proposed_name for c in candidates])
    except Exception:
        logger.warning('suggestion dedup: embedder unavailable', exc_info=True)
        return None
    probe, rest = vectors[0], vectors[1:]
    scored = sorted(
        ((taxonomy._cosine(probe, v), c) for v, c in zip(rest, candidates)),
        key=lambda x: x[0], reverse=True)
    if not scored:
        return None
    best, winner = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best >= taxonomy.SEMANTIC_MATCH_THRESHOLD and \
            (best - runner_up) >= taxonomy.SEMANTIC_MATCH_MARGIN:
        return winner
    return None


def _similar_topics_for(resolution) -> list[dict]:
    """Near-miss official topics, shaped for the review UI.

    Shown so "this is really an existing topic" is the easiest call a reviewer
    can make — which, on the Phase 2 evidence, is the correct call most of the
    time.
    """
    out = []
    for entry in (resolution.candidates or ())[:5]:
        if len(entry) == 3 and isinstance(entry[2], (int, float)):
            topic, sub, score = entry
        elif len(entry) >= 2:
            topic, sub, score = entry[0], entry[1], None
        else:
            continue
        out.append({
            'topic': topic, 'subcategory': sub or '',
            'score': round(float(score), 4) if score is not None else None,
            'label': taxonomy.topic_label(topic),
        })
    return out


def ingest_unresolved(resolution, *, requirement=None, evidence_quote='',
                      reason='', why_insufficient='', chunk_node_id='',
                      embed_fn=None):
    """Fold one unresolved concept into the review queue. Returns (suggestion, created).

    Returns (None, False) whenever `should_suggest` refuses — which is the
    common case and not an error.

    When an open suggestion already covers the concept, this attaches evidence
    to THAT suggestion instead of creating a second one. Evidence is unique per
    (suggestion, requirement, wording), so re-running classification refreshes
    rather than inflating `occurrence_count`.
    """
    from django.db import IntegrityError, transaction
    from apps.library.models import (
        TopicSuggestion as TS, TopicSuggestionEvidence as TSE,
    )

    ok, _why = should_suggest(resolution)
    if not ok:
        return None, False

    concept = resolution.concept.strip()
    with transaction.atomic():
        suggestion = find_matching_suggestion(concept, embed_fn=embed_fn)
        created = False
        if suggestion is None:
            try:
                with transaction.atomic():
                    suggestion = TS.objects.create(
                        proposed_name  = concept[:120],
                        proposed_slug  = slugify_concept(concept),
                        reason         = reason,
                        why_existing_insufficient = why_insufficient,
                        confidence     = resolution.confidence,
                        similar_topics = _similar_topics_for(resolution),
                        origin         = TS.MODEL,
                        taxonomy_version_at_suggestion = taxonomy.TAXONOMY_VERSION,
                    )
                    created = True
            except IntegrityError:
                # Lost a race on the open-slug constraint. The other writer's
                # row is the right home for this evidence.
                suggestion = TS.objects.filter(
                    proposed_slug=slugify_concept(concept),
                    status__in=TS.OPEN_STATUSES).first()
                if suggestion is None:
                    return None, False

        TSE.objects.update_or_create(
            suggestion    = suggestion,
            requirement   = requirement,
            model_concept = concept[:200],
            defaults = {
                'quote':            (evidence_quote or '')[:4000],
                'confidence':       resolution.confidence,
                'chunk_node_id':    chunk_node_id[:64],
                'taxonomy_version': taxonomy.TAXONOMY_VERSION,
            },
        )
        _refresh_counts(suggestion)
        if not created and reason and not suggestion.reason:
            suggestion.reason = reason
            suggestion.save(update_fields=['reason'])
        if not created and why_insufficient and not suggestion.why_existing_insufficient:
            suggestion.why_existing_insufficient = why_insufficient
            suggestion.save(update_fields=['why_existing_insufficient'])

    return suggestion, created


def _refresh_counts(suggestion) -> None:
    """Recompute occurrence_count and confidence from the evidence rows.

    Confidence is the MAXIMUM observed, not a mean: one strong observation is
    better grounds than a crowd of weak ones, and averaging would let repeated
    low-confidence noise drag a real signal down.
    """
    from django.db.models import Count, Max
    agg = suggestion.evidence.aggregate(n=Count('id'), best=Max('confidence'))
    suggestion.occurrence_count = agg['n'] or 0
    suggestion.confidence = agg['best'] or 0.0
    suggestion.save(update_fields=['occurrence_count', 'confidence', 'updated_at'])


# ── manual creation ─────────────────────────────────────────────────────────

def create_manual_suggestion(*, name, parent_topic='', subcategory='',
                             reason='', why_insufficient='', reviewer=None):
    """A person proposing a topic directly, with no model involved.

    The taxonomy is not owned by the model, so a human must be able to start
    the process. The SAME approval and release boundary applies: a manually
    created suggestion is still only a suggestion, and still becomes official
    only when someone commits the source change.

    Raises ValueError on input the taxonomy could not accept, so bad proposals
    fail at creation rather than at release time.
    """
    from apps.library.models import TopicSuggestion as TS

    clean = (name or '').strip()
    if not clean:
        raise ValueError('a topic name is required')
    slug = slugify_concept(clean)
    if not slug:
        raise ValueError(f'{clean!r} does not produce a usable topic tag')

    parent = (parent_topic or '').strip()
    if parent and parent not in taxonomy.TAXONOMY:
        raise ValueError(f'{parent!r} is not an official topic')

    sub = slugify_concept(subcategory) if subcategory else ''
    if parent:
        # Proposing a new subcategory under an existing topic.
        if taxonomy.is_valid(parent, sub or slug):
            raise ValueError(
                f'{parent}/{sub or slug} already exists in the official taxonomy')
    elif slug in taxonomy.TAXONOMY:
        raise ValueError(f'{slug!r} already exists in the official taxonomy')

    existing = TS.objects.filter(proposed_slug=slug,
                                 status__in=TS.OPEN_STATUSES).first()
    if existing:
        raise ValueError(
            f'an open suggestion for {slug!r} already exists (#{existing.pk})')

    return TS.objects.create(
        proposed_name        = clean[:120],
        proposed_slug        = slug,
        proposed_subcategory = sub,
        parent_topic         = parent,
        reason               = reason,
        why_existing_insufficient = why_insufficient,
        origin               = TS.HUMAN,
        reviewer             = reviewer,
        confidence           = 1.0,
        taxonomy_version_at_suggestion = taxonomy.TAXONOMY_VERSION,
    )


# ── patch generation ────────────────────────────────────────────────────────

def _proposed_labels(suggestion) -> tuple[list[str], dict]:
    """The leaves this suggestion adds, plus the labels the patch will write.

    Labels are part of the v2 fingerprint, so a prediction that omitted them
    would not match the file once the change is applied. Kept in ONE place so
    the patch text and the predicted version cannot drift apart.
    """
    slug   = suggestion.proposed_slug
    parent = suggestion.parent_topic
    sub    = suggestion.proposed_subcategory
    name   = suggestion.proposed_name

    if parent:
        leaf = f'{parent}/{sub or slug}'
        return [leaf], {leaf: name}

    if sub:
        leaf = f'{slug}/{sub}'
        return [leaf], {slug: name, leaf: sub.replace('_', ' ').capitalize()}

    # A top-level topic with no subcategories yet. Representable since the v2
    # fingerprint hashes topics as well as leaves — under v1 this would not
    # have changed the version at all, which is why the old patch template had
    # to invent a "general" subcategory to force a change.
    return [slug], {slug: name}


def predicted_version(suggestion) -> str:
    """The TAXONOMY_VERSION this suggestion's change would produce."""
    leaves, labels = _proposed_labels(suggestion)
    return taxonomy.fingerprint_with(leaves, labels=labels)


def build_patch(suggestion) -> str:
    """The exact source change a human would commit to make this official.

    GENERATED AND RETURNED. Nothing writes it. The file stays human-edited
    because that is the control point the whole design rests on: a taxonomy
    change alters the fingerprint, and the fingerprint decides which stored
    classifications are still valid across the entire corpus.

    Covers the three places a topic has to be registered: TAXONOMY, ALIASES
    (so the wordings already observed resolve to it instead of coming back as
    fresh suggestions), and TAXONOMY_LINEAGE (so consumers can tell an
    additive change from an invalidating one).
    """
    from apps.library.models import TopicSuggestion as TS

    name = suggestion.proposed_name
    slug = suggestion.proposed_slug
    parent = suggestion.parent_topic
    sub = suggestion.proposed_subcategory or slug
    leaf = suggestion.target_leaf
    new_version = predicted_version(suggestion)

    # Wordings already observed for this concept become aliases, so the same
    # phrasing never re-enters the queue after the topic exists.
    wordings = sorted({
        taxonomy.normalise_concept(c) for c in
        suggestion.evidence.values_list('model_concept', flat=True) if c
    } | {taxonomy.normalise_concept(name)})
    wordings = [w for w in wordings if w and w != slug.replace('_', ' ')]

    lines: list[str] = []
    lines.append('# ' + '=' * 70)
    lines.append(f'# PROPOSED TAXONOMY CHANGE — suggestion #{suggestion.pk}')
    lines.append('# ' + '=' * 70)
    lines.append('#')
    lines.append('# Review and apply BY HAND to reasoning/taxonomy.py, then commit.')
    lines.append('# Nothing in the application writes this file.')
    lines.append('#')
    lines.append(f'# Origin      : {suggestion.get_origin_display()}')
    lines.append(f'# Occurrences : {suggestion.occurrence_count}')
    lines.append(f'# Taxonomy at suggestion time : '
                 f'{suggestion.taxonomy_version_at_suggestion or "unknown"}')
    lines.append(f'# Taxonomy now                : {taxonomy.TAXONOMY_VERSION}')
    lines.append(f'# Taxonomy AFTER this change  : {new_version}')
    lines.append('#')
    if suggestion.reason:
        lines.append(f'# Reason: {suggestion.reason[:300]}')
    if suggestion.why_existing_insufficient:
        lines.append('# Why existing topics are insufficient: '
                     f'{suggestion.why_existing_insufficient[:300]}')
    lines.append('')

    if parent:
        lines.append(f'# --- 1. Add a subcategory under the existing "{parent}" topic ---')
        lines.append(f'#     In TAXONOMY["{parent}"]["subcategories"], add:')
        lines.append('')
        lines.append(f'    "{sub}": "{name}",')
    else:
        lines.append('# --- 1. Add a new top-level topic to TAXONOMY ---')
        lines.append('')
        lines.append(f'    "{slug}": {{')
        lines.append(f'        "label": "{name}",')
        if suggestion.proposed_subcategory:
            lines.append('        "subcategories": {')
            lines.append(f'            "{suggestion.proposed_subcategory}": '
                         f'"{suggestion.proposed_subcategory.replace("_", " ").capitalize()}",')
            lines.append('        },')
        else:
            lines.append('        # Subcategories are optional. The fingerprint hashes')
            lines.append('        # topics as well as leaves, so adding this topic changes')
            lines.append('        # TAXONOMY_VERSION on its own — no placeholder needed.')
            lines.append('        "subcategories": {},')
        lines.append('    },')

    lines.append('')
    lines.append('# --- 2. Add ALIASES for the wordings already observed ---')
    lines.append('#     Without these the same phrasings return as new suggestions.')
    lines.append('')
    if wordings:
        for w in wordings:
            lines.append(f'    "{w}": "{leaf}",')
    else:
        lines.append('    # (no additional wordings observed)')

    lines.append('')
    lines.append('# --- 3. Append a TAXONOMY_LINEAGE entry ---')
    lines.append('#     ADDITIVE: existing tags stay valid but become incomplete,')
    lines.append('#     so re-classification can be scheduled rather than forced.')
    lines.append('')
    lines.append('    {')
    lines.append(f'        "version": "{new_version}",')
    lines.append('        "change":  LINEAGE_ADDITIVE,')
    lines.append('        "date":    "<YYYY-MM-DD>",')
    lines.append(f'        "added":   ["{leaf}"],')
    lines.append('        "removed": [],')
    plural = '' if suggestion.occurrence_count == 1 else 's'
    lines.append(f'        "note":    "Added {name!r} after review of suggestion '
                 f'#{suggestion.pk} ({suggestion.occurrence_count} '
                 f'observation{plural}).",')
    lines.append('    },')
    lines.append('')
    lines.append('# --- 4. After committing, mark the suggestion active ---')
    lines.append(f'#     manage.py taxonomy_apply {suggestion.pk} --mark-active')
    lines.append('#     (it verifies the topic really is in TAXONOMY first)')
    return '\n'.join(lines)


# ── lifecycle ───────────────────────────────────────────────────────────────

def _stamp(suggestion, reviewer, note):
    from django.utils import timezone
    suggestion.reviewer = reviewer
    suggestion.reviewed_at = timezone.now()
    if note:
        suggestion.reviewer_note = note


def start_review(suggestion, *, reviewer=None, note=''):
    from apps.library.models import TopicSuggestion as TS
    if suggestion.status not in (TS.SUGGESTED, TS.UNDER_REVIEW):
        raise ValueError(f'cannot review a {suggestion.status} suggestion')
    suggestion.status = TS.UNDER_REVIEW
    _stamp(suggestion, reviewer, note)
    suggestion.save()
    return suggestion


def approve(suggestion, *, reviewer=None, note='', name=None,
            parent_topic=None, subcategory=None):
    """Approve as a genuinely new topic — moves to APPROVED_PENDING_RELEASE.

    This does NOT make the topic official, and the status name says so. It
    records a human decision and generates the patch. Officialdom requires
    someone to commit that patch; `mark_active` is what confirms they did.

    The reviewer may edit the proposal on the way through — the model's naming
    is a starting point, not a specification.
    """
    from apps.library.models import TopicSuggestion as TS

    if suggestion.status in TS.TERMINAL_STATUSES:
        raise ValueError(f'cannot approve a {suggestion.status} suggestion')

    if name is not None:
        clean = name.strip()
        if not clean:
            raise ValueError('a topic name is required')
        suggestion.proposed_name = clean[:120]
        suggestion.proposed_slug = slugify_concept(clean)
    if parent_topic is not None:
        parent = parent_topic.strip()
        if parent and parent not in taxonomy.TAXONOMY:
            raise ValueError(f'{parent!r} is not an official topic')
        suggestion.parent_topic = parent
    if subcategory is not None:
        suggestion.proposed_subcategory = slugify_concept(subcategory) if subcategory else ''

    # Approving something the taxonomy ALREADY has would produce a patch that
    # duplicates an existing leaf. That is a merge, not an approval.
    if taxonomy.is_valid(suggestion.parent_topic or suggestion.proposed_slug,
                         suggestion.proposed_subcategory or None):
        raise ValueError(
            f'{suggestion.target_leaf} already exists in the official taxonomy — '
            f'merge into it instead of approving it as new')

    suggestion.status = TS.APPROVED_PENDING_RELEASE
    suggestion.expected_taxonomy_version = predicted_version(suggestion)
    _stamp(suggestion, reviewer, note)
    suggestion.save()
    # Built after the edits so the patch reflects what was actually approved.
    suggestion.proposed_patch = build_patch(suggestion)
    suggestion.save(update_fields=['proposed_patch'])
    return suggestion


def reject(suggestion, *, reviewer=None, note=''):
    from apps.library.models import TopicSuggestion as TS
    if suggestion.status == TS.ACTIVE:
        raise ValueError('cannot reject a topic that is already official')
    suggestion.status = TS.REJECTED
    _stamp(suggestion, reviewer, note)
    suggestion.save()
    _detach_assignments(suggestion)
    return suggestion


def merge_into_topic(suggestion, topic, subcategory='', *, reviewer=None, note=''):
    """Resolve a suggestion as "this is really an existing official topic".

    The outcome we expect most often, and on the Phase 2 evidence the correct
    one five times out of six. Every requirement that raised the concept is
    re-pointed at the official topic as a HUMAN assignment, so the reviewer's
    judgement is recorded where the data is actually read — and survives
    reclassification.
    """
    from apps.library.models import RequirementTopic as RT, TopicSuggestion as TS

    if suggestion.status == TS.ACTIVE:
        raise ValueError('cannot merge a topic that is already official')
    if not taxonomy.is_valid(topic, subcategory or None):
        raise ValueError(f'{topic}/{subcategory} is not an official taxonomy leaf')

    suggestion.status = TS.MERGED
    suggestion.merged_into_topic = topic
    suggestion.merged_into_subcategory = subcategory or ''
    _stamp(suggestion, reviewer, note)
    suggestion.save()

    converted = 0
    for row in list(suggestion.assignments.filter(assignment=RT.SUGGESTED)):
        already = RT.objects.filter(requirement=row.requirement, topic=topic,
                                    subcategory=subcategory or '').exists()
        if already:
            row.delete()
            continue
        row.topic             = topic
        row.subcategory       = subcategory or ''
        row.assignment        = RT.HUMAN
        row.resolution_method = RT.HUMAN_M
        row.suggestion        = None
        row.save(update_fields=['topic', 'subcategory', 'assignment',
                                'resolution_method', 'suggestion', 'updated_at'])
        converted += 1
        _resync(row.requirement)
    return suggestion, converted


def merge_into_suggestion(suggestion, target, *, reviewer=None, note=''):
    """Fold one proposal into another — two wordings for the same idea."""
    from apps.library.models import TopicSuggestion as TS

    if suggestion.pk == getattr(target, 'pk', None):
        raise ValueError('cannot merge a suggestion into itself')
    if suggestion.status == TS.ACTIVE:
        raise ValueError('cannot merge a topic that is already official')
    if target.status in (TS.REJECTED, TS.MERGED, TS.SUPERSEDED):
        raise ValueError(f'cannot merge into a {target.status} suggestion')

    for ev in list(suggestion.evidence.all()):
        exists = target.evidence.filter(
            requirement=ev.requirement, model_concept=ev.model_concept).exists()
        if exists:
            ev.delete()
        else:
            ev.suggestion = target
            ev.save(update_fields=['suggestion'])
    suggestion.assignments.update(suggestion=target)

    suggestion.status = TS.MERGED
    suggestion.merged_into_suggestion = target
    _stamp(suggestion, reviewer, note)
    suggestion.save()
    _refresh_counts(target)
    return suggestion, target


def mark_active(suggestion, *, reviewer=None, note=''):
    """Confirm the approved change actually landed in reasoning/taxonomy.py.

    THE RELEASE GATE. It reads the live taxonomy and REFUSES if the topic is
    not there. That refusal is what makes `active` trustworthy: the status
    cannot claim officialdom the source file does not back, and no automatic
    path exists from approved_pending_release to active.
    """
    from apps.library.models import TopicSuggestion as TS

    if suggestion.status != TS.APPROVED_PENDING_RELEASE:
        raise ValueError(
            f'only an approved_pending_release suggestion can become active '
            f'(this one is {suggestion.status})')

    topic = suggestion.parent_topic or suggestion.proposed_slug
    sub   = suggestion.proposed_subcategory or None
    if suggestion.parent_topic:
        sub = suggestion.proposed_subcategory or suggestion.proposed_slug
    if not taxonomy.is_valid(topic, sub):
        raise ValueError(
            f'{suggestion.target_leaf!r} is not in the official taxonomy yet. '
            f'Apply the proposed patch to reasoning/taxonomy.py and commit it '
            f'first — this command confirms a release, it does not perform one.')

    suggestion.status = TS.ACTIVE
    _stamp(suggestion, reviewer, note)
    suggestion.save()
    return suggestion


def _detach_assignments(suggestion) -> None:
    """Unlink a dead suggestion from the rows that raised it.

    The RequirementTopic rows stay: the model DID raise that concept about
    that requirement, and rejecting the proposal does not un-happen it. Only
    the pointer goes.
    """
    suggestion.assignments.update(suggestion=None)


def _resync(requirement) -> None:
    from apps.library.topics import sync_topics_mirror
    if requirement is not None:
        sync_topics_mirror(requirement)


def queue(status=None, *, threshold=None):
    """Suggestions for the review queue, high-signal first.

    Ordered by occurrence count then confidence, because a concept observed
    across many provisions is worth a reviewer's time before a one-off — the
    7B model has been measured proposing different concepts on identical
    input, so a single occurrence is weak evidence.

    Ordering only. Nothing is promoted, hidden, or auto-approved by count.
    """
    from apps.library.models import TopicSuggestion as TS
    qs = TS.objects.all()
    if status:
        qs = qs.filter(status=status)
    return qs.order_by('-occurrence_count', '-confidence', 'proposed_name')
