"""
api.py — JSON + HTMX endpoints for the V2 comparison workspace.
"""
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.db.models import Count, Q

from apps.accounts.decorators import role_required
from apps.library.models import Document
from apps.comparison.models import (
    ComparisonAnalysis, ComparisonRun, ComparisonResult,
    PAIR_CONFIGS, REL_COLORS, REL_LABELS,
)
from apps.comparison.strictness import compute_strictness_score

# Comparison is an analyst/reviewer-only workspace per user spec — admins do
# not run or review comparisons. (Admins have their own ops dashboard.)
ALL_ROLES = ('analyst', 'reviewer')
REVIEW_ROLES = ('reviewer',)


# ── V1 endpoints (kept for backward compat) ───────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class DocumentStrictnessView(View):
    def get(self, request, pk):
        get_object_or_404(Document, pk=pk)
        try:
            result = compute_strictness_score(pk)
        except Exception:
            return HttpResponse(status=500)

        if (
            request.GET.get('format') == 'json'
            or 'application/json' in request.headers.get('Accept', '')
        ):
            return _strictness_json(result)

        return render(request, 'partials/_strictness_meter.html', {'result': result})


def _strictness_json(result):
    components_out = {}
    for key, comp in result.components.items():
        components_out[key] = {
            'value':        comp.value,
            'normalized':   comp.normalized,
            'weight':       comp.weight,
            'contribution': comp.contribution,
        }
    return JsonResponse({
        'document_id':   result.document_id,
        'document_name': result.document_name,
        'score':         result.score,
        'score_tier':    result.score_tier,
        'components':    components_out,
        'summary_line':  result.summary_line,
    })


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class ComparisonArcsView(View):
    """V1 arc diagram endpoint."""
    def get(self, request, pk):
        analysis = get_object_or_404(ComparisonAnalysis, pk=pk)
        from apps.comparison.serializers import ArcDataSerializer
        data = ArcDataSerializer(analysis).serialize()
        if (
            request.GET.get('format') == 'json'
            or 'application/json' in request.headers.get('Accept', '')
        ):
            return JsonResponse(data)
        return render(request, 'partials/_equivalency_arc.html', {
            'data': data, 'analysis': analysis,
        })


# ── V2: Available pairs ────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class AvailablePairsView(View):
    def get(self, request):
        pairs = []
        for pair_key, cfg in PAIR_CONFIGS.items():
            reg_a = Document.objects.filter(
                jurisdiction=cfg['a'], doc_type=Document.REGULATION, status=Document.INDEXED
            ).first()
            reg_b = Document.objects.filter(
                jurisdiction=cfg['b'], doc_type=Document.REGULATION, status=Document.INDEXED
            ).first()
            last_run = None
            if reg_a and reg_b:
                last_run = ComparisonRun.objects.filter(
                    reg_a=reg_a, reg_b=reg_b, status=ComparisonRun.COMPLETE,
                ).first()
            pairs.append({
                'id':    pair_key,
                'label': cfg['label'],
                'reg_a': {'id': reg_a.pk, 'name': reg_a.name, 'chunk_count': reg_a.chunk_count} if reg_a else None,
                'reg_b': {'id': reg_b.pk, 'name': reg_b.name, 'chunk_count': reg_b.chunk_count} if reg_b else None,
                'last_compared_at': last_run.created_at.isoformat() if last_run else None,
                'last_run_id': last_run.pk if last_run else None,
                'available': bool(reg_a and reg_b),
            })
        return JsonResponse({'pairs': pairs})


# ── V2: Topic scan ────────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class TopicScanView(View):
    def post(self, request):
        try:
            body     = json.loads(request.body)
            reg_a_pk = body['reg_a_id']
            reg_b_pk = body['reg_b_id']
        except (json.JSONDecodeError, KeyError):
            return JsonResponse({'error': 'reg_a_id and reg_b_id required'}, status=400)

        from apps.comparison.topic_scan import scan_topic_coverage
        try:
            data = scan_topic_coverage(reg_a_pk, reg_b_pk)
        except Exception as exc:
            return JsonResponse({'error': str(exc)}, status=500)

        return JsonResponse(data)


# ── V2: Run status (progress page polling) ────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RunStatusView(View):
    def get(self, request, pk):
        run = get_object_or_404(ComparisonRun, pk=pk)
        if run.status in (ComparisonRun.COMPLETE, ComparisonRun.FAILED,
                          ComparisonRun.PARTIALLY_FAILED):
            response = HttpResponse()
            response['HX-Redirect'] = f'/comparison/runs/{run.pk}/'
            return response
        return render(request, 'partials/_run_progress_poll.html', {'run': run})


# ── V2: Run overview ──────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RunOverviewView(View):
    def get(self, request, pk):
        run     = get_object_or_404(ComparisonRun, pk=pk)
        results = list(run.results.all())
        total   = len(results)

        avg_sim = round(sum(r.similarity_score for r in results) / total * 100) if total else 0

        reviewed = sum(1 for r in results if r.lifecycle != ComparisonResult.DRAFT)
        approved = sum(1 for r in results if r.lifecycle == ComparisonResult.APPROVED)
        rejected = sum(1 for r in results if r.lifecycle == ComparisonResult.REJECTED)
        pct_rev  = round(reviewed / total * 100) if total else 0

        try:
            sa = compute_strictness_score(run.reg_a_id)
            sb = compute_strictness_score(run.reg_b_id)
            if sa.score >= sb.score:
                stricter_name, stricter_score, stricter_tier = run.reg_a.name, sa.score, sa.score_tier
                opp_name,      opp_score,      opp_tier      = run.reg_b.name, sb.score, sb.score_tier
            else:
                stricter_name, stricter_score, stricter_tier = run.reg_b.name, sb.score, sb.score_tier
                opp_name,      opp_score,      opp_tier      = run.reg_a.name, sa.score, sa.score_tier
        except Exception:
            stricter_name = stricter_tier = opp_name = opp_tier = '—'
            stricter_score = opp_score = 0.0

        data = {
            'similarity_overall': avg_sim,
            'pairs_total':        total,
            'stricter': {
                'name':          stricter_name,
                'score':         stricter_score,
                'tier':          stricter_tier,
                'opponent_name': opp_name,
                'opponent_score':opp_score,
                'opponent_tier': opp_tier,
            },
            'review': {
                'total':            total,
                'reviewed':         reviewed,
                'approved':         approved,
                'rejected':         rejected,
                'percent_reviewed': pct_rev,
            },
        }

        if request.GET.get('format') == 'json':
            return JsonResponse(data)

        return render(request, 'partials/_run_overview.html', {
            'run': run, 'overview': data,
        })


# ── V2: Clause list ────────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RunClausesView(View):
    def get(self, request, pk):
        run        = get_object_or_404(ComparisonRun, pk=pk)
        qs         = run.results.all()
        filter_val = request.GET.get('filter', 'all')
        search     = request.GET.get('search', '').strip()
        sort       = request.GET.get('sort', 'article')

        if filter_val == 'equivalent':
            qs = qs.filter(relationship=ComparisonResult.EQUIVALENT)
        elif filter_val == 'stricter':
            qs = qs.filter(relationship__in=[
                ComparisonResult.STRICTER_IN_A, ComparisonResult.STRICTER_IN_B,
            ])
        elif filter_val == 'additional':
            qs = qs.filter(relationship__in=[
                ComparisonResult.ADDITIONAL_IN_A, ComparisonResult.ADDITIONAL_IN_B,
            ])
        elif filter_val == 'conflicts':
            qs = qs.filter(relationship=ComparisonResult.CONFLICTING)
        elif filter_val == 'low_confidence':
            qs = qs.filter(confidence__lt=0.70)
        elif filter_val == 'needs_review':
            qs = qs.filter(lifecycle=ComparisonResult.DRAFT)

        if search:
            qs = qs.filter(
                Q(citation_a__icontains=search) |
                Q(citation_b__icontains=search) |
                Q(preview_a__icontains=search) |
                Q(preview_b__icontains=search) |
                Q(key_difference__icontains=search) |
                Q(rationale__icontains=search) |
                Q(reviewer_note__icontains=search)
            )

        if sort == 'confidence_asc':
            qs = qs.order_by('confidence')
        elif sort == 'confidence_desc':
            qs = qs.order_by('-confidence')
        elif sort == 'similarity_desc':
            qs = qs.order_by('-similarity_score')
        else:
            qs = qs.order_by('id')

        results = list(qs)
        counts  = _count_filters(run)

        return render(request, 'partials/_clause_list.html', {
            'run':        run,
            'results':    results,
            'counts':     counts,
            'filter_val': filter_val,
            'search':     search,
            'sort':       sort,
        })


def _count_filters(run) -> dict:
    return run.results.aggregate(
        all=Count('id'),
        equivalent=Count('id', filter=Q(relationship=ComparisonResult.EQUIVALENT)),
        stricter=Count('id', filter=Q(relationship__in=[
            ComparisonResult.STRICTER_IN_A, ComparisonResult.STRICTER_IN_B,
        ])),
        additional=Count('id', filter=Q(relationship__in=[
            ComparisonResult.ADDITIONAL_IN_A, ComparisonResult.ADDITIONAL_IN_B,
        ])),
        conflicts=Count('id', filter=Q(relationship=ComparisonResult.CONFLICTING)),
        low_confidence=Count('id', filter=Q(confidence__lt=0.70)),
        needs_review=Count('id', filter=Q(lifecycle=ComparisonResult.DRAFT)),
    )


# ── V2: Clause detail ─────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class ResultDetailView(View):
    def get(self, request, pk):
        result = get_object_or_404(ComparisonResult, pk=pk)
        from apps.review.views import _enrich, LIFECYCLE_META
        _enrich([result])
        return render(request, 'partials/_clause_detail.html', {
            'result':    result,
            'run':       result.run,
            'hx_target': '#rv-detail' if request.GET.get('review') else None,
        })


# ── V2: Lifecycle transition ──────────────────────────────────────────────────

@method_decorator(role_required(*REVIEW_ROLES), name='dispatch')
class ResultTransitionView(View):
    def post(self, request, pk):
        result = get_object_or_404(ComparisonResult, pk=pk)
        action = request.POST.get('action', request.POST.get('lifecycle', ''))
        action_map = {
            'approved': ComparisonResult.APPROVED,
            'rejected': ComparisonResult.REJECTED,
            'reset':    ComparisonResult.DRAFT,
            'reviewed': ComparisonResult.REVIEWED,
            'draft':    ComparisonResult.DRAFT,
        }
        new_lifecycle = action_map.get(action, action)
        valid = [
            ComparisonResult.REVIEWED, ComparisonResult.APPROVED,
            ComparisonResult.REJECTED, ComparisonResult.DRAFT,
        ]
        if new_lifecycle not in valid:
            return HttpResponse(status=400)

        from apps.comparison.models import AuditEvent
        AuditEvent.objects.create(
            result=result,
            actor=request.user.username if request.user.is_authenticated else 'reviewer',
            action=new_lifecycle,
            from_lifecycle=result.lifecycle,
            to_lifecycle=new_lifecycle,
        )
        old_lifecycle = result.lifecycle
        result.lifecycle = new_lifecycle
        result.save(update_fields=['lifecycle'])

        # Cross-cutting AuditLog row in addition to the comparison-specific
        # AuditEvent above (which stays as the lifecycle review-trail).
        from apps.history.audit import log_event, Actions
        action_map = {
            ComparisonResult.APPROVED: Actions.REVIEW_ACCEPT,
            ComparisonResult.REJECTED: Actions.REVIEW_REJECT,
        }
        audit_action = action_map.get(new_lifecycle, Actions.REVIEW_MODIFY)
        log_event(
            request.user, audit_action,
            request=request,
            target_type='comparison.ComparisonResult', target_id=result.pk,
            description=(
                f'{request.user.username} {new_lifecycle} '
                f'comparison result {result.citation_a} ↔ {result.citation_b or "—"}'
            ),
            metadata={
                'from_lifecycle': old_lifecycle,
                'to_lifecycle':   new_lifecycle,
                'run_id':         result.run_id,
            },
        )

        # Per-row approval can flip the run-level ReviewItem state — bust
        # the sidebar badge cache so it doesn't lag the 30 s TTL.
        try:
            from django.core.cache import cache
            cache.delete('nav_counts')
        except Exception:
            pass

        if request.POST.get('from_review'):
            from apps.review.views import _enrich
            _enrich([result])
            return render(request, 'partials/_review_card.html', {
                'result': result,
                'run':    result.run,
            })

        return render(request, 'partials/_clause_detail.html', {
            'result': result,
            'run':    result.run,
        })


# ── V2: Reviewer note ─────────────────────────────────────────────────────────

@method_decorator(role_required(*REVIEW_ROLES), name='dispatch')
class ResultNoteView(View):
    def post(self, request, pk):
        result = get_object_or_404(ComparisonResult, pk=pk)
        new_note = request.POST.get('note', '')
        old_note = result.reviewer_note
        result.reviewer_note = new_note
        result.save(update_fields=['reviewer_note'])

        from apps.history.audit import log_event, Actions
        log_event(
            request.user, Actions.REVIEW_MODIFY,
            request=request,
            target_type='comparison.ComparisonResult', target_id=result.pk,
            description=f'{request.user.username} edited reviewer note on result #{result.pk}',
            metadata={'old_note': old_note[:200], 'new_note': new_note[:200]},
        )
        return HttpResponse(status=204)


# ── V2: Graph data ────────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RunGraphView(View):
    def get(self, request, pk):
        run     = get_object_or_404(ComparisonRun, pk=pk)
        results = run.results.all()

        nodes = {}
        edges = []

        def _short(cit):
            if not cit:
                return cit
            if '—' in cit:
                return cit.split('—', 1)[1].strip()
            if '\u2014' in cit:
                return cit.split('\u2014', 1)[1].strip()
            return cit

        for r in results:
            a_id = f'a_{r.citation_a}'
            if a_id not in nodes:
                nodes[a_id] = {'id': a_id, 'label': r.citation_a, 'short_label': _short(r.citation_a), 'side': 'a', 'obligations': 0}
            nodes[a_id]['obligations'] += 1

            if r.citation_b:
                b_id = f'b_{r.citation_b}'
                if b_id not in nodes:
                    nodes[b_id] = {'id': b_id, 'label': r.citation_b, 'short_label': _short(r.citation_b), 'side': 'b', 'obligations': 0}
                nodes[b_id]['obligations'] += 1
                edges.append({
                    'source':             a_id,
                    'target':             b_id,
                    'relationship':       r.relationship,
                    'confidence':         round(r.confidence, 2),
                    'similarity':         round(r.similarity_score, 2),
                    'result_id':          r.pk,
                    'reg_a_text':         r.preview_a[:200],
                    'reg_b_text':         r.preview_b[:200],
                    'key_difference':     r.key_difference[:200],
                    'citation_verified':  r.citation_verified,
                })
            else:
                nodes[a_id]['no_match'] = True

        payload = {
            'nodes':      list(nodes.values()),
            'edges':      edges,
            'reg_a_name': run.reg_a.name,
            'reg_b_name': run.reg_b.name,
        }
        if request.GET.get('format') == 'json':
            return JsonResponse(payload)

        # HTML partial — renders an interactive D3 force-directed graph inline
        # so the Graph tab actually shows something instead of raw JSON.
        return render(request, 'partials/_run_graph.html', {
            'run':           run,
            'graph_payload': payload,
        })


# ── V2: Arc diagram ───────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RunArcsView(View):
    def get(self, request, pk):
        run  = get_object_or_404(ComparisonRun, pk=pk)
        from apps.comparison.serializers import RunArcSerializer
        data = RunArcSerializer(run).serialize()

        if request.GET.get('format') == 'json':
            return JsonResponse(data)

        # Reuse the existing arc partial (it works off data + analysis.reg_a/b)
        class _FakeAnalysis:
            reg_a = run.reg_a
            reg_b = run.reg_b
        return render(request, 'partials/_equivalency_arc.html', {
            'data': data, 'analysis': _FakeAnalysis(),
        })


# ── V2: Topic map ─────────────────────────────────────────────────────────────

_REL_ORDER = [
    ComparisonResult.EQUIVALENT,
    ComparisonResult.STRICTER_IN_A,
    ComparisonResult.STRICTER_IN_B,
    ComparisonResult.ADDITIONAL_IN_A,
    ComparisonResult.ADDITIONAL_IN_B,
    ComparisonResult.CONFLICTING,
]


def _short_citation(full: str) -> str:
    """Extract article/section label from 'Regulation Name — Article X' format."""
    for sep in (' \u2014 ', '\u2014', ' — ', ' - '):
        if sep in full:
            return full.split(sep, 1)[1].strip()
    return full


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RunTopicMapView(View):
    """Group this run's obligations by the **taxonomy topic** of the chunks
    each obligation cited, then summarise per topic. Replaces the old
    CONCEPT_SEEDS regex grouping which was heuristic — taxonomy tags come
    from the LLM chunk classifier, so the grouping is deterministic and
    matches what the reasoning layer used to retrieve those chunks."""

    def get(self, request, pk):
        from collections import Counter, defaultdict
        from reasoning import taxonomy as _tx

        run     = get_object_or_404(ComparisonRun, pk=pk)
        results = list(run.results.all())

        # Collect every chunk_id referenced by this run's results, look up
        # taxonomy topic per chunk_id from the chunk_tags side-table.
        all_chunk_ids = set()
        for r in results:
            if r.chunk_id_a: all_chunk_ids.add(r.chunk_id_a)
            if r.chunk_id_b: all_chunk_ids.add(r.chunk_id_b)
        chunk_topic_map: dict[str, str] = {}
        if all_chunk_ids:
            from retrieval.bm25_store import BM25_DB_PATH, _connect, _CREATE_TAGS_TABLE
            import sqlite3
            try:
                with _connect() as conn:
                    conn.execute(_CREATE_TAGS_TABLE)
                    placeholders = ",".join("?" * len(all_chunk_ids))
                    rows = conn.execute(
                        f"SELECT node_id, topic FROM chunk_tags "
                        f"WHERE node_id IN ({placeholders}) AND topic != 'unclassified'",
                        list(all_chunk_ids),
                    ).fetchall()
                    chunk_topic_map = {nid: topic for nid, topic in rows}
            except sqlite3.OperationalError:
                pass

        # Group results by their taxonomy topic(s).
        by_topic: dict[str, list] = defaultdict(list)
        for r in results:
            topics_here = set()
            if r.chunk_id_a in chunk_topic_map:
                topics_here.add(chunk_topic_map[r.chunk_id_a])
            if r.chunk_id_b in chunk_topic_map:
                topics_here.add(chunk_topic_map[r.chunk_id_b])
            for t in topics_here:
                by_topic[t].append(r)

        _DOM_MAP = {
            ComparisonResult.EQUIVALENT:     ('Equivalent',        '#3FB85C'),
            ComparisonResult.STRICTER_IN_A:  ('One Side Stricter', '#002583'),
            ComparisonResult.STRICTER_IN_B:  ('One Side Stricter', '#FFB800'),
            ComparisonResult.ADDITIONAL_IN_A:('Additional Clause', '#5A6BBE'),
            ComparisonResult.ADDITIONAL_IN_B:('Additional Clause', '#E5B45F'),
            ComparisonResult.CONFLICTING:    ('Conflicting',       '#D93939'),
        }
        _TOPIC_GROUPS = [
            ('equivalent',  'Equivalent',        '#3FB85C', [ComparisonResult.EQUIVALENT]),
            ('stricter',    'One Side Stricter', '#002583', [ComparisonResult.STRICTER_IN_A, ComparisonResult.STRICTER_IN_B]),
            ('additional',  'Additional Clause', '#5A6BBE', [ComparisonResult.ADDITIONAL_IN_A, ComparisonResult.ADDITIONAL_IN_B]),
            ('conflicting', 'Conflicting',       '#D93939', [ComparisonResult.CONFLICTING]),
        ]

        topics_data = []
        for topic_tag, relevant in by_topic.items():
            total     = len(relevant)
            eq        = sum(1 for r in relevant if r.relationship == ComparisonResult.EQUIVALENT)
            div       = round(1 - (eq / total), 2) if total else 0
            a_count   = sum(1 for r in relevant if r.citation_a)
            b_count   = sum(1 for r in relevant if r.citation_b)
            max_count = max(a_count, b_count, 1)

            _raw_dominant = max(
                set(r.relationship for r in relevant),
                key=lambda rel: sum(1 for r in relevant if r.relationship == rel),
                default='equivalent',
            )
            dominant_label, dominant_color = _DOM_MAP.get(_raw_dominant, ('Equivalent', '#3FB85C'))

            rel_breakdown = []
            for gkey, glabel, gcolor, grels in _TOPIC_GROUPS:
                cnt = sum(1 for r in relevant if r.relationship in grels)
                rel_breakdown.append({
                    'rel':   gkey, 'count': cnt,
                    'pct':   round(cnt / total * 100) if total else 0,
                    'color': gcolor, 'label': glabel,
                })

            confs = [r.confidence for r in relevant if r.confidence is not None]
            avg_conf = round(sum(confs) / len(confs) * 100) if confs else 0

            cit_a_info, cit_b_info = {}, {}
            for r in relevant:
                if r.citation_a and r.citation_a not in cit_a_info:
                    cit_a_info[r.citation_a] = {
                        'full':  r.citation_a,
                        'short': _short_citation(r.citation_a),
                        'text':  r.clause_text_a or r.preview_a or '',
                    }
                if r.citation_b and r.citation_b not in cit_b_info:
                    cit_b_info[r.citation_b] = {
                        'full':  r.citation_b,
                        'short': _short_citation(r.citation_b),
                        'text':  r.clause_text_b or r.preview_b or '',
                    }
            cit_a_top = Counter(r.citation_a for r in relevant if r.citation_a).most_common(5)
            cit_b_top = Counter(r.citation_b for r in relevant if r.citation_b).most_common(5)

            topics_data.append({
                'principle_id':      topic_tag,
                'label':             _tx.topic_label(topic_tag),
                'color_dot':         dominant_color,
                'color_light':       '#F4F6FB',
                'a_count':           a_count,
                'b_count':           b_count,
                'bar_width_a':       round(a_count / max_count * 100),
                'bar_width_b':       round(b_count / max_count * 100),
                'pair_count':        total,
                'dominant_color':    dominant_color,
                'dominant_label':    dominant_label,
                'divergence_score':  div,
                'divergence_pct':    round(div * 100),
                'rel_breakdown':     rel_breakdown,
                'avg_confidence':    avg_conf,
                'top_citations_a':   [cit_a_info[c] for c, _ in cit_a_top if c in cit_a_info],
                'top_citations_b':   [cit_b_info[c] for c, _ in cit_b_top if c in cit_b_info],
            })

        topics_data.sort(key=lambda x: x['divergence_score'], reverse=True)

        avg_div = round(
            sum(t['divergence_score'] for t in topics_data) / len(topics_data) * 100
        ) if topics_data else 0
        most_aligned = min(topics_data, key=lambda t: t['divergence_score'])['label'] if topics_data else ''

        if request.GET.get('format') == 'json':
            return JsonResponse({'topics': topics_data})

        return render(request, 'partials/_topic_map.html', {
            'run':               run,
            'topics':            topics_data,
            'avg_divergence':    avg_div,
            'most_aligned_label': most_aligned,
        })


# ── V2: Insights ─────────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class RunInsightsView(View):
    def get(self, request, pk):
        run     = get_object_or_404(ComparisonRun, pk=pk)
        results = list(run.results.all())

        from apps.comparison.insights import (
            get_top_divergences, compute_confidence_histogram,
            generate_ai_summary, generate_bbk_implications,
        )

        top3      = get_top_divergences(results, n=3)
        histogram = compute_confidence_histogram(results)
        summary   = generate_ai_summary(run)
        bbk_impl  = generate_bbk_implications(run, top3)

        return render(request, 'partials/_insights_tab.html', {
            'run':        run,
            'top3':       top3,
            'histogram':  histogram,
            'summary':    summary,
            'bbk_impl':   bbk_impl,
            'total':      len(results),
            'high_conf':  sum(b['count'] for b in histogram[5:]),
            'rel_colors': REL_COLORS,
            'rel_labels': REL_LABELS,
        })
