"""Phase 3 review UI — requirements, their topics, references, and suggestions.

Kept in its own module rather than appended to library/views.py, which is
already ~1500 lines and owns document upload/ingestion. Nothing here touches
that flow.

Two surfaces:

  REQUIREMENT REVIEW  a requirement with ALL its topics (plural is the point),
                      its cross-references with their real resolution state,
                      and the actions to correct any of it.

  SUGGESTION QUEUE    proposed taxonomy additions awaiting human judgement,
                      high-signal first, with the evidence that produced them.

Every write goes through apps.library.topics or apps.library.suggestions. No
view mutates a model directly, and — the property this phase exists to
guarantee — no view writes reasoning/taxonomy.py.
"""

from __future__ import annotations

from django.contrib import messages
from django.db.models import Count, Prefetch
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.accounts.decorators import role_required
from apps.library.models import (
    Document, Requirement, RequirementReference, RequirementTopic,
    TopicSuggestion, TopicSuggestionEvidence,
)
from apps.library import suggestions as sug
from apps.library import topics as topic_service
from reasoning import taxonomy

ALL_ROLES = ('analyst', 'reviewer', 'admin')


def _taxonomy_options():
    """Every official leaf, for the reviewer's pickers.

    Built from TAXONOMY at request time, so the pickers grow the moment a new
    topic is released. Nothing here assumes twelve of anything.
    """
    out = []
    for tag, label in taxonomy.all_topics():
        out.append({'value': tag, 'label': label, 'topic': tag,
                    'subcategory': '', 'depth': 0})
        for sub_tag, sub_label in taxonomy.all_subcategories(tag):
            out.append({'value': f'{tag}/{sub_tag}', 'label': sub_label,
                        'topic': tag, 'subcategory': sub_tag, 'depth': 1})
    return out


def _split_leaf(value: str) -> tuple[str, str]:
    topic, _, sub = (value or '').partition('/')
    return topic.strip(), sub.strip()


# ══════════════════════════════════════════════════════════════════════════
# Requirements
# ══════════════════════════════════════════════════════════════════════════

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RequirementListView(View):
    """GET /library/requirements/ — every extracted requirement, filterable."""

    def get(self, request):
        qs = (Requirement.objects
              .select_related('regulation')
              .prefetch_related('topic_assignments', 'references')
              .order_by('regulation__name', 'article_ref', 'pk'))

        reg = request.GET.get('regulation', '')
        if reg:
            qs = qs.filter(regulation_id=reg)
        topic = request.GET.get('topic', '')
        if topic:
            qs = qs.filter(topic_assignments__topic=topic).distinct()
        state = request.GET.get('state', '')
        if state == 'untopiced':
            qs = qs.exclude(topic_assignments__assignment__in=
                            RequirementTopic.OFFICIAL_ASSIGNMENTS)
        elif state == 'multi':
            qs = (qs.annotate(n=Count('topic_assignments'))
                  .filter(topic_assignments__assignment=RequirementTopic.MATCHED)
                  .annotate(n_official=Count('topic_assignments'))
                  .filter(n_official__gt=1).distinct())
        elif state == 'suggested':
            qs = qs.filter(
                topic_assignments__assignment=RequirementTopic.SUGGESTED).distinct()
        elif state == 'refs':
            qs = qs.filter(references__isnull=False).distinct()

        requirements = list(qs[:400])
        return render(request, 'pages/requirements.html', {
            'requirements': requirements,
            'regulations': Document.objects.filter(doc_type=Document.REGULATION)
                                   .annotate(n=Count('requirements'))
                                   .filter(n__gt=0).order_by('name'),
            'topic_options': _taxonomy_options(),
            'selected': {'regulation': reg, 'topic': topic, 'state': state},
            'open_suggestions': TopicSuggestion.objects.filter(
                status__in=TopicSuggestion.OPEN_STATUSES).count(),
            'taxonomy_version': taxonomy.TAXONOMY_VERSION,
        })


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RequirementDetailView(View):
    """GET /library/requirements/<pk>/ — one requirement, reviewable."""

    def get(self, request, pk):
        requirement = get_object_or_404(
            Requirement.objects.select_related('regulation')
            .prefetch_related(
                Prefetch('topic_assignments',
                         queryset=RequirementTopic.objects
                         .select_related('suggestion').order_by('rank', 'id')),
                Prefetch('references',
                         queryset=RequirementReference.objects
                         .select_related('target_document').order_by('id'))),
            pk=pk)

        assignments = list(requirement.topic_assignments.all())
        references = list(requirement.references.all())

        # Candidate node ids are stored raw; resolve them to the article label
        # a reviewer can actually read. Read from the STORED provision record,
        # never echoed from model output — the same anti-fabrication rule the
        # coverage UI follows.
        for ref in references:
            ref.candidate_details = _describe_candidates(ref)

        return render(request, 'pages/requirement_detail.html', {
            'requirement':   requirement,
            'assignments':   assignments,
            'official':      [a for a in assignments if a.is_official],
            'suggested':     [a for a in assignments
                              if a.assignment == RequirementTopic.SUGGESTED],
            'unclassified':  [a for a in assignments
                              if a.assignment == RequirementTopic.UNCLASSIFIED],
            'references':    references,
            'topic_options': _taxonomy_options(),
            'taxonomy_version': taxonomy.TAXONOMY_VERSION,
        })


def _describe_candidates(ref) -> list[dict]:
    """Turn candidate node ids into readable provision labels.

    An ambiguous reference lists every valid target and names none of them as
    THE target — collapsing them to one is exactly the false traceability
    Phase 1 refuses to create.
    """
    from retrieval.bm25_store import get_chunk_provision
    out = []
    for node_id in (ref.candidates or [])[:25]:
        provision = None
        try:
            provision = get_chunk_provision(node_id)
        except Exception:
            provision = None
        out.append({
            'node_id': node_id,
            'article_ref': (provision or {}).get('article_ref', ''),
            'doc_title': (provision or {}).get('doc_title', ''),
            'grounded': provision is not None,
        })
    return out


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RequirementTopicActionView(View):
    """POST /library/requirements/<pk>/topics/ — reviewer edits to topics.

    Every action records provenance as `assignment=human`, which is what makes
    it survive the next automated classification run.
    """

    def post(self, request, pk):
        requirement = get_object_or_404(Requirement, pk=pk)
        action = request.POST.get('action', '')
        note = (request.POST.get('note') or '').strip()

        try:
            if action == 'add':
                topic, sub = _split_leaf(request.POST.get('leaf', ''))
                topic_service.add_human_topic(requirement, topic, sub, note=note)
                messages.success(request, f'Added {topic}{"/" + sub if sub else ""}.')

            elif action == 'replace':
                topic, sub = _split_leaf(request.POST.get('leaf', ''))
                topic_service.add_human_topic(
                    requirement, topic, sub, note=note,
                    replaces=request.POST.get('assignment_id') or None)
                messages.success(request, 'Topic corrected.')

            elif action == 'remove':
                removed = topic_service.remove_topic(
                    requirement, request.POST.get('assignment_id'))
                messages.success(request, 'Topic removed.' if removed
                                 else 'That assignment no longer exists.')

            elif action == 'unclassified':
                topic_service.mark_unclassified(requirement, note=note)
                messages.success(request, 'Marked as having no applicable topic.')

            else:
                return HttpResponseBadRequest('Unknown action')

        except ValueError as exc:
            messages.error(request, str(exc))

        return redirect('library-requirement-detail', pk=pk)


# ══════════════════════════════════════════════════════════════════════════
# Topic suggestions
# ══════════════════════════════════════════════════════════════════════════

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class TopicSuggestionQueueView(View):
    """GET /library/topic-suggestions/ — proposed taxonomy additions."""

    def get(self, request):
        status = request.GET.get('status', '')
        rows = list(sug.queue(status or None)
                    .prefetch_related('evidence')[:200])
        threshold = sug.occurrence_threshold()
        for row in rows:
            row.is_high_signal = row.occurrence_count >= threshold

        counts = {s: TopicSuggestion.objects.filter(status=s).count()
                  for s, _ in TopicSuggestion.STATUS_CHOICES}
        return render(request, 'pages/topic_suggestions.html', {
            'suggestions': rows,
            'selected_status': status,
            'counts': counts,
            'total': TopicSuggestion.objects.count(),
            'threshold': threshold,
            'topic_options': _taxonomy_options(),
            'taxonomy_version': taxonomy.TAXONOMY_VERSION,
            'official_topic_count': len(taxonomy.TAXONOMY),
            'status_choices': TopicSuggestion.STATUS_CHOICES,
            'pending_release': TopicSuggestion.objects.filter(
                status=TopicSuggestion.APPROVED_PENDING_RELEASE).count(),
        })


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class TopicSuggestionDetailView(View):
    """GET /library/topic-suggestions/<pk>/ — the evidence and the decision."""

    def get(self, request, pk):
        suggestion = get_object_or_404(
            TopicSuggestion.objects.prefetch_related(
                Prefetch('evidence',
                         queryset=TopicSuggestionEvidence.objects
                         .select_related('requirement',
                                         'requirement__regulation'))),
            pk=pk)
        patch = suggestion.proposed_patch
        if suggestion.status == TopicSuggestion.APPROVED_PENDING_RELEASE and not patch:
            patch = sug.build_patch(suggestion)

        return render(request, 'pages/topic_suggestion_detail.html', {
            'suggestion': suggestion,
            'evidence': list(suggestion.evidence.all()),
            'patch': patch,
            'topic_options': _taxonomy_options(),
            'other_open': TopicSuggestion.objects.filter(
                status__in=TopicSuggestion.OPEN_STATUSES).exclude(pk=pk),
            'threshold': sug.occurrence_threshold(),
            'taxonomy_version': taxonomy.TAXONOMY_VERSION,
            'is_in_taxonomy': taxonomy.is_valid(
                suggestion.parent_topic or suggestion.proposed_slug,
                suggestion.proposed_subcategory or None),
        })


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class TopicSuggestionActionView(View):
    """POST /library/topic-suggestions/<pk>/action/ — the review decision.

    `approve` moves to APPROVED_PENDING_RELEASE and generates a patch. It does
    NOT make the topic official and does not touch reasoning/taxonomy.py —
    `mark_active` is the only path to `active`, and it verifies the source file
    before allowing it.
    """

    def post(self, request, pk):
        suggestion = get_object_or_404(TopicSuggestion, pk=pk)
        action = request.POST.get('action', '')
        note = (request.POST.get('note') or '').strip()
        reviewer = request.user if request.user.is_authenticated else None

        try:
            if action == 'start_review':
                sug.start_review(suggestion, reviewer=reviewer, note=note)
                messages.success(request, 'Marked under review.')

            elif action == 'approve':
                sug.approve(
                    suggestion, reviewer=reviewer, note=note,
                    name=request.POST.get('name') or None,
                    parent_topic=request.POST.get('parent_topic'),
                    subcategory=request.POST.get('subcategory'))
                messages.success(
                    request,
                    'Approved — pending taxonomy release. The topic is NOT '
                    'official yet: apply the generated change to '
                    'reasoning/taxonomy.py and commit it first.')

            elif action == 'reject':
                sug.reject(suggestion, reviewer=reviewer, note=note)
                messages.success(request, 'Rejected.')

            elif action == 'merge_topic':
                topic, subcat = _split_leaf(request.POST.get('leaf', ''))
                _, converted = sug.merge_into_topic(
                    suggestion, topic, subcat, reviewer=reviewer, note=note)
                messages.success(
                    request,
                    f'Merged into {topic}{"/" + subcat if subcat else ""}; '
                    f'{converted} requirement assignment(s) re-pointed.')

            elif action == 'merge_suggestion':
                target = get_object_or_404(
                    TopicSuggestion, pk=request.POST.get('target_id'))
                sug.merge_into_suggestion(
                    suggestion, target, reviewer=reviewer, note=note)
                messages.success(request,
                                 f'Merged into #{target.pk} {target.proposed_name}.')

            elif action == 'mark_active':
                sug.mark_active(suggestion, reviewer=reviewer, note=note)
                messages.success(
                    request, 'Confirmed — the topic is now in the official '
                             'taxonomy and the suggestion is active.')

            else:
                return HttpResponseBadRequest('Unknown action')

        except ValueError as exc:
            messages.error(request, str(exc))

        return redirect('library-topic-suggestion-detail', pk=pk)


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class TopicSuggestionCreateView(View):
    """POST /library/topic-suggestions/new/ — a person proposing a topic.

    The taxonomy is not owned by the model, so a reviewer can start the
    process directly. The same approval and release boundary applies: this
    creates a SUGGESTION, not an official topic.
    """

    def post(self, request):
        try:
            suggestion = sug.create_manual_suggestion(
                name             = request.POST.get('name', ''),
                parent_topic     = request.POST.get('parent_topic', ''),
                subcategory      = request.POST.get('subcategory', ''),
                reason           = request.POST.get('reason', ''),
                why_insufficient = request.POST.get('why_insufficient', ''),
                reviewer         = request.user if request.user.is_authenticated else None,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('library-topic-suggestions')
        messages.success(request,
                         f'Created suggestion #{suggestion.pk}. It still needs '
                         f'approval and a taxonomy release to become official.')
        return redirect('library-topic-suggestion-detail', pk=suggestion.pk)
