import json
import logging
import os
import subprocess
import sys
from datetime import timezone as dt_tz

from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.decorators import role_required
from apps.library.models import Document
from apps.mapping.models import Gap, MappingAnalysis, ObligationMapping

ALL_ROLES = ('analyst', 'reviewer', 'admin')
REVIEW_ROLES = ('reviewer', 'admin')

logger = logging.getLogger(__name__)

TOPIC_TILES = [
    {'key': 'retention',      'icon': '🗄️',  'label': 'Data retention'},
    {'key': 'consent',        'icon': '✅',  'label': 'Consent'},
    {'key': 'rights',         'icon': '👤',  'label': 'Data subject rights'},
    {'key': 'transfer',       'icon': '🌍',  'label': 'Cross-border transfers'},
    {'key': 'security',       'icon': '🔒',  'label': 'Security & breach notification'},
    {'key': 'notice',         'icon': '📄',  'label': 'Privacy notice'},
    {'key': 'minimisation',   'icon': '⚖️',  'label': 'Data minimisation'},
    {'key': 'accountability', 'icon': '📋',  'label': 'Accountability'},
]

COVERAGE_LABELS = {
    ObligationMapping.COVERED: 'Covered',
    ObligationMapping.PARTIAL: 'Partial',
    ObligationMapping.REVIEW:  'Review',
    ObligationMapping.NONE:    'Not covered',
}

COVERAGE_COLORS = {
    ObligationMapping.COVERED: ('#FFB800', '#E5E8EF'),
    ObligationMapping.PARTIAL: ('#FFB800', '#E5E8EF'),
    ObligationMapping.REVIEW:  ('#002583', '#E5E8EF'),
    ObligationMapping.NONE:    ('#002583', '#E5E8EF'),
}

PRIORITY_COLORS = {
    Gap.CRITICAL: ('#002583', '#E5E8EF'),
    Gap.HIGH:     ('#002583', '#E5E8EF'),
    Gap.MEDIUM:   ('#FFB800', '#E5E8EF'),
    Gap.LOW:      ('#FFB800', '#E5E8EF'),
}

COVERAGE_CYCLE = [
    ObligationMapping.COVERED,
    ObligationMapping.PARTIAL,
    ObligationMapping.REVIEW,
    ObligationMapping.NONE,
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_topics(doc):
    """Return list of display label strings from doc.cached_topics concept IDs."""
    try:
        from apps.comparison.concepts import CONCEPT_SEEDS
        return [
            CONCEPT_SEEDS[cid]['label']
            for cid in (doc.cached_topics or [])
            if cid in CONCEPT_SEEDS
        ]
    except Exception:
        return []


def _map_coverage(status: str) -> str:
    s = status.strip().lower()
    if 'fully' in s or s == 'covered':
        return ObligationMapping.COVERED
    if 'partial' in s:
        return ObligationMapping.PARTIAL
    if 'review' in s:
        return ObligationMapping.REVIEW
    return ObligationMapping.NONE


def _infer_priority(coverage: str) -> str:
    return {
        ObligationMapping.NONE:    Gap.HIGH,
        ObligationMapping.REVIEW:  Gap.MEDIUM,
        ObligationMapping.PARTIAL: Gap.MEDIUM,
    }.get(coverage, Gap.LOW)


# ── Ollama health check ───────────────────────────────────────────────────────

def _ollama_is_reachable() -> bool:
    import urllib.request
    try:
        from config import OLLAMA_URL
        urllib.request.urlopen(f'{OLLAMA_URL}/api/tags', timeout=3)
        return True
    except Exception:
        return False


# ── subprocess launcher ───────────────────────────────────────────────────────

def _launch_subprocess(command: str, *args: str) -> None:
    """Spawn a management command as an independent process."""
    import pathlib
    from django.conf import settings
    base = pathlib.Path(settings.BASE_DIR)          # …/cjpca
    project_root = str(base.parent)                 # …/  (contains reasoning/)
    manage_py = str(base / 'manage.py')
    env = os.environ.copy()
    env.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
    # Ensure both the Django project dir and the project root (for `reasoning`)
    # are on PYTHONPATH inside the subprocess.
    existing = env.get('PYTHONPATH', '')
    extra = os.pathsep.join([str(base), project_root])
    env['PYTHONPATH'] = f'{extra}{os.pathsep}{existing}' if existing else extra
    log_dir = base / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f'{command}_{"_".join(args)}.log'
    log_fh = open(log_path, 'w', buffering=1)
    proc = subprocess.Popen(
        [sys.executable, manage_py, command, *args],
        cwd=str(base),
        env=env,
        stdout=log_fh,
        stderr=log_fh,
    )
    logger.info('Launched subprocess pid=%s command=%s args=%s log=%s', proc.pid, command, args, log_path)


# ── background AI runner ──────────────────────────────────────────────────────


def _run_mapping_job(analysis_id: int) -> None:
    import django.db
    django.db.close_old_connections()

    try:
        analysis = MappingAnalysis.objects.prefetch_related('regulations').get(pk=analysis_id)
    except MappingAnalysis.DoesNotExist:
        # The row vanished between view-side create and the thread starting.
        # Belt-and-braces: try to flip the status anyway in case the row
        # exists but the prefetch failed for some other reason — otherwise
        # we'd silently leak a RUNNING row that blocks future submissions.
        logger.error('MappingAnalysis %s not found at worker start', analysis_id)
        try:
            MappingAnalysis.objects.filter(pk=analysis_id).update(
                status=MappingAnalysis.FAILED,
                error='Worker could not load analysis row at start.',
            )
        except Exception:
            pass
        return

    try:
        from reasoning.workflows import map_policy_coverage_auto
        from retrieval.bm25_store import get_chunk_provision

        # one helper to write a reasoning-layer item → ObligationMapping +
        # Gap row. used by both the auto and the legacy paths so a future
        # change to the reasoning schema doesn't have to be applied twice.
        def _persist_item(item, reg_doc):
            coverage = _map_coverage(item.coverage_status)
            # Title is the truncated card-header version; obligation_text is
            # the full LLM-produced obligation, rendered in the expanded
            # panel. Truncate at the last word boundary so we never end on
            # "…and r" mid-word.
            full_obligation = (item.regulatory_obligation or '').strip()
            if len(full_obligation) > 300:
                cut = full_obligation[:297].rsplit(' ', 1)[0]
                title_short = cut + '…'
            else:
                title_short = full_obligation
            # evidence_text holds the policy-side verbatim quote (the
            # actual evidence for the verdict). Don't co-opt it for the
            # gap description — those go on dedicated fields.
            policy_quote = (item.policy_excerpt or '').strip()
            # Real per-row confidence. PolicyCoverageItem doesn't carry a
            # confidence float directly (the LLM emits coverage + grounding
            # signals rather than a number), so we derive it from the two
            # signals it DOES emit:
            #   citation_verified — does the regulation citation ground?
            #   hallucination_risk — NLI score, 0 entailed → 1 unsupported.
            # Unverified citations cap at 0.6; otherwise we scale by (1-risk).
            # Was hardcoded to 0.5 for every row, which made downstream AI-
            # quality and severity-by-confidence aggregations partly fake.
            # ── Anti-fabrication guardrail ──────────────────────────────
            # The article reference shown in the UI must be looked up from
            # the STORED provision record, never echoed from model output.
            # The mapper returns the chunk id it based its judgement on; we
            # read THAT chunk's indexed article_ref and use it. If the chunk
            # can't be found the citation is ungrounded — we refuse to render
            # the model's free-text regulation_citation and fall back to the
            # regulation's own name (a real document), flagging the row as
            # unverified so it can never masquerade as a grounded citation.
            reg_chunk_id = getattr(item, 'regulation_chunk_id', '') or ''
            provision = get_chunk_provision(reg_chunk_id) if reg_chunk_id else None
            grounded_ref = (provision or {}).get('article_ref', '').strip() if provision else ''
            citation_grounded = bool(grounded_ref)
            if not citation_grounded:
                grounded_ref = (reg_doc.name or 'Regulation')

            verified  = bool(getattr(item, 'citation_verified', True)) and citation_grounded
            hall_risk = float(getattr(item, 'hallucination_risk', 0.0) or 0.0)
            base      = 1.0 if verified else 0.6
            confidence = max(0.05, min(1.0, base * (1.0 - hall_risk)))
            confidence = round(confidence, 2)
            om = ObligationMapping.objects.create(
                analysis=analysis,
                article_ref=grounded_ref[:100],
                obligation_title=title_short,
                obligation_text=full_obligation,
                regulation=reg_doc,
                coverage=coverage,
                evidence_text=policy_quote,
                evidence_source=item.policy_section,
                confidence_pct=round(confidence * 100),
                confidence=confidence,
                severity=ObligationMapping.derive_severity(coverage, confidence),
                regulation_evidence=getattr(item, 'regulation_evidence', '') or '',
                regulation_chunk_id=getattr(item, 'regulation_chunk_id', '') or '',
                policy_chunk_id=getattr(item, 'policy_chunk_id', '') or '',
                citation_verified=verified,
                hallucination_risk=hall_risk,
                topics=[item.topic] if getattr(item, 'topic', '') else [],
                # rationale doubles as the LLM's verbal explanation of the
                # verdict. for non-Covered rows the LLM produces a
                # gap_description; for Covered rows it's empty (the prompt
                # only asks for a description when there's a gap), and the
                # UI falls back to a "both clauses align" template.
                rationale=(item.gap_description or '').strip(),
            )
            if coverage != ObligationMapping.COVERED:
                Gap.objects.create(
                    mapping=analysis,
                    obligation_mapping=om,
                    priority=_infer_priority(coverage),
                    severity=_infer_priority(coverage),
                    remediation_text=item.remediation_suggestion,
                    remediation_source=Gap.AI_DRAFTED,
                )
                return 1, 1   # obligation + gap
            return 1, 0       # obligation only

        obligation_count = 0
        gap_count = 0
        regs = list(analysis.regulations.filter(status=Document.INDEXED))

        # Auto-route is the only mode. The legacy Full-scan / Pick-topics
        # paths (which did keyword-soup retrieval with no taxonomy filter)
        # were retired — the per-topic mapper below is the only entry now.
        policy_title = analysis.policy_doc.chunk_doc_title
        analysis.progress_total = len(regs)
        analysis.save(update_fields=['progress_total'])

        topics_used_overall = set()
        # tag -> {topic,label,policy_chunks}. A topic skipped for one reg may be
        # mapped by another, so we collect candidates here and subtract anything
        # that ended up mapped before persisting (below).
        skipped_candidates: dict = {}
        for step, reg_doc in enumerate(regs, 1):
            # Leave progress_current pointing at the LAST completed step
            # while we WORK on the current one — that way the bar doesn't
            # jump to 100% the moment we start the only regulation.
            analysis.current_obligation_label = (
                f'Mapping against {reg_doc.name} ({step}/{len(regs)})'
            )[:200]
            analysis.save(update_fields=['current_obligation_label'])

            # Heartbeat callback — writes "Topic X of Y: <label>" to the
            # analysis row before each per-topic LLM call so the progress
            # UI shows real motion instead of sitting on one line for the
            # full wall time.
            def _topic_progress(topic_idx, total_topics, topic_label,
                                _reg_name=reg_doc.name,
                                _step=step,
                                _total=len(regs)):
                try:
                    msg = (
                        f'Mapping against {_reg_name} ({_step}/{_total}) — '
                        f'topic {topic_idx}/{total_topics}: {topic_label}'
                    )[:200]
                    MappingAnalysis.objects.filter(pk=analysis.pk).update(
                        current_obligation_label=msg,
                    )
                except Exception:
                    pass

            try:
                # Scope retrieval to JUST this regulation. Without
                # doc_titles_reg, the auto-route would pull topic-matching
                # chunks from EVERY indexed reg in the jurisdiction.
                report = map_policy_coverage_auto(
                    doc_titles_policy=[policy_title],
                    doc_titles_reg=[reg_doc.chunk_doc_title] if reg_doc.chunk_doc_title else None,
                    jurisdiction=reg_doc.jurisdiction,
                    progress_cb=_topic_progress,
                )
            except Exception as exc:
                logger.error('map_policy_coverage_auto failed for %s: %s',
                             reg_doc.jurisdiction, exc)
                continue

            for item in report.items:
                o, g = _persist_item(item, reg_doc)
                obligation_count += o
                gap_count += g

            analysis.progress_current = step
            analysis.save(update_fields=['progress_current'])

            if isinstance(report.query, list):
                topics_used_overall.update(report.query)

            for st in getattr(report, 'skipped_topics', None) or []:
                # SkippedTopic (pydantic) or dict, depending on caller.
                tag   = getattr(st, 'topic', None) if not isinstance(st, dict) else st.get('topic')
                label = getattr(st, 'label', None) if not isinstance(st, dict) else st.get('label')
                pc    = getattr(st, 'policy_chunks', 0) if not isinstance(st, dict) else st.get('policy_chunks', 0)
                if tag:
                    skipped_candidates[tag] = {'topic': tag, 'label': label or tag,
                                               'policy_chunks': pc}

        # A candidate is genuinely skipped only if it was mapped against NO
        # regulation. topics_used_overall holds human labels, so compare on the
        # label we stored alongside each candidate.
        mapped_labels = set(topics_used_overall)
        skipped_final = [v for v in skipped_candidates.values()
                         if v['label'] not in mapped_labels]

        analysis.scope_topics = sorted(topics_used_overall)
        analysis.skipped_topics = skipped_final
        analysis.topic = ', '.join(sorted(topics_used_overall))[:255] or 'auto'
        analysis.save(update_fields=['scope_topics', 'skipped_topics', 'topic'])

        analysis.status = MappingAnalysis.COMPLETE
        analysis.obligation_count = obligation_count
        analysis.gap_count = gap_count
        analysis.progress_current = analysis.progress_total
        analysis.completed_at = timezone.now()
        analysis.save(update_fields=[
            'status', 'obligation_count', 'gap_count',
            'progress_current', 'completed_at',
        ])
        logger.info('MappingAnalysis %s complete — %s obligations, %s gaps',
                    analysis_id, obligation_count, gap_count)

        try:
            from apps.history.audit import log_event, Actions
            log_event(
                analysis.created_by, Actions.MAPPING_COMPLETE,
                target_type='mapping.MappingAnalysis', target_id=analysis.pk,
                description=f'Mapping analysis #{analysis.pk} complete: {obligation_count} obligations, {gap_count} gaps',
                metadata={
                    'policy_id':        analysis.policy_doc_id,
                    'obligation_count': obligation_count,
                    'gap_count':        gap_count,
                },
            )
        except Exception:
            pass

    except Exception as exc:
        import traceback
        logger.error('MappingAnalysis %s failed:\n%s', analysis_id, traceback.format_exc())
        try:
            MappingAnalysis.objects.filter(pk=analysis_id).update(
                status=MappingAnalysis.FAILED,
                error=traceback.format_exc()[:2000],
            )
        except Exception:
            pass

        try:
            from apps.history.audit import log_event, Actions
            log_event(
                analysis.created_by, Actions.MAPPING_FAILED,
                target_type='mapping.MappingAnalysis', target_id=analysis.pk,
                description=f'Mapping analysis #{analysis.pk} failed: {str(exc)[:200]}',
                metadata={'error': str(exc)[:500]},
            )
        except Exception:
            pass


# ── Screen 1 — Policy select ──────────────────────────────────────────────────

@method_decorator(role_required('analyst'), name='dispatch')
class PolicySelectView(TemplateView):
    """GET /mapping/ — pick a policy to map. Analyst-only kickoff surface;
    reviewers see results via the review queue and the workspace, not the
    'start a new mapping' page."""
    template_name = 'pages/mapping/policy_select.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        policies_qs = (
            Document.objects
            .filter(doc_type=Document.POLICY, status=Document.INDEXED)
            .annotate(
                prior_mapping_count=Count('mapping_analyses', distinct=True),
                open_gap_count=Count(
                    'mapping_analyses__gaps',
                    filter=Q(mapping_analyses__gaps__closed_at__isnull=True),
                    distinct=True,
                ),
            )
            .prefetch_related(
                Prefetch(
                    'mapping_analyses',
                    queryset=MappingAnalysis.objects.filter(
                        status=MappingAnalysis.COMPLETE,
                    ).order_by('-completed_at'),
                    to_attr='completed_analyses',
                )
            )
            .order_by('-upload_date')
        )

        enriched = []
        for p in policies_qs:
            p.cached_topics = _resolve_topics(p)
            completed = getattr(p, 'completed_analyses', [])
            p.last_analysis = completed[0] if completed else None
            # Use last_analysis as single source of truth for both score and gap count
            # so they are always internally consistent.
            if p.last_analysis:
                p.current_gap_count = p.last_analysis.gap_count
                if p.last_analysis.obligation_count:
                    covered = p.last_analysis.obligation_count - p.last_analysis.gap_count
                    p.compliance_score = round(covered / p.last_analysis.obligation_count * 100)
                else:
                    p.compliance_score = None
            else:
                p.current_gap_count = 0
                p.compliance_score = None
            enriched.append(p)

        attention_count = sum(1 for p in enriched if p.current_gap_count > 0)
        never_count     = sum(1 for p in enriched if p.prior_mapping_count == 0)
        clean_count     = sum(1 for p in enriched if p.prior_mapping_count > 0 and p.current_gap_count == 0)

        ctx['policies']         = enriched
        ctx['attention_count']  = attention_count
        ctx['never_count']      = never_count
        ctx['clean_count']      = clean_count
        return ctx


# ── Screen 2 — Mapping setup ──────────────────────────────────────────────────

@method_decorator(role_required('analyst'), name='dispatch')
class MappingSetupView(TemplateView):
    """GET /mapping/setup/<pk>/ — configure scope and regulations."""
    template_name = 'pages/mapping/setup.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        policy = get_object_or_404(
            Document, pk=self.kwargs['pk'],
            doc_type=Document.POLICY, status=Document.INDEXED,
        )
        policy.cached_topics = _resolve_topics(policy)

        reg_qs = (
            Document.objects
            .filter(doc_type=Document.REGULATION, status=Document.INDEXED)
            .order_by('jurisdiction', 'name')
        )
        reg_list = list(reg_qs)

        _jur_labels = {
            'bahrain': 'Bahrain', 'india': 'India', 'kuwait': 'Kuwait',
            'bbk': 'BBK', 'eu': 'European Union',
            'saudi': 'Saudi Arabia', 'uae': 'UAE', 'other': 'Other',
        }
        _flag_codes = {
            'bahrain': 'bh', 'india': 'in', 'kuwait': 'kw',
            'eu': 'eu', 'saudi': 'sa', 'uae': 'ae',
        }

        seen_jur = {}
        for r in reg_list:
            seen_jur.setdefault(r.jurisdiction, []).append(r)

        reg_groups = [
            {
                'jur':   jur,
                'label': _jur_labels.get(jur, jur.title()),
                'flag':  _flag_codes.get(jur, ''),
                'regs':  regs,
            }
            for jur, regs in seen_jur.items()
        ]

        # ── classified topic discovery (drives the auto-route panel) ────
        # ask the chunk-tags sidecar what topics the policy actually covers
        # and what topics each jurisdiction has indexed clauses for. these
        # populate the "Will map / Skipped" panel in setup.html so the user
        # sees the methodological intersection BEFORE clicking Start.
        # JURISDICTION_NORM is the same map ingestion uses, so passing the
        # jurisdiction here matches what's actually stored in chroma/bm25.
        from config import JURISDICTION_NORM
        try:
            from retrieval.bm25_store import topics_for_docs, topics_for_jurisdiction
            from reasoning.taxonomy   import TAXONOMY
        except Exception:
            topics_for_docs = topics_for_jurisdiction = None
            TAXONOMY = {}

        policy_topics_classified: list[dict] = []
        reg_topics_by_jur: dict[str, dict] = {}
        # Per-document topic counts so the front-end can show the REAL
        # intersection for the user's actual selection rather than a
        # whole-jurisdiction approximation (which double-counted topics
        # when multiple regs from the same jurisdiction were selected).
        reg_topics_by_doc: dict[str, dict] = {}
        if topics_for_docs and policy.chunk_doc_title:
            policy_jur = JURISDICTION_NORM.get((policy.jurisdiction or '').lower(), policy.jurisdiction)
            for tag, count in topics_for_docs([policy.chunk_doc_title], jurisdiction=policy_jur):
                policy_topics_classified.append({
                    'tag':   tag,
                    'label': TAXONOMY.get(tag, {}).get('label', tag),
                    'count': count,
                })
            for r in reg_list:
                if not r.chunk_doc_title:
                    continue
                norm = JURISDICTION_NORM.get((r.jurisdiction or '').lower(), r.jurisdiction)
                reg_topics_by_doc[str(r.pk)] = dict(
                    topics_for_docs([r.chunk_doc_title], jurisdiction=norm)
                )

        if topics_for_jurisdiction:
            for jur in {r.jurisdiction for r in reg_list}:
                norm = JURISDICTION_NORM.get((jur or '').lower(), jur)
                reg_topics_by_jur[jur] = topics_for_jurisdiction(norm)

        ctx.update({
            'policy':                    policy,
            'reg_groups':                reg_groups,
            'topic_tiles':               TOPIC_TILES,
            'reg_chunks_json':           json.dumps({str(r.pk): r.chunk_count for r in reg_list}),
            # the auto-route panel reads these directly + via JS
            'policy_topics_classified':  policy_topics_classified,
            # client-side intersection: {regulation_pk: jurisdiction_string}
            'reg_jurisdictions_json':    json.dumps({str(r.pk): r.jurisdiction for r in reg_list}),
            # {jurisdiction: {topic_tag: count}} — kept for backwards compat
            # but no longer the intersection source of truth.
            'reg_topics_by_jur_json':    json.dumps(reg_topics_by_jur),
            # {regulation_pk: {topic_tag: count}} — the source of truth for
            # the auto-route intersection panel. JS sums topic counts ONLY
            # across the regs the user actually selected, so the numbers
            # reflect their actual choice (no double-counting from picking
            # multiple regs in the same jurisdiction).
            'reg_topics_by_doc_json':    json.dumps(reg_topics_by_doc),
            # {topic_tag: human label} so JS can render labels without
            # re-implementing the taxonomy
            'topic_labels_json':         json.dumps({
                t['tag']: t['label'] for t in policy_topics_classified
            }),
        })
        return ctx


# ── Screen 2 form submit — start mapping ─────────────────────────────────────

@method_decorator(role_required('analyst'), name='dispatch')
class MappingRunView(View):
    """POST /mapping/setup/<pk>/run/ — create analysis, start background job."""

    def post(self, request, pk):
        policy = get_object_or_404(
            Document, pk=pk,
            doc_type=Document.POLICY, status=Document.INDEXED,
        )

        reg_ids = request.POST.getlist('regulations')
        # Scope is hard-coded to AUTO. Full scan and Pick topics were
        # retired — both did keyword-soup retrieval with no taxonomy filter
        # and produced noisier output than auto-route's per-topic mapping.
        # Posted value (if any) is ignored.
        scope_mode   = MappingAnalysis.SCOPE_AUTO
        scope_topics: list[str] = []

        regulations = Document.objects.filter(
            pk__in=reg_ids,
            doc_type=Document.REGULATION,
            status=Document.INDEXED,
        )
        if not regulations.exists():
            return redirect('mapping-setup', pk=pk)

        # Block if another analysis is already running — but only if it's
        # actually making progress. A crashed worker can leave a row stuck at
        # RUNNING indefinitely (no signal handler to flip it to FAILED), and
        # before this guard, that one zombie row locked every user out of
        # mapping until an admin manually edited the DB. So: if the last save
        # was more than STALE_THRESHOLD ago, treat it as dead and reap it.
        from datetime import timedelta
        STALE_THRESHOLD = timedelta(minutes=15)
        now = timezone.now()
        running = MappingAnalysis.objects.filter(status=MappingAnalysis.RUNNING)
        live_running = []
        for r in running:
            heartbeat = r.run_at  # auto_now_add — won't refresh, but ok as a floor
            # Most recent observable progress write: completed_at, run_at, or
            # the file-system mtime of progress_current via the cancelled_at /
            # completed_at fields. Use the latest of run_at / cancelled_at /
            # completed_at as a coarse heartbeat — good enough to detect "this
            # row has been RUNNING for > 15 min without ANY save". Fine-grained
            # heartbeat would need a new column; this catches the failure mode.
            for ts in (r.completed_at, r.cancelled_at):
                if ts and ts > heartbeat:
                    heartbeat = ts
            if (now - heartbeat) > STALE_THRESHOLD:
                # Reap the zombie so it doesn't block future runs forever.
                MappingAnalysis.objects.filter(pk=r.pk).update(
                    status=MappingAnalysis.FAILED,
                    error='Reaped: worker stopped reporting progress for >15 min.',
                )
                logger.warning('Reaped stale RUNNING MappingAnalysis %s (age %s)',
                               r.pk, now - heartbeat)
            else:
                live_running.append(r)
        if live_running:
            from django.contrib import messages
            messages.warning(request, 'Another analysis is already running. Please wait for it to complete.')
            return redirect('mapping-setup', pk=pk)

        analysis = MappingAnalysis.objects.create(
            policy_doc=policy,
            topic=', '.join(scope_topics) if scope_topics else 'full',
            scope_mode=scope_mode,
            scope_topics=scope_topics,
            status=MappingAnalysis.RUNNING,
            created_by=request.user if request.user.is_authenticated else None,
        )
        analysis.regulations.set(regulations)

        if not _ollama_is_reachable():
            analysis.delete()
            messages_error = 'Ollama is not running. Start Ollama and try again.'
            return render(request, 'pages/mapping/setup.html', {
                'policy': policy,
                'error': messages_error,
            })

        from apps.history.audit import log_event, Actions
        log_event(
            request.user, Actions.MAPPING_RUN,
            request=request,
            target_type='mapping.MappingAnalysis', target_id=analysis.pk,
            description=f'{request.user.username} ran policy mapping for {policy.name}',
            metadata={
                'policy': policy.name,
                'regulations': [r.name for r in regulations],
                'scope_mode': scope_mode,
                'topics': scope_topics,
            },
        )

        # Background-thread execution. Returns immediately so the browser
        # lands on /mapping/<pk>/running/, which polls the progress endpoint
        # every 2s and redirects to the workspace once the analysis row is
        # marked complete. Subprocess was unreliable (server restarts killed
        # the worker); synchronous was a 4–8 min request blocking the user
        # with no visible progress; in-process threading lets us write
        # progress to the DB and have the client poll it.
        import threading
        from django.db import close_old_connections

        def _thread_target(aid):
            close_old_connections()  # each thread gets its own DB connection
            try:
                _run_mapping_job(aid)
            finally:
                close_old_connections()

        threading.Thread(target=_thread_target, args=(analysis.pk,), daemon=True).start()

        return redirect('mapping-running', pk=analysis.pk)


# ── Screen 3 — Running / progress ────────────────────────────────────────────

@method_decorator(role_required('analyst', 'reviewer', 'admin'), name='dispatch')
class MappingRunningView(View):
    """GET /mapping/<pk>/running/ — progress screen with HTMX polling."""

    def get(self, request, pk):
        analysis = get_object_or_404(MappingAnalysis, pk=pk)

        if analysis.status == MappingAnalysis.COMPLETE:
            return redirect('mapping-workspace', pk=pk)
        if analysis.status == MappingAnalysis.FAILED:
            return render(request, 'pages/mapping/running.html', {
                'analysis': analysis, 'failed': True,
            })

        if request.headers.get('HX-Request'):
            if analysis.status == MappingAnalysis.COMPLETE:
                response = HttpResponse()
                response['HX-Redirect'] = f'/mapping/{pk}/'
                return response
            return render(request, 'partials/_mapping_progress.html', {
                'analysis': analysis,
            })

        return render(request, 'pages/mapping/running.html', {
            'analysis': analysis, 'failed': False,
        })


@method_decorator(role_required('analyst'), name='dispatch')
class MappingCancelView(View):
    """POST /mapping/<pk>/cancel/ — cancel a running analysis."""

    def post(self, request, pk):
        analysis = get_object_or_404(MappingAnalysis, pk=pk)
        if analysis.status == MappingAnalysis.RUNNING:
            analysis.status = MappingAnalysis.CANCELLED
            analysis.cancelled_at = timezone.now()
            analysis.save(update_fields=['status', 'cancelled_at'])
        return redirect('mapping')


# ── Screen 4 — Results workspace ──────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class MappingWorkspaceView(View):
    """GET /mapping/<pk>/ — results workspace."""

    def get(self, request, pk):
        analysis = get_object_or_404(MappingAnalysis, pk=pk)

        if analysis.status in (MappingAnalysis.RUNNING, MappingAnalysis.QUEUED):
            return redirect('mapping-running', pk=pk)

        # FAILED / CANCELLED rows have no ObligationMapping / Gap rows, so the
        # workspace template would render blank (or crash on missing context
        # vars). Send the user back to the running page in its failed state —
        # that template already handles `failed=True` with a proper error
        # banner + retry CTA.
        if analysis.status in (MappingAnalysis.FAILED, MappingAnalysis.CANCELLED):
            from django.contrib import messages
            if analysis.status == MappingAnalysis.CANCELLED:
                messages.info(request, f'Mapping for "{analysis.policy_doc.name}" was cancelled.')
            else:
                messages.error(
                    request,
                    f'Mapping for "{analysis.policy_doc.name}" failed. '
                    f'{(analysis.error or "")[:200]}',
                )
            return render(request, 'pages/mapping/running.html', {
                'analysis': analysis,
                'failed': True,
            })

        ctx = {'analysis': analysis}
        if analysis.status in (MappingAnalysis.COMPLETE, MappingAnalysis.REVIEW, MappingAnalysis.APPROVED):
            mappings = (
                analysis.obligation_mappings
                .select_related('regulation')
                .order_by('regulation__jurisdiction', 'article_ref')
            )
            gaps = (
                analysis.gaps
                .select_related('obligation_mapping', 'obligation_mapping__regulation')
                .order_by('obligation_mapping__regulation__jurisdiction', 'pk')
            )
            counts = {
                'covered': mappings.filter(coverage=ObligationMapping.COVERED).count(),
                'partial': mappings.filter(coverage=ObligationMapping.PARTIAL).count(),
                'review':  mappings.filter(coverage=ObligationMapping.REVIEW).count(),
                'none':    mappings.filter(coverage=ObligationMapping.NONE).count(),
            }

            # Coverage by regulation — evaluate mappings once
            from collections import OrderedDict
            reg_cov: OrderedDict = OrderedDict()
            for m in mappings:
                rk = str(m.regulation.pk)
                if rk not in reg_cov:
                    reg_cov[rk] = {
                        'name': m.regulation.name,
                        'covered': 0, 'partial': 0, 'review': 0, 'none': 0,
                    }
                reg_cov[rk][m.coverage] += 1
            reg_list = list(reg_cov.values())
            # ordered counts for the carousel JS state — matches the
            # {% regroup mappings by regulation %} iteration order, which
            # matches the queryset's order_by('regulation__jurisdiction',
            # 'article_ref'). also a parallel list of (gap_count) per reg.
            ob_counts_per_reg = [v['covered'] + v['partial'] + v['review'] + v['none']
                                 for v in reg_list]

            gap_counts_per_reg_dict: dict = OrderedDict()
            for g in gaps:
                rk = str(g.obligation_mapping.regulation.pk)
                gap_counts_per_reg_dict[rk] = gap_counts_per_reg_dict.get(rk, 0) + 1
            gap_counts_per_reg = list(gap_counts_per_reg_dict.values())

            # Gap priority counts
            pri = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
            for g in gaps:
                pri[g.priority] = pri.get(g.priority, 0) + 1

            total = sum(counts.values())
            compliance_score = (
                round((counts['covered'] + 0.5 * counts['partial']) / total * 100)
                if total else 0
            )

            # AI quality aggregates — parallel to what the comparison workspace
            # surfaces. citation_verified is the structural check (citation
            # label + chunk_id + verbatim evidence all matched a real chunk).
            # hallucination_risk is the NLI score (0 = entailed, 1 = unsupported).
            from django.db.models import Avg
            verified_count = mappings.filter(citation_verified=True).count()
            verified_pct   = round(verified_count / total * 100) if total else 0
            avg_hall = mappings.aggregate(Avg('hallucination_risk'))['hallucination_risk__avg'] or 0.0
            # rows over 0.5 NLI risk are "the model paraphrased far enough that
            # the cited chunk doesn't actually entail it" — flagged for human
            # review even when citation_verified passes structurally.
            high_risk_count = mappings.filter(hallucination_risk__gt=0.5).count()
            # combined AI quality score: 70% verification ratio + 30% inverted
            # mean hallucination risk. tuned to drop visibly when either signal
            # degrades, not just one.
            ai_quality_score = round(0.7 * verified_pct + 0.3 * (1.0 - avg_hall) * 100)

            # Distinct status colors. Charts and template share the same
            # palette so the legend, badges, and chart slices line up:
            #   covered  = success green   #1E7E48
            #   partial  = amber           #FFB800
            #   review   = navy            #002583
            #   none     = danger red      #C03A3A
            chart_data = {
                'coverage': {
                    'labels': ['Covered', 'Partial', 'Needs Review', 'Not Covered'],
                    'values': [counts['covered'], counts['partial'], counts['review'], counts['none']],
                    'colors': ['#1E7E48', '#FFB800', '#002583', '#C03A3A'],
                },
                'byRegulation': {
                    'labels':  [r['name'] for r in reg_list],
                    'covered': [r['covered'] for r in reg_list],
                    'partial': [r['partial'] for r in reg_list],
                    'review':  [r['review'] for r in reg_list],
                    'none':    [r['none'] for r in reg_list],
                },
                'gapPriority': {
                    'labels': ['Critical', 'High', 'Medium', 'Low'],
                    'values': [pri['critical'], pri['high'], pri['medium'], pri['low']],
                    'colors': ['#C03A3A', '#E07A1F', '#FFB800', '#5A6685'],
                },
                'complianceScore': compliance_score,
            }

            ctx.update({
                'mappings':          mappings,
                'gaps':              gaps,
                'counts':            counts,
                'coverage_labels':   COVERAGE_LABELS,
                'coverage_colors':   COVERAGE_COLORS,
                'priority_colors':   PRIORITY_COLORS,
                'chart_data':        json.dumps(chart_data),
                'compliance_score':  compliance_score,
                # AI quality block — parallel to comparison workspace
                'ai_quality_score':  ai_quality_score,
                'verified_count':    verified_count,
                'verified_pct':      verified_pct,
                'unverified_count':  total - verified_count,
                'unverified_pct':    100 - verified_pct,
                'avg_hall':          round(avg_hall, 2),
                'avg_hall_pct':      round(avg_hall * 100),
                'high_risk_count':   high_risk_count,
                'total_obligations': total,
                # carousel state initializers — JSON-serialised so Alpine
                # can read them with a one-liner instead of looping in the
                # template
                'ob_counts_json':    json.dumps(ob_counts_per_reg),
                'gap_counts_json':   json.dumps(gap_counts_per_reg),
            })

            # Resolve chunk_ids to their *actual* source Document. When auto-
            # routing pulls a chunk from a sibling regulation in the same
            # jurisdiction, om.regulation_id points at the user-selected
            # Document, not the chunk's true origin — so opening the doc
            # viewer at om.regulation can fail to find the verbatim quote.
            # We look the chunk_ids up in chroma metadata once and stuff
            # the resolved Document pk onto each mapping for the template.
            chunk_ids: set = set()
            for m in mappings:
                if m.regulation_chunk_id:
                    chunk_ids.add(m.regulation_chunk_id)
                if m.policy_chunk_id:
                    chunk_ids.add(m.policy_chunk_id)

            chunk_to_title: dict = {}
            if chunk_ids:
                # Open ChromaDB directly — going through retriever._get_service
                # forces a SentenceTransformer load (~10s cold start) just to
                # read metadata. We only need doc_title from the chunk
                # metadata; no embeddings, no querying.
                try:
                    import chromadb
                    from config import CHROMA_DIR, CHROMA_COLLECTION
                    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
                    col = client.get_or_create_collection(
                        CHROMA_COLLECTION, metadata={'hnsw:space': 'cosine'},
                    )
                    res = col.get(ids=list(chunk_ids), include=['metadatas'])
                    for cid, md in zip(res.get('ids') or [], res.get('metadatas') or []):
                        if md and md.get('doc_title'):
                            chunk_to_title[cid] = md['doc_title']
                except Exception:
                    # ChromaDB unreachable or collection mismatch — fall back
                    # to using each mapping's stored regulation_id; the doc
                    # viewer's links won't be 100% chunk-accurate but the
                    # workspace still renders fully.
                    chunk_to_title = {}

            title_to_doc: dict = {}
            if chunk_to_title:
                from pathlib import Path
                wanted_titles = set(chunk_to_title.values())
                for d in Document.objects.filter(status=Document.INDEXED):
                    if d.chunk_doc_title in wanted_titles:
                        title_to_doc[d.chunk_doc_title] = d

            for m in mappings:
                reg_t = chunk_to_title.get(m.regulation_chunk_id)
                m.actual_regulation_doc = title_to_doc.get(reg_t) or m.regulation
                pol_t = chunk_to_title.get(m.policy_chunk_id)
                m.actual_policy_doc = title_to_doc.get(pol_t) or analysis.policy_doc
            for g in gaps:
                om = g.obligation_mapping
                reg_t = chunk_to_title.get(om.regulation_chunk_id)
                om.actual_regulation_doc = title_to_doc.get(reg_t) or om.regulation
                pol_t = chunk_to_title.get(om.policy_chunk_id)
                om.actual_policy_doc = title_to_doc.get(pol_t) or analysis.policy_doc
        return render(request, 'pages/mapping_workspace.html', ctx)


# ── HTMX partials & actions ───────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class EvidencePanelView(View):
    """GET /mapping/evidence/<pk>/ — HTMX inline evidence panel."""

    def get(self, request, pk):
        mapping = get_object_or_404(
            ObligationMapping.objects.select_related('regulation', 'analysis__policy_doc'),
            pk=pk,
        )
        return render(request, 'partials/_evidence_panel.html', {
            'mapping':         mapping,
            'coverage_labels': COVERAGE_LABELS,
            'coverage_colors': COVERAGE_COLORS,
        })


@method_decorator(role_required('analyst'), name='dispatch')
class CoverageOverrideView(View):
    """POST /mapping/obligation/<pk>/override/ — cycle coverage state."""

    def post(self, request, pk):
        om = get_object_or_404(ObligationMapping, pk=pk)
        current = om.coverage if om.coverage in COVERAGE_CYCLE else COVERAGE_CYCLE[-1]
        om.coverage = COVERAGE_CYCLE[(COVERAGE_CYCLE.index(current) + 1) % len(COVERAGE_CYCLE)]
        om.human_override = True
        om.save(update_fields=['coverage', 'human_override'])
        fg, bg = COVERAGE_COLORS[om.coverage]
        return render(request, 'partials/_coverage_badge.html', {
            'om': om, 'fg': fg, 'bg': bg, 'lbl': COVERAGE_LABELS[om.coverage],
        })


@method_decorator(role_required('reviewer', 'admin'), name='dispatch')
class GapRemediationSaveView(View):
    """POST /mapping/gap/<pk>/save/ — save remediation text + (optional) due_date.

    Reviewer-only. The analyst sees the AI-suggested remediation read-only;
    the reviewer is the one with authority to refine the text and to set an
    explicit due date (overriding the severity-derived default the exporter
    would otherwise compute).
    """

    def post(self, request, pk):
        from datetime import datetime
        gap = get_object_or_404(Gap, pk=pk)
        text     = request.POST.get('remediation_text', '').strip()
        due_raw  = (request.POST.get('due_date') or '').strip()
        update_fields = ['remediation_text', 'remediation_source']

        gap.remediation_text   = text
        gap.remediation_source = Gap.HUMAN

        # Due date is optional. Empty string clears it; otherwise parse a
        # YYYY-MM-DD string (the HTML date input format).
        if 'due_date' in request.POST:
            if due_raw:
                try:
                    gap.due_date = datetime.strptime(due_raw, '%Y-%m-%d').date()
                except ValueError:
                    pass  # bad input — leave existing due_date alone
            else:
                gap.due_date = None
            update_fields.append('due_date')

        gap.save(update_fields=update_fields)

        try:
            from apps.history.audit import log_event
            log_event(
                request.user, 'review.modify',
                request=request,
                target_type='mapping.Gap', target_id=gap.pk,
                description=f'{request.user.username} edited remediation for gap #{gap.pk}',
                metadata={'gap_id': gap.pk, 'source': source, 'len': len(text)},
            )
        except Exception:
            pass

        return render(request, 'partials/_remediation_tag.html', {'gap': gap})


@method_decorator(role_required('reviewer', 'admin'), name='dispatch')
class ObligationSeverityOverrideView(View):
    """POST /mapping/obligation/<pk>/severity/ — set severity (HTMX).

    Reviewer-only. The AI's `derive_severity()` result is the default the
    analyst sees; only the reviewer can promote/demote it before validation.
    `human_override=True` flags this row as reviewer-adjusted in the audit
    trail and the exported artifacts.

    Returns the same 4-button row, re-rendered with the new active state,
    so the form is replaceable in-place via hx-swap="outerHTML".
    """

    def post(self, request, pk):
        om = get_object_or_404(ObligationMapping, pk=pk)
        sev = (request.POST.get('severity') or '').strip().lower()
        valid = {
            ObligationMapping.CRITICAL,
            ObligationMapping.HIGH,
            ObligationMapping.MEDIUM,
            ObligationMapping.LOW,
        }
        if sev not in valid:
            return HttpResponseBadRequest('Invalid severity')

        om.severity       = sev
        om.human_override = True
        om.save(update_fields=['severity', 'human_override'])

        try:
            from apps.history.audit import log_event
            log_event(
                request.user, 'review.modify',
                request=request,
                target_type='mapping.ObligationMapping', target_id=om.pk,
                description=f'{request.user.username} set severity={sev} on obligation #{om.pk}',
                metadata={'obligation_id': om.pk, 'severity': sev},
            )
        except Exception:
            pass

        return render(request, 'partials/_severity_picker.html', {'item': om})


@method_decorator(role_required('analyst'), name='dispatch')
class GapAISuggestView(View):
    """POST /mapping/gap/<pk>/suggest/ — generate AI remediation suggestion on demand."""

    _PROMPT = (
        'Gap: {missing}\n'
        'Regulation: {article} — {obligation}\n\n'
        'Write 2 sentences: what internal procedure or control should the bank create or update '
        'to fix this gap? Start with a verb. Do not repeat the gap text.\n'
        'Action:'
    )

    def post(self, request, pk):
        gap = get_object_or_404(
            Gap.objects.select_related('obligation_mapping'),
            pk=pk,
        )
        om = gap.obligation_mapping
        prompt = self._PROMPT.format(
            obligation=om.obligation_title[:300],
            article=om.article_ref[:100],
            missing=om.evidence_text[:300] if om.evidence_text else 'Not specified',
        )
        suggestion = ''
        error = ''
        try:
            import requests as _req, json as _json
            from config import OLLAMA_URL
            resp = _req.post(
                f'{OLLAMA_URL}/api/generate',
                json={'model': 'llama3.2:latest', 'prompt': prompt, 'stream': True,
                      'options': {'temperature': 0.3, 'num_predict': 150}},
                stream=True,
                timeout=(10, 90),
            )
            resp.raise_for_status()
            parts = []
            for line in resp.iter_lines():
                if not line:
                    continue
                obj = _json.loads(line)
                parts.append(obj.get('response', ''))
                if obj.get('done'):
                    break
            suggestion = ''.join(parts).strip().strip('"\'')
        except Exception as exc:
            logger.error('AI suggest failed for gap %s: %s', pk, exc)
            error = str(exc)

        if suggestion:
            gap.remediation_text   = suggestion
            gap.remediation_source = Gap.AI_DRAFTED
            gap.save(update_fields=['remediation_text', 'remediation_source'])

        from django.http import JsonResponse
        return JsonResponse({'suggestion': suggestion, 'error': error})


@method_decorator(role_required('analyst'), name='dispatch')
class SendToReviewView(View):
    """POST /mapping/<pk>/send-to-review/ — analyst hand-off.

    Mirrors comparison's SubmitForReviewView: captures an optional analyst
    note, stamps `submitted_for_review_at` + `submitted_by`, transitions the
    analysis to REVIEW so the reviewer queue picks it up, and audits the
    event. Idempotent — re-submitting just refreshes the note + timestamp.
    """

    def post(self, request, pk):
        analysis = get_object_or_404(MappingAnalysis, pk=pk)
        note = (request.POST.get('analyst_note') or '').strip()[:2000]

        analysis.status                  = MappingAnalysis.REVIEW
        analysis.analyst_note            = note
        analysis.submitted_for_review_at = timezone.now()
        analysis.submitted_by            = request.user if request.user.is_authenticated else None
        analysis.save(update_fields=[
            'status', 'analyst_note', 'submitted_for_review_at', 'submitted_by',
        ])

        try:
            from apps.history.audit import log_event, Actions
            log_event(
                request.user, Actions.REVIEW_SUBMIT,
                target_type='mapping.MappingAnalysis', target_id=analysis.pk,
                request=request,
                description=f'{request.user.username} sent mapping #{analysis.pk} to reviewer',
                metadata={
                    'analysis_id': analysis.pk,
                    'policy':      analysis.policy_doc.name,
                    'note_len':    len(note),
                },
            )
        except Exception:
            pass

        # Pending-review badge in the sidebar reads from a 30 s cache; bust
        # so the reviewer sees the new item immediately on their next nav.
        try:
            from django.core.cache import cache
            cache.delete('nav_counts')
        except Exception:
            pass

        if request.headers.get('HX-Request'):
            response = HttpResponse()
            response['HX-Redirect'] = '/review/'
            return response
        return redirect('review')


@method_decorator(role_required(*REVIEW_ROLES), name='dispatch')
class ValidateAnalysisView(View):
    """POST /mapping/<pk>/validate/ — mark analysis as approved + cascade.

    Validation is the reviewer's single action that turns an entire mapping
    into auditable evidence. Cascading effects so all downstream consumers
    see a consistent state:

      1. MappingAnalysis.status        -> APPROVED
      2. Every ObligationMapping under it that's still draft / reviewed
         -> lifecycle = APPROVED   (so the review queue clears, the Copilot's
         approved-data feed picks them up, and analytics treats them as
         signed-off evidence rather than draft AI output).
      3. Audit-log entry for the cascade so the trail is explicit.
      4. Cache bust on the Copilot's approved-data cache key so a follow-up
         user question reads the new approved set.
    """

    def post(self, request, pk):
        analysis = get_object_or_404(MappingAnalysis, pk=pk)
        cascaded = 0
        if analysis.status in (MappingAnalysis.COMPLETE, MappingAnalysis.REVIEW):
            analysis.status = MappingAnalysis.APPROVED
            analysis.save(update_fields=['status'])

            # Flip every still-draft / reviewed obligation under this analysis
            # to APPROVED. Already-rejected rows stay rejected (the reviewer
            # may have flagged them individually before bulk-validating).
            cascaded = ObligationMapping.objects.filter(
                analysis=analysis,
                lifecycle__in=[
                    ObligationMapping.DRAFT,
                    ObligationMapping.REVIEWED,
                ],
            ).update(
                lifecycle=ObligationMapping.APPROVED,
                human_override=True,
            )

            try:
                from apps.history.audit import log_event
                log_event(
                    request.user, 'review.accept',
                    request=request,
                    target_type='mapping.MappingAnalysis', target_id=analysis.pk,
                    description=(f'{request.user.username} validated mapping #{analysis.pk}'
                                 f' ({cascaded} obligation(s) flipped to approved)'),
                    metadata={
                        'analysis_id': analysis.pk,
                        'policy':      analysis.policy_doc.name,
                        'rows_approved_via_cascade': cascaded,
                    },
                )
            except Exception:
                pass

            # Bust the sidebar badge cache so "Pending review" updates without
            # waiting for the 30 s TTL. Copilot retrieval is already live (no
            # cache layer over the approved-data queries), so an in-flight
            # question after Validate reflects the cascade automatically.
            try:
                from django.core.cache import cache
                cache.delete('nav_counts')
            except Exception:
                pass
        # Force the workspace to fully refresh after validate so the user
        # sees the cascaded state: status badge flips to Approved, the
        # Validate button disappears, and the Download package button
        # finally appears (it's gated on status == 'approved'). Without
        # this, HTMX would only swap the validate button in-place and the
        # rest of the page stayed stale — the user had to reload manually.
        if request.headers.get('HX-Request'):
            resp = HttpResponse('')
            resp['HX-Refresh'] = 'true'
            return resp
        return redirect('mapping-workspace', pk=pk)


@method_decorator(role_required(*REVIEW_ROLES), name='dispatch')
class ObligationMappingTransitionView(View):
    """POST /mapping/obligation/<pk>/transition/ — approve or reject a single ObligationMapping."""

    def post(self, request, pk):
        obj = get_object_or_404(ObligationMapping, pk=pk)
        action = request.POST.get('action', '')
        old_lifecycle = obj.lifecycle
        if action == 'approved':
            obj.lifecycle = ObligationMapping.APPROVED
        elif action == 'rejected':
            obj.lifecycle = ObligationMapping.REJECTED
        elif action == 'reset':
            obj.lifecycle = ObligationMapping.DRAFT
        note = request.POST.get('note', '').strip()
        if note:
            obj.reviewer_notes = note
        obj.save(update_fields=['lifecycle', 'reviewer_notes'])

        from apps.history.audit import log_event, Actions
        action_map = {
            'approved': Actions.REVIEW_ACCEPT,
            'rejected': Actions.REVIEW_REJECT,
        }
        audit_action = action_map.get(action, Actions.REVIEW_MODIFY)
        log_event(
            request.user, audit_action,
            request=request,
            target_type='mapping.ObligationMapping', target_id=obj.pk,
            description=f'{request.user.username} {action or "modified"} obligation mapping #{obj.pk}',
            metadata={'from_lifecycle': old_lifecycle, 'to_lifecycle': obj.lifecycle},
        )

        # Per-row transitions can change the analysis-level ReviewItem state
        # downstream — bust nav_counts so badges don't lag 30 s.
        try:
            from django.core.cache import cache
            cache.delete('nav_counts')
        except Exception:
            pass

        from django.template.loader import render_to_string
        html = render_to_string('partials/_review_mapping_card.html', {'item': obj})
        return HttpResponse(html)


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class MappingProgressAPIView(View):
    """GET /mapping/<pk>/progress/ — JSON progress for the running screen."""

    def get(self, request, pk):
        analysis = get_object_or_404(MappingAnalysis, pk=pk)
        return JsonResponse({
            'status':   analysis.status,
            'pct':      analysis.progress_pct,
            'current':  analysis.progress_current,
            'total':    analysis.progress_total,
            'label':    analysis.current_obligation_label,
        })


# ── Results-first coverage flow ──────────────────────────────────────────────
# A separate surface from the setup→running→workspace flow above. Instead of
# hand-picking regulations, the analyst opens a policy's coverage page: scope
# is auto-derived (whole corpus, topic-intersected), the pair count is shown
# BEFORE any model runs, and results lead with gaps + a topic rollup. Skipped
# topics (policy covers, no in-scope law legislates) are shown as skipped,
# never as gaps.

def _coverage_jurisdictions(request):
    """Optional ?jur=bahrain&jur=india scope restriction. Empty → whole corpus."""
    jl = [j.strip().lower() for j in request.GET.getlist('jur') if j.strip()]
    return jl or None


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class PolicyCoverageView(View):
    """GET /mapping/coverage/<pk>/ — results-first coverage for one policy."""

    def get(self, request, pk):
        policy = get_object_or_404(
            Document, pk=pk, doc_type=Document.POLICY, status=Document.INDEXED,
        )
        jl = _coverage_jurisdictions(request)

        from apps.mapping.scope import compute_scope
        scope = compute_scope(policy, jurisdictions=jl)

        # Latest run + any in-flight run for this policy.
        latest = (
            MappingAnalysis.objects
            .filter(policy_doc=policy,
                    status__in=[MappingAnalysis.COMPLETE, MappingAnalysis.REVIEW,
                                MappingAnalysis.APPROVED])
            .order_by('-completed_at', '-run_at')
            .first()
        )
        running = (
            MappingAnalysis.objects
            .filter(policy_doc=policy,
                    status__in=[MappingAnalysis.RUNNING, MappingAnalysis.QUEUED])
            .order_by('-run_at')
            .first()
        )

        coverage = None
        if latest:
            from apps.mapping.coverage import build_coverage
            coverage = build_coverage(latest)

        # Available jurisdictions for the adjust-scope drawer.
        jur_available = sorted({
            d.jurisdiction for d in Document.objects.filter(
                doc_type=Document.REGULATION, status=Document.INDEXED)
            if d.jurisdiction
        })

        return render(request, 'pages/mapping/coverage.html', {
            'policy':        policy,
            'scope':         scope,
            'summary':       scope.summary,
            'coverage':      coverage,
            'latest':        latest,
            'running':       running,
            'selected_jurs': jl or [],
            'jur_available': jur_available,
            'coverage_labels': COVERAGE_LABELS,
        })


@method_decorator(role_required('analyst'), name='dispatch')
class CoverageRunView(View):
    """POST /mapping/coverage/<pk>/run/ — auto-scope run for the coverage page.

    Scope is derived, not picked: every indexed regulation (optionally
    jurisdiction-filtered) becomes a candidate, and the per-topic auto-router
    drops everything the policy doesn't legislate on. No checkbox grid."""

    def post(self, request, pk):
        policy = get_object_or_404(
            Document, pk=pk, doc_type=Document.POLICY, status=Document.INDEXED,
        )
        jl = [j.strip().lower() for j in request.POST.getlist('jur') if j.strip()] or None

        reg_qs = Document.objects.filter(
            doc_type=Document.REGULATION, status=Document.INDEXED)
        if jl:
            reg_qs = reg_qs.filter(jurisdiction__in=jl)
        if not reg_qs.exists():
            from django.contrib import messages
            messages.warning(request, 'No indexed regulations in the selected scope.')
            return redirect('policy-coverage', pk=pk)

        if not _ollama_is_reachable():
            from django.contrib import messages
            messages.error(request, 'Ollama is not running. Start Ollama and try again.')
            return redirect('policy-coverage', pk=pk)

        # Reuse the same live-run guard as MappingRunView so two runs for the
        # same policy don't stack.
        existing = MappingAnalysis.objects.filter(
            policy_doc=policy,
            status__in=[MappingAnalysis.RUNNING, MappingAnalysis.QUEUED],
        ).first()
        if existing:
            return redirect('policy-coverage', pk=pk)

        analysis = MappingAnalysis.objects.create(
            policy_doc=policy,
            topic='auto',
            scope_mode=MappingAnalysis.SCOPE_AUTO,
            scope_topics=[],
            status=MappingAnalysis.RUNNING,
            created_by=request.user if request.user.is_authenticated else None,
        )
        analysis.regulations.set(list(reg_qs))

        try:
            from apps.history.audit import log_event, Actions
            log_event(
                request.user, Actions.MAPPING_RUN, request=request,
                target_type='mapping.MappingAnalysis', target_id=analysis.pk,
                description=f'{getattr(request.user, "username", "user")} ran coverage for {policy.name}',
                metadata={'policy': policy.name, 'scope_mode': 'auto',
                          'jurisdictions': jl or 'all'},
            )
        except Exception:
            pass

        import threading
        from django.db import close_old_connections

        def _thread_target(aid):
            close_old_connections()
            try:
                _run_mapping_job(aid)
            finally:
                close_old_connections()

        threading.Thread(target=_thread_target, args=(analysis.pk,), daemon=True).start()
        return redirect('policy-coverage', pk=pk)


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class CoverageClassifyView(View):
    """POST /mapping/coverage/<pk>/classify/ — classify this policy's sections
    now so the scope preview is populated before a run."""

    def post(self, request, pk):
        policy = get_object_or_404(
            Document, pk=pk, doc_type=Document.POLICY, status=Document.INDEXED,
        )
        try:
            from apps.library.classification import classify_document_async
            classify_document_async(policy.pk)
        except Exception:
            logger.exception('coverage classify launch failed for %s', pk)
        return redirect('policy-coverage', pk=pk)


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class CoverageStatusAPIView(View):
    """GET /mapping/coverage/<pk>/status/ — JSON for the coverage page poller.

    Reports both the classification lifecycle and any in-flight run so the
    page can move itself from classifying → ready → running → done without a
    manual refresh."""

    def get(self, request, pk):
        policy = get_object_or_404(Document, pk=pk, doc_type=Document.POLICY)
        run = (MappingAnalysis.objects
               .filter(policy_doc=policy,
                       status__in=[MappingAnalysis.RUNNING, MappingAnalysis.QUEUED])
               .order_by('-run_at').first())
        return JsonResponse({
            'classification_state': policy.classification_state,
            'run_status': run.status if run else None,
            'run_pct':    run.progress_pct if run else None,
            'run_label':  run.current_obligation_label if run else '',
        })


# ── Dual-regulation policy mapping ──────────────────────────────────────────
# "Compare BBK's policy against Bahrain PDPL AND India DPDPA at the same time."
# Runs reasoning.workflows.map_policy_coverage() twice (once per jurisdiction)
# and renders the two coverage tables side by side. This is one-shot and
# in-memory — no DB persistence, since the use case is exploration. If the
# analyst wants to save findings they can run the regular Mapping flow.

@method_decorator(role_required('reviewer', 'admin'), name='dispatch')
class GapAssignView(View):
    """POST /mapping/gap/<pk>/assign/ — assign a gap to a user with a due date.

    Reviewer/admin only — analysts shouldn't be re-assigning their own work.
    Sends a notification to the assignee via apps.notifications.services so
    the assigned user sees it in their inbox immediately.
    """
    def post(self, request, pk):
        from datetime import datetime
        from django.contrib.auth import get_user_model
        gap = get_object_or_404(Gap, pk=pk)
        User = get_user_model()

        # blank assignee_id == clear the assignment
        assignee_id = (request.POST.get('assignee_id') or '').strip()
        due_str     = (request.POST.get('due_date')   or '').strip()

        if not assignee_id:
            old_assignee = gap.assigned_to
            gap.assigned_to = None
            gap.assigned_by = None
            gap.assigned_at = None
            gap.due_date    = None
            gap.save(update_fields=['assigned_to', 'assigned_by', 'assigned_at', 'due_date'])
            try:
                from apps.history.audit import log_event, Actions
                log_event(request.user, getattr(Actions, 'GAP_UNASSIGN', 'mapping.gap_unassign'),
                          target_type='mapping.Gap', target_id=gap.pk, request=request,
                          description=f'Gap {gap.obligation_mapping.article_ref} unassigned',
                          metadata={'previous_assignee': old_assignee.username if old_assignee else None})
            except Exception:
                pass
            return JsonResponse({'ok': True, 'assigned': False})

        try:
            assignee = User.objects.get(pk=int(assignee_id))
        except (User.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Invalid assignee'}, status=400)

        due_date = None
        if due_str:
            try:
                due_date = datetime.strptime(due_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Invalid date format (use YYYY-MM-DD)'}, status=400)

        gap.assigned_to = assignee
        gap.assigned_by = request.user
        gap.assigned_at = timezone.now()
        gap.due_date    = due_date
        gap.save(update_fields=['assigned_to', 'assigned_by', 'assigned_at', 'due_date'])

        # audit
        try:
            from apps.history.audit import log_event, Actions
            log_event(request.user, getattr(Actions, 'GAP_ASSIGN', 'mapping.gap_assign'),
                      target_type='mapping.Gap', target_id=gap.pk, request=request,
                      description=f'Gap {gap.obligation_mapping.article_ref} assigned to {assignee.username}',
                      metadata={'assignee': assignee.username,
                                'due_date': due_date.isoformat() if due_date else None,
                                'priority': gap.priority})
        except Exception:
            pass

        return JsonResponse({
            'ok':       True,
            'assigned': True,
            'assignee': {'id': assignee.pk, 'name': assignee.get_full_name() or assignee.username},
            'due_date': due_date.isoformat() if due_date else None,
        })


@method_decorator(role_required('analyst'), name='dispatch')
class DualMappingView(View):
    """GET/POST /mapping/dual/ — policy vs two regulations at once."""

    def get(self, request):
        topic = (request.GET.get('topic') or '').strip()
        jurs  = request.GET.getlist('jurs')
        # default to Bahrain + India when first loaded
        if not jurs:
            jurs = ['Bahrain', 'India']
        # cap at 2 sides — this view is explicitly dual, not n-way
        jurs = jurs[:2]

        report_a = report_b = None
        error    = None

        if topic and len(topic) >= 3 and len(jurs) == 2:
            try:
                from reasoning.workflows import map_policy_coverage
                report_a = map_policy_coverage(topic, jurisdiction=jurs[0], top_k=4, rerank=True)
                report_b = map_policy_coverage(topic, jurisdiction=jurs[1], top_k=4, rerank=True)
            except Exception as exc:
                import traceback; traceback.print_exc()
                error = f'Mapping failed: {exc}'

        # bundle reports + meta into a list so the template can iterate cleanly
        # ({% for r in report_a,report_b %} isn't valid Django template syntax).
        reports = []
        if report_a is not None:
            reports.append({'side': 'A', 'jurisdiction': jurs[0], 'report': report_a})
        if report_b is not None:
            reports.append({'side': 'B', 'jurisdiction': jurs[1], 'report': report_b})

        return render(request, 'pages/mapping_dual.html', {
            'topic':    topic,
            'jurs':     jurs,
            'jur_options': [
                ('Bahrain', 'Bahrain (PDPL)'),
                ('India',   'India (DPDPA)'),
                ('Kuwait',  'Kuwait (DPPR)'),
            ],
            'reports':  reports,
            'error':    error,
        })


# ── Approved-package exports ──────────────────────────────────────────────────
#
# Two artifacts the reviewer / DPO can hand off downstream:
#   exec-summary.pdf  → board-pack one-pager
#   gap-register.xlsx → flat register the DPO drops into the GRC tracker
#
# Available ONLY after reviewer validation (status = APPROVED). Earlier
# states are still drafts — exporting before sign-off would let pre-decision
# numbers escape into the GRC tracker / board pack and undermine the
# audit-traceable evidence story.
# Downloads write an audit row so we know who pulled what artifact when.

_DECIDED_STATES = (MappingAnalysis.APPROVED,)


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class MappingExecSummaryView(View):
    """GET /mapping/<pk>/exports/exec-summary.pdf — executive-summary PDF."""

    def get(self, request, pk):
        analysis = get_object_or_404(MappingAnalysis, pk=pk)
        if analysis.status not in _DECIDED_STATES:
            return HttpResponseBadRequest(
                'Exports are only available after the mapping has been validated by a reviewer.'
            )
        from apps.review.exports import build_executive_summary_pdf, audit_hash
        data = build_executive_summary_pdf(analysis)
        try:
            from apps.history.audit import log_event
            log_event(
                request.user, 'exports.downloaded',
                request=request,
                target_type='mapping.MappingAnalysis', target_id=analysis.pk,
                description=f'{request.user.username} downloaded exec summary for mapping #{analysis.pk}',
                metadata={'format': 'pdf', 'audit_hash': audit_hash(analysis),
                          'analysis_id': analysis.pk},
            )
        except Exception:
            pass
        slug = analysis.policy_doc.name[:60].replace(' ', '_').replace('/', '_')
        response = HttpResponse(data, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="exec-summary_{slug}.pdf"'
        return response


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class MappingGapRegisterView(View):
    """GET /mapping/<pk>/exports/gap-register.xlsx — gap register XLSX."""

    def get(self, request, pk):
        analysis = get_object_or_404(MappingAnalysis, pk=pk)
        if analysis.status not in _DECIDED_STATES:
            return HttpResponseBadRequest(
                'Exports are only available after the mapping has been validated by a reviewer.'
            )
        from apps.review.exports import build_gap_register_xlsx, audit_hash
        data = build_gap_register_xlsx(analysis)
        try:
            from apps.history.audit import log_event
            log_event(
                request.user, 'exports.downloaded',
                request=request,
                target_type='mapping.MappingAnalysis', target_id=analysis.pk,
                description=f'{request.user.username} downloaded gap register for mapping #{analysis.pk}',
                metadata={'format': 'xlsx', 'audit_hash': audit_hash(analysis),
                          'analysis_id': analysis.pk},
            )
        except Exception:
            pass
        slug = analysis.policy_doc.name[:60].replace(' ', '_').replace('/', '_')
        response = HttpResponse(
            data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="gap-register_{slug}.xlsx"'
        return response
