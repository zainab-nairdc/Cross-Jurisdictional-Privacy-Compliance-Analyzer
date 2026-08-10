"""
views.py — Page views for the V2 Comparison Workspace (4 screens).
"""
import json
import os
import subprocess
import sys
import traceback

from django.shortcuts import render, get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.views import View
from django.http import HttpResponse, HttpResponseBadRequest

from apps.accounts.decorators import role_required, RoleRequiredMixin
from apps.library.models import Document
from apps.comparison.models import (
    ComparisonAnalysis, ClausePair,
    ComparisonRun, ComparisonResult, AuditEvent,
    PAIR_CONFIGS,
)

ALL_ROLES = ('analyst', 'reviewer', 'admin')


# ── Helpers ────────────────────────────────────────────────────────────────────

# Canonical privacy regulation PKs — the primary data-protection law per jurisdiction.
# These prevent _get_reg() from accidentally picking a more-recently-indexed non-PDPL doc.
CANONICAL_REGS = {
    'bahrain': 75,   # Personal Data Protection Law 30/2018
    'india':   88,   # Digital Personal Data Protection Act 2023
    'kuwait':  95,   # Data Privacy Protection Regulation Administrative Decision 26/2024
}


def _get_reg(jurisdiction: str, preferred_pk: int = None):
    qs = Document.objects.filter(
        jurisdiction=jurisdiction,
        doc_type=Document.REGULATION,
        status=Document.INDEXED,
        superseded=False,          # only the in-force version, never a repealed one
    )
    if preferred_pk:
        doc = qs.filter(pk=preferred_pk).first()
        if doc:
            return doc
    canonical_pk = CANONICAL_REGS.get(jurisdiction)
    if canonical_pk:
        doc = qs.filter(pk=canonical_pk).first()
        if doc:
            return doc
    return qs.first()


def _all_regs(jurisdiction: str):
    """In-force indexed regulations for a jurisdiction, for user selection.
    Superseded versions are excluded so no one compares against a repealed law."""
    return list(Document.objects.filter(
        jurisdiction=jurisdiction,
        doc_type=Document.REGULATION,
        status=Document.INDEXED,
        superseded=False,
    ).order_by('name'))


def _map_relationship(equivalence: str, stricter: str, llm_similarity: int = -1, llm_confidence: int = -1) -> tuple:
    """Return (relationship, confidence, similarity_score).

    llm_similarity:  0-100 score from the LLM prompt (-1 = not provided).
    llm_confidence:  0-100 AI-generated confidence score (-1 = not provided).
    When available these override hard-coded defaults.
    """
    e  = equivalence.strip().lower()
    sj = (stricter or '').strip().lower()

    def _sim(default: float) -> float:
        if 0 <= llm_similarity <= 100:
            return round(llm_similarity / 100, 2)
        return default

    def _conf(default: float) -> float:
        if 0 <= llm_confidence <= 100:
            return round(llm_confidence / 100, 2)
        return default

    if e == 'equivalent':
        return 'equivalent', _conf(0.92), _sim(0.90)

    if e == 'partially equivalent':
        if 'a' in sj and 'b' not in sj:
            return 'stricter_in_a', _conf(0.82), _sim(0.78)
        if 'b' in sj and 'a' not in sj:
            return 'stricter_in_b', _conf(0.82), _sim(0.78)
        return 'equivalent', _conf(0.76), _sim(0.80)

    if e == 'different':
        if 'a' in sj and 'b' not in sj:
            return 'stricter_in_a', _conf(0.74), _sim(0.62)
        if 'b' in sj and 'a' not in sj:
            return 'stricter_in_b', _conf(0.74), _sim(0.62)
        return 'conflicting', _conf(0.65), _sim(0.45)

    if e == 'conflicting':
        return 'conflicting', _conf(0.68), _sim(0.28)

    if e in ('only in a', 'only_in_a'):
        return 'additional_in_a', _conf(0.92), _sim(0.05)

    if e in ('only in b', 'only_in_b'):
        return 'additional_in_b', _conf(0.92), _sim(0.05)

    return 'conflicting', _conf(0.55), _sim(0.35)


def _detect_principles(text: str) -> list:
    """Light-weight taxonomy probe over the obligation text.

    The Topic Map (RunTopicMapView) now groups results by the **taxonomy
    topic of the chunks each obligation cited** — that's the source of
    truth. This function is kept as a cheap fallback that picks taxonomy
    topic tags whose human label (or key tokens) appear in the obligation
    text. Used to seed ``ComparisonResult.principle_ids`` so legacy
    consumers (review queue filters, exports) still see *some* tag.
    """
    if not text:
        return []
    from reasoning import taxonomy as _tx
    text_lc = text.lower()
    out: list[str] = []
    for tag, body in _tx.TAXONOMY.items():
        # tag tokens (snake_case → words) + the human label
        label_lc = body.get('label', '').lower()
        tokens = tag.replace('_', ' ').lower()
        if tokens in text_lc or any(w in text_lc for w in label_lc.split() if len(w) > 3):
            out.append(tag)
    return out


def _ollama_is_reachable() -> bool:
    import urllib.request
    try:
        from config import OLLAMA_URL
        urllib.request.urlopen(f'{OLLAMA_URL}/api/tags', timeout=3)
        return True
    except Exception:
        return False


def _launch_subprocess(command: str, *args: str) -> None:
    import logging, pathlib
    _log = logging.getLogger(__name__)
    from django.conf import settings
    base = pathlib.Path(settings.BASE_DIR)          # …/cjpca
    project_root = str(base.parent)                 # …/  (contains reasoning/)
    manage_py = str(base / 'manage.py')
    env = os.environ.copy()
    env.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
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
    _log.info('Launched subprocess pid=%s command=%s args=%s log=%s', proc.pid, command, args, log_path)


def _run_comparison_background(
    run_pk: int,
    include_orphans: bool = False,
    articles_a: list = None,
    articles_b: list = None,
) -> None:
    """Runs the AI comparison in a background thread."""
    from django.db import close_old_connections
    close_old_connections()

    run = ComparisonRun.objects.get(pk=run_pk)
    try:
        import sys
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[3]
        # Add project root so reasoning/ and retrieval/ are importable
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        # Add venv site-packages — needed when server runs without venv activated
        venv_site = project_root / '.venv' / 'Lib' / 'site-packages'
        if venv_site.exists() and str(venv_site) not in sys.path:
            sys.path.insert(1, str(venv_site))
        from reasoning.workflows import compare_regulations

        # Human-readable topic labels for the retrieval query.
        # Concept IDs (snake_case) are mapped to legal terms the embedding model understands.
        _CONCEPT_QUERIES = {
            'data_minimization':   'data minimization collection limitation relevant data only',
            'purpose_limitation':  'purpose limitation specified purpose lawful processing',
            'consent':             'consent data subject consent explicit consent withdrawal',
            'data_subject_rights': 'data subject rights access rectification erasure objection portability',
            'breach_notification': 'data breach notification personal data breach security incident',
            'data_retention':      'data retention storage limitation retention period deletion',
            'cross_border':        'cross border transfer international transfer adequacy decision',
            'accountability':      'accountability data protection officer DPO responsibility record keeping',
            'security':            'security measures technical organizational measures safeguards',
            'sensitive_data':      'sensitive personal data special categories health race biometric',
            'children':            'children minors parental consent age verification',
            'automated_decisions': 'automated decision making profiling AI decision',
        }

        if articles_a and articles_b:
            query = f'specific articles: {", ".join(articles_a)} vs {", ".join(articles_b)}'
        elif run.topics:
            query = [_CONCEPT_QUERIES.get(t, t.replace('_', ' ')) for t in run.topics]
        else:
            # Full comparison — retrieve each concept separately for diverse coverage
            query = list(_CONCEPT_QUERIES.values())

        query_preview = query if isinstance(query, str) else f'{len(query)} concepts'
        print(f'[comparison v2] starting run #{run_pk}: {str(query_preview)[:80]}...')

        # Pass the chunk_doc_title (file stem) — NOT the display name. The
        # ingestion pipeline writes the file stem as chunk metadata.doc_title,
        # so retrieval has to filter on the same string. Display-name was the
        # original bug here: filter resolved to 0 chunks, workflow returned
        # 0 obligations, run completed silently with empty results.
        report = compare_regulations(
            query=query,
            reg_a=run.reg_a.jurisdiction,
            reg_b=run.reg_b.jurisdiction,
            doc_title_a=run.reg_a.chunk_doc_title or run.reg_a.name,
            doc_title_b=run.reg_b.chunk_doc_title or run.reg_b.name,
        )

        total = len(report.obligations)
        run.total_pairs = total
        run.save(update_fields=['total_pairs'])

        to_create = []
        for i, o in enumerate(report.obligations, 1):
            relationship, confidence, similarity = _map_relationship(
                o.equivalence, o.stricter_jurisdiction, o.similarity_score,
                llm_confidence=getattr(o, 'confidence_score', -1),
            )
            # Penalise confidence when the LLM citation could not be verified
            if not getattr(o, 'citation_verified', True):
                confidence = min(confidence, 0.45)
            text_blob = (o.reg_a_requirement or '') + ' ' + (o.reg_b_requirement or '')
            principles = _detect_principles(text_blob)

            to_create.append(ComparisonResult(
                run=run,
                citation_a=o.reg_a_citation or o.topic or f'Item {i}',
                citation_b=o.reg_b_citation or '',
                preview_a=(o.reg_a_requirement or '')[:300],
                preview_b=(o.reg_b_requirement or '')[:300],
                clause_text_a=o.reg_a_requirement or '',
                clause_text_b=o.reg_b_requirement or '',
                relationship=relationship,
                confidence=confidence,
                similarity_score=similarity,
                rationale=o.notes or '',
                key_difference=o.key_difference or '',
                lifecycle=ComparisonResult.DRAFT,
                principle_ids=principles,
                citation_verified=getattr(o, 'citation_verified', True),
                # reasoning-layer evidence + risk (added in the workflow migration)
                evidence_a=getattr(o, 'reg_a_evidence', '') or '',
                evidence_b=getattr(o, 'reg_b_evidence', '') or '',
                chunk_id_a=getattr(o, 'reg_a_chunk_id', '') or '',
                chunk_id_b=getattr(o, 'reg_b_chunk_id', '') or '',
                hallucination_risk=getattr(o, 'hallucination_risk', 0.0) or 0.0,
                practical_conclusion=getattr(o, 'practical_conclusion', '') or '',
                compliance_impact=getattr(o, 'compliance_impact', '') or '',
                shared_controls=getattr(o, 'shared_controls', []) or [],
                terminology_note=getattr(o, 'terminology_note', '') or '',
            ))

        # Orphan results for asymmetric topics
        if include_orphans:
            from apps.comparison.topic_scan import scan_topic_coverage
            try:
                scan = scan_topic_coverage(run.reg_a.pk, run.reg_b.pk)
                for t in scan.get('only_in_a', []):
                    to_create.append(ComparisonResult(
                        run=run,
                        citation_a=t['label'],
                        citation_b='',
                        preview_a=f'{t["label"]} — covered in {run.reg_a.name} ({t["articles"]} sections); not found in {run.reg_b.name}.',
                        preview_b='',
                        relationship=ComparisonResult.ADDITIONAL_IN_A,
                        confidence=0.85,
                        similarity_score=0.0,
                        rationale=f'This topic ({t["label"]}) is present in {run.reg_a.name} but not in {run.reg_b.name}.',
                        key_difference=f'{run.reg_a.name} addresses {t["label"]} explicitly; {run.reg_b.name} does not.',
                        lifecycle=ComparisonResult.DRAFT,
                        principle_ids=[t['principle_id']],
                    ))
                for t in scan.get('only_in_b', []):
                    to_create.append(ComparisonResult(
                        run=run,
                        citation_a='',
                        citation_b=t['label'],
                        preview_a='',
                        preview_b=f'{t["label"]} — covered in {run.reg_b.name} ({t["articles"]} sections); not found in {run.reg_a.name}.',
                        relationship=ComparisonResult.ADDITIONAL_IN_B,
                        confidence=0.85,
                        similarity_score=0.0,
                        rationale=f'This topic ({t["label"]}) is present in {run.reg_b.name} but not in {run.reg_a.name}.',
                        key_difference=f'{run.reg_b.name} addresses {t["label"]} explicitly; {run.reg_a.name} does not.',
                        lifecycle=ComparisonResult.DRAFT,
                        principle_ids=[t['principle_id']],
                    ))
            except Exception as e:
                print(f'[comparison v2] orphan scan failed: {e}')

        ComparisonResult.objects.bulk_create(to_create)
        run.completed_pairs = len(to_create)
        run.status = ComparisonRun.COMPLETE
        run.save(update_fields=['completed_pairs', 'status'])
        print(f'[comparison v2] run #{run_pk} complete: {len(to_create)} pairs')

        # Audit the terminal state. Best-effort: log_event already swallows
        # exceptions, but we belt-and-braces it because we are running in
        # a background subprocess and a stray traceback would just hit
        # stderr unnoticed.
        try:
            from apps.history.audit import log_event, Actions
            log_event(
                run.created_by, Actions.COMPARISON_COMPLETE,
                target_type='comparison.ComparisonRun', target_id=run.pk,
                description=f'Comparison run #{run.pk} complete: {len(to_create)} pairs',
                metadata={'pair_key': run.pair_key, 'completed_pairs': len(to_create)},
            )
        except Exception:
            pass

    except Exception as exc:
        traceback.print_exc()
        run.status = ComparisonRun.FAILED
        run.error_message = str(exc)[:1000]
        run.save(update_fields=['status', 'error_message'])
        print(f'[comparison v2] run #{run_pk} FAILED: {exc}')

        try:
            from apps.history.audit import log_event, Actions
            log_event(
                run.created_by, Actions.COMPARISON_FAILED,
                target_type='comparison.ComparisonRun', target_id=run.pk,
                description=f'Comparison run #{run.pk} failed: {str(exc)[:200]}',
                metadata={'pair_key': run.pair_key, 'error': str(exc)[:500]},
            )
        except Exception:
            pass


# ── Single combined landing — was Pair Picker, now serves the custom-scope
# picker. The country-pair tile landing was a duplicate entry point. The user
# wanted ONE comparison page using the search-driven picker UI, so /comparison/
# is now handled by PairPickerView (custom-scope flow inlined here).

@method_decorator(role_required('analyst', 'reviewer'), name='dispatch')
class PairPickerView(View):
    def get(self, request):
        all_regs = list(Document.objects.filter(
            doc_type=Document.REGULATION,
            status=Document.INDEXED,
        ).order_by('jurisdiction', 'name'))

        reg_a_pk = int(request.GET['reg_a_pk']) if request.GET.get('reg_a_pk') else None
        reg_b_pk = int(request.GET['reg_b_pk']) if request.GET.get('reg_b_pk') else None

        reg_a = Document.objects.filter(pk=reg_a_pk, doc_type=Document.REGULATION, status=Document.INDEXED).first() if reg_a_pk else None
        reg_b = Document.objects.filter(pk=reg_b_pk, doc_type=Document.REGULATION, status=Document.INDEXED).first() if reg_b_pk else None

        scan = None
        if reg_a and reg_b and reg_a.pk != reg_b.pk:
            from apps.comparison.topic_scan import scan_topic_coverage
            try:
                scan = scan_topic_coverage(reg_a.pk, reg_b.pk)
            except Exception:
                pass
        scan = scan or {'both_covered': [], 'only_in_a': [], 'only_in_b': [],
                        'total_estimated_pairs_full': 0, 'total_estimated_seconds_full': 60}

        same_jurisdiction = bool(
            reg_a and reg_b and reg_a.jurisdiction == reg_b.jurisdiction
        )
        return render(request, 'pages/comparison_custom_scope.html', {
            'all_regs':   all_regs,
            'reg_a':      reg_a,
            'reg_b':      reg_b,
            'reg_a_pk':   reg_a_pk or '',
            'reg_b_pk':   reg_b_pk or '',
            'flag_a':     _FLAG_MAP.get(reg_a.jurisdiction, '') if reg_a else '',
            'flag_b':     _FLAG_MAP.get(reg_b.jurisdiction, '') if reg_b else '',
            'has_regs':   bool(reg_a and reg_b and reg_a.pk != reg_b.pk),
            'same_jurisdiction': same_jurisdiction,
            'scan':       scan,
        })


# ── Run creation (POST from scope selector) ───────────────────────────────────

_FLAG_MAP = {
    'bahrain': 'bh', 'india': 'in', 'kuwait': 'kw',
    'saudi': 'sa', 'uae': 'ae', 'eu': 'eu', 'bbk': 'bh',
}


@method_decorator(role_required('analyst', 'reviewer'), name='dispatch')
class RunComparisonView(View):
    """POST handler from the combined comparison picker. Runs the reasoning
    workflow synchronously (the analyst flow that actually works), persists
    every obligation as a ComparisonResult row with the full evidence/risk
    payload, then redirects to /comparison/runs/<pk>/.

    The previous subprocess-based flow left runs stuck in 'running' when the
    server restarted; this synchronous path keeps the run and the request in
    the same process so a crash fails loudly instead of silently."""

    def post(self, request):
        reg_a_pk = int(request.POST['reg_a_pk']) if request.POST.get('reg_a_pk') else None
        reg_b_pk = int(request.POST['reg_b_pk']) if request.POST.get('reg_b_pk') else None

        if not reg_a_pk or not reg_b_pk:
            return redirect('comparison')
        reg_a = Document.objects.filter(pk=reg_a_pk, doc_type=Document.REGULATION, status=Document.INDEXED).first()
        reg_b = Document.objects.filter(pk=reg_b_pk, doc_type=Document.REGULATION, status=Document.INDEXED).first()
        if not reg_a or not reg_b or reg_a.pk == reg_b.pk:
            return redirect('comparison')

        scope_mode      = request.POST.get('scope_mode', 'full')
        topics          = request.POST.getlist('topics') if scope_mode != 'full' else []
        include_orphans = request.POST.get('include_orphans') == '1'

        # Build the run row up front so the workspace URL exists immediately and
        # we can audit even a crash in compare_regulations.
        pair_key = f'{reg_a.jurisdiction}_{reg_b.jurisdiction}'
        run = ComparisonRun.objects.create(
            pair_key=pair_key,
            reg_a=reg_a,
            reg_b=reg_b,
            topics=topics,
            status=ComparisonRun.RUNNING,
            created_by=request.user if request.user.is_authenticated else None,
        )

        from apps.history.audit import log_event, Actions
        log_event(
            request.user, Actions.COMPARISON_RUN,
            request=request,
            target_type='comparison.ComparisonRun', target_id=run.pk,
            description=f'{request.user.username} ran comparison {reg_a.name} vs {reg_b.name}',
            metadata={
                'pair_key': pair_key,
                'reg_a': reg_a.name, 'reg_b': reg_b.name,
                'topics': topics, 'include_orphans': include_orphans,
            },
        )

        # Run the reasoning workflow inline. This is the same call path the
        # analyst page uses — the user confirmed it produces the right results.
        try:
            import sys
            from pathlib import Path
            project_root = Path(__file__).resolve().parents[3]
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from reasoning.workflows import compare_regulations, compare_regulations_auto
            from reasoning             import taxonomy as _tx

            if not topics:
                # Full scope → topic-route across every taxonomy topic BOTH
                # regulations are classified on, then merge. A single generic
                # "compliance obligations" query retrieves misaligned clauses
                # and the local model finds almost no genuine A↔B pairs; routing
                # per shared topic makes each side's clauses align, producing a
                # fuller, better-grounded obligation set.
                report = compare_regulations_auto(
                    reg_a        = reg_a.jurisdiction,
                    reg_b        = reg_b.jurisdiction,
                    doc_title_a  = reg_a.chunk_doc_title or reg_a.name,
                    doc_title_b  = reg_b.chunk_doc_title or reg_b.name,
                    top_k_per_topic = 8,
                    rerank       = True,
                )
            else:
                # Explicit topic pick. single-topic vs multi-topic route through
                # different retrieval paths:
                #   • query as str  → _scoped_retrieve per side, accepts topic filter
                #   • query as list → _multi_query_retrieve, per-query taxonomy filter
                if len(topics) == 1:
                    query = _tx.topic_label(topics[0]).replace('_', ' ')
                else:
                    query = [_tx.topic_label(t).replace('_', ' ') for t in topics]
                topic_filter = topics[0] if _tx.is_valid(topics[0]) else None
                report = compare_regulations(
                    query        = query,
                    reg_a        = reg_a.jurisdiction,
                    reg_b        = reg_b.jurisdiction,
                    doc_title_a  = reg_a.chunk_doc_title or reg_a.name,
                    doc_title_b  = reg_b.chunk_doc_title or reg_b.name,
                    top_k        = 10,
                    rerank       = True,
                    scope_mode   = 'strict',
                    topic        = topic_filter,
                    topics       = topics if isinstance(query, list) else None,
                )
        except Exception as exc:
            import traceback; traceback.print_exc()
            run.status = ComparisonRun.FAILED
            run.error_message = f'{type(exc).__name__}: {str(exc)[:500]}'
            run.save(update_fields=['status', 'error_message'])
            return redirect('comparison-workspace', pk=run.pk)

        # Persist obligations as ComparisonResult rows. Every field the
        # reasoning layer produces is captured so the workspace can render the
        # same rich view the analyst page does.
        to_create = []
        for i, o in enumerate(report.obligations, 1):
            relationship, confidence, similarity = _map_relationship(
                o.equivalence, o.stricter_jurisdiction, o.similarity_score,
                llm_confidence=getattr(o, 'confidence_score', -1),
            )
            if not getattr(o, 'citation_verified', True):
                confidence = min(confidence, 0.45)
            text_blob = (o.reg_a_requirement or '') + ' ' + (o.reg_b_requirement or '')
            principles = _detect_principles(text_blob)

            to_create.append(ComparisonResult(
                run=run,
                citation_a=o.reg_a_citation or o.topic or f'Item {i}',
                citation_b=o.reg_b_citation or '',
                preview_a=(o.reg_a_requirement or '')[:300],
                preview_b=(o.reg_b_requirement or '')[:300],
                clause_text_a=o.reg_a_requirement or '',
                clause_text_b=o.reg_b_requirement or '',
                relationship=relationship,
                confidence=confidence,
                similarity_score=similarity,
                rationale=o.notes or '',
                key_difference=o.key_difference or '',
                lifecycle=ComparisonResult.DRAFT,
                principle_ids=principles,
                citation_verified=getattr(o, 'citation_verified', True),
                evidence_a=getattr(o, 'reg_a_evidence', '') or '',
                evidence_b=getattr(o, 'reg_b_evidence', '') or '',
                chunk_id_a=getattr(o, 'reg_a_chunk_id', '') or '',
                chunk_id_b=getattr(o, 'reg_b_chunk_id', '') or '',
                hallucination_risk=getattr(o, 'hallucination_risk', 0.0) or 0.0,
                practical_conclusion=getattr(o, 'practical_conclusion', '') or '',
                compliance_impact=getattr(o, 'compliance_impact', '') or '',
                shared_controls=getattr(o, 'shared_controls', []) or [],
                terminology_note=getattr(o, 'terminology_note', '') or '',
            ))

        ComparisonResult.objects.bulk_create(to_create)
        # Stash the full Pydantic report as JSON so the workspace can render
        # the rich analyst-style view without losing fields that don't have
        # ComparisonResult columns (axis strictness, raw equivalence, etc.).
        try:
            run.report_json = report.model_dump(mode='json')
        except Exception:
            run.report_json = {'obligations': [o.model_dump(mode='json') for o in report.obligations]}
        run.total_pairs = len(report.obligations)
        run.completed_pairs = len(to_create)
        run.status = ComparisonRun.COMPLETE
        run.save(update_fields=['total_pairs', 'completed_pairs', 'status', 'report_json'])

        try:
            log_event(
                request.user, Actions.COMPARISON_COMPLETE,
                target_type='comparison.ComparisonRun', target_id=run.pk,
                description=f'Comparison run #{run.pk} complete: {len(to_create)} pairs',
                metadata={'pair_key': pair_key, 'completed_pairs': len(to_create)},
            )
        except Exception:
            pass

        return redirect('comparison-workspace', pk=run.pk)


# ── Screen 4 — Results Workspace ──────────────────────────────────────────────

@method_decorator(role_required('analyst'), name='dispatch')
class SubmitForReviewView(View):
    """POST /comparison/runs/<pk>/submit-review/  — analyst hand-off action.

    Captures an optional analyst note, stamps the run with
    ``submitted_for_review_at`` + ``submitted_by``, transitions every
    draft ComparisonResult to ``reviewed`` so the reviewer queue picks them
    up, audits the event, and notifies reviewers. Idempotent — re-submitting
    the same run just refreshes the note + timestamp."""

    def post(self, request, pk):
        run = get_object_or_404(ComparisonRun, pk=pk)
        note = (request.POST.get('analyst_note') or '').strip()[:2000]

        from django.utils import timezone
        run.analyst_note            = note
        run.submitted_for_review_at = timezone.now()
        run.submitted_by            = request.user
        run.save(update_fields=['analyst_note', 'submitted_for_review_at', 'submitted_by'])

        ComparisonResult.objects.filter(
            run=run, lifecycle=ComparisonResult.DRAFT,
        ).update(lifecycle=ComparisonResult.REVIEWED)

        try:
            from apps.history.audit import log_event, Actions
            log_event(
                request.user, Actions.REVIEW_SUBMIT,
                target_type='comparison.ComparisonRun', target_id=run.pk,
                request=request,
                description=f'{request.user.username} sent run #{run.pk} to reviewer',
                metadata={'run_id': run.pk, 'note_len': len(note),
                          'reg_a': run.reg_a.name, 'reg_b': run.reg_b.name},
            )
        except Exception:
            pass

        try:
            from django.core.cache import cache
            cache.delete('nav_counts')
        except Exception:
            pass

        return redirect('comparison-workspace', pk=run.pk)


@method_decorator(role_required('analyst', 'reviewer'), name='dispatch')
class ComparisonWorkspaceView(View):
    """GET /comparison/runs/<pk>/  — render the unified 8-tab results view
    (Overview, Obligations, Charts, BBK Implications, Arc Diagram, Graph,
    Topic Map, Insights) for a saved comparison run. Same partial the analyst
    page uses, just hydrated from ``run.report_json`` + ``run.results`` instead
    of a fresh in-memory report."""

    def get(self, request, pk):
        run = get_object_or_404(ComparisonRun, pk=pk)
        ctx = self._build_context(run)
        return render(request, 'pages/comparison_workspace.html', ctx)

    def _build_context(self, run):
        from types import SimpleNamespace
        import json as _json

        # Hydrate obligations — preferred path is the JSON dump, which keeps
        # every reasoning-layer field. Legacy runs (pre-report_json migration)
        # fall back to ComparisonResult rows; some fields will be missing then.
        obligations = []
        if run.report_json and run.report_json.get('obligations'):
            for d in run.report_json['obligations']:
                obligations.append(SimpleNamespace(**d))
        else:
            for r in run.results.all():
                obligations.append(SimpleNamespace(
                    topic                  = '',
                    reg_a_citation         = r.citation_a or '',
                    reg_b_citation         = r.citation_b or '',
                    reg_a_chunk_id         = r.chunk_id_a or '',
                    reg_b_chunk_id         = r.chunk_id_b or '',
                    reg_a_doc_title        = run.reg_a.chunk_doc_title or '',
                    reg_b_doc_title        = run.reg_b.chunk_doc_title or '',
                    reg_a_requirement      = r.clause_text_a or r.preview_a or '',
                    reg_b_requirement      = r.clause_text_b or r.preview_b or '',
                    reg_a_evidence         = r.evidence_a or '',
                    reg_b_evidence         = r.evidence_b or '',
                    equivalence            = _rel_to_equivalence(r.relationship),
                    similarity_score       = int(round((r.similarity_score or 0) * 100)),
                    confidence_score       = int(round((r.confidence or 0) * 100)),
                    key_difference         = r.key_difference or '',
                    procedural_stricter    = 'Not Assessable',
                    substantive_stricter   = 'Not Assessable',
                    enforcement_stricter   = 'Not Assessable',
                    stricter_jurisdiction  = '',
                    notes                  = r.rationale or '',
                    citation_verified      = bool(r.citation_verified),
                    hallucination_risk     = float(r.hallucination_risk or 0.0),
                ))

        report = SimpleNamespace(
            obligations  = obligations,
            summary      = (run.report_json or {}).get('summary', ''),
            query        = (run.report_json or {}).get('query', ''),
            regulation_a = run.reg_a.name,
            regulation_b = run.reg_b.name,
        )

        stats, axes, chart_data, bbk = _build_analyst_aggregates(obligations, run.reg_a, run.reg_b)

        try:
            from reasoning import taxonomy as _tx
            taxonomy_topics = _tx.all_topics()
            taxonomy_subs_flat = [
                (t_code, s_code, s_label)
                for t_code, _ in taxonomy_topics
                for s_code, s_label in _tx.all_subcategories(t_code)
            ]
            taxonomy_map = {t: _tx.all_subcategories(t) for t, _ in taxonomy_topics}
        except Exception:
            taxonomy_topics = []
            taxonomy_subs_flat = []
            taxonomy_map = {}

        tab_defs = [
            ('obligations', 'Obligations'),
            ('overview',    'Overview'),
            ('charts',      'Charts'),
            ('graph',       'Graph'),
        ]

        return {
            'run':                run,
            'run_pk':             run.pk,
            'report':             report,
            'stats':              stats,
            'axes':               axes,
            'chart_data_json':    _json.dumps(chart_data) if chart_data else 'null',
            'bbk':                bbk,
            'tab_defs':           tab_defs,
            'reg_a':              run.reg_a,
            'reg_b':              run.reg_b,
            'topic':              (run.topics[0] if run.topics else ''),
            'subcategory':        '',
            'topic_choices':      taxonomy_topics,
            'taxonomy_map_json':  _json.dumps(taxonomy_map),
            'taxonomy_subs_flat': taxonomy_subs_flat,
            'error':              run.error_message or None,
        }


def _rel_to_equivalence(relationship: str) -> str:
    """Reverse-map ComparisonResult.relationship to the raw equivalence label
    the reasoning layer uses. Lossy — different/conflicting both map to
    'Different' if no per-side stricter info is available — but good enough
    for the workspace to render legacy runs that pre-date report_json."""
    return {
        'equivalent':      'Equivalent',
        'stricter_in_a':   'Partially Equivalent',
        'stricter_in_b':   'Partially Equivalent',
        'additional_in_a': 'Only in A',
        'additional_in_b': 'Only in B',
        'conflicting':     'Conflicting',
    }.get(relationship, 'Different')


def _build_analyst_aggregates(obligations, reg_a, reg_b):
    """Compute the stats/axes/chart_data/bbk_implications context blocks the
    analyst results partial expects. Lifted from AnalystComparisonView._render
    so the workspace view can show the same UI for a persisted run."""
    if not obligations:
        return None, [], None, None

    verified = sum(1 for o in obligations if getattr(o, 'citation_verified', False))
    avg_hall = sum(float(getattr(o, 'hallucination_risk', 0.0)) for o in obligations) / max(len(obligations), 1)
    equiv_count = sum(1 for o in obligations if getattr(o, 'equivalence', '') == 'Equivalent')
    conflicts   = sum(1 for o in obligations if getattr(o, 'equivalence', '') == 'Conflicting')

    def tally(field):
        a = sum(1 for o in obligations if getattr(o, field, '') == 'A')
        b = sum(1 for o in obligations if getattr(o, field, '') == 'B')
        eq = sum(1 for o in obligations if getattr(o, field, '') == 'Equivalent')
        na = len(obligations) - a - b - eq
        return {'a': a, 'b': b, 'equiv': eq, 'na': na}

    stats = {
        'count':       len(obligations),
        'verified':    verified,
        'avg_hall':    round(avg_hall, 3),
        'equiv':       equiv_count,
        'conflicts':   conflicts,
        'procedural':  tally('procedural_stricter'),
        'substantive': tally('substantive_stricter'),
        'enforcement': tally('enforcement_stricter'),
    }
    axes = [
        ('Procedural',  stats['procedural']),
        ('Substantive', stats['substantive']),
        ('Enforcement', stats['enforcement']),
    ]

    conf_buckets = [0] * 10
    risk_buckets = [0] * 5
    sim_buckets  = [0] * 10
    for o in obligations:
        conf_idx = min(max(int(getattr(o, 'confidence_score', 0)) // 10, 0), 9)
        conf_buckets[conf_idx] += 1
        risk_idx = min(max(int(float(getattr(o, 'hallucination_risk', 0.0)) * 5), 0), 4)
        risk_buckets[risk_idx] += 1
        sim_idx = min(max(int(getattr(o, 'similarity_score', 0)) // 10, 0), 9)
        sim_buckets[sim_idx] += 1
    equiv_counts = {}
    for o in obligations:
        k = getattr(o, 'equivalence', '') or 'Unspecified'
        equiv_counts[k] = equiv_counts.get(k, 0) + 1
    chart_data = {
        'confidence': {'labels': ['0-10','10-20','20-30','30-40','40-50','50-60','60-70','70-80','80-90','90-100'], 'data': conf_buckets},
        'risk':       {'labels': ['0.0-0.2 (low)','0.2-0.4','0.4-0.6','0.6-0.8','0.8-1.0 (high)'], 'data': risk_buckets},
        'similarity': {'labels': ['0-10','10-20','20-30','30-40','40-50','50-60','60-70','70-80','80-90','90-100'], 'data': sim_buckets},
        'strictness': {
            'labels': ['A', 'B', 'Equivalent', 'Not Assessable'],
            'procedural':  [stats['procedural']['a'], stats['procedural']['b'], stats['procedural']['equiv'], stats['procedural']['na']],
            'substantive': [stats['substantive']['a'], stats['substantive']['b'], stats['substantive']['equiv'], stats['substantive']['na']],
            'enforcement': [stats['enforcement']['a'], stats['enforcement']['b'], stats['enforcement']['equiv'], stats['enforcement']['na']],
        },
        'equivalence': {'labels': list(equiv_counts.keys()), 'data': list(equiv_counts.values())},
    }

    jur_a = (reg_a.jurisdiction.capitalize() if reg_a else 'A') or 'A'
    jur_b = (reg_b.jurisdiction.capitalize() if reg_b else 'B') or 'B'
    buckets = {
        'conflicts':           [],
        'unilateral_a':        [],
        'unilateral_b':        [],
        'procedural_actions':  [],
        'substantive_gaps':    [],
        'enforcement_risks':   [],
        'aligned':             [],
    }
    for i, o in enumerate(obligations, 1):
        row = {
            'index':       i,
            'topic':       getattr(o, 'topic', ''),
            'detail':      getattr(o, 'key_difference', '') or getattr(o, 'notes', ''),
            'reg_a_short': (getattr(o, 'reg_a_citation', '') or '')[:60],
            'reg_b_short': (getattr(o, 'reg_b_citation', '') or '')[:60],
        }
        eq = getattr(o, 'equivalence', '')
        if eq == 'Conflicting':
            buckets['conflicts'].append(row)
        elif eq == 'Only in A':
            buckets['unilateral_a'].append(row)
        elif eq == 'Only in B':
            buckets['unilateral_b'].append(row)
        elif eq == 'Equivalent':
            buckets['aligned'].append(row)
        else:
            if getattr(o, 'procedural_stricter', '') in ('A', 'B'):
                buckets['procedural_actions'].append({**row, 'stricter': o.procedural_stricter})
            if getattr(o, 'substantive_stricter', '') in ('A', 'B'):
                buckets['substantive_gaps'].append({**row, 'stricter': o.substantive_stricter})
            if getattr(o, 'enforcement_stricter', '') in ('A', 'B'):
                buckets['enforcement_risks'].append({**row, 'stricter': o.enforcement_stricter})
            if all(getattr(o, f, '') in ('Equivalent', 'Not Assessable', '')
                   for f in ('procedural_stricter', 'substantive_stricter', 'enforcement_stricter')):
                buckets['aligned'].append(row)

    top_actions = []
    for r in buckets['conflicts']:
        top_actions.append({'severity': 'high', 'kind': 'Conflict — escalate to legal',
                            'topic': r['topic'], 'detail': r['detail'], 'index': r['index']})
    for r in buckets['procedural_actions']:
        stricter_jur = jur_a if r.get('stricter') == 'A' else jur_b
        top_actions.append({'severity': 'medium', 'kind': f'Adopt stricter procedure ({stricter_jur})',
                            'topic': r['topic'], 'detail': r['detail'], 'index': r['index']})
    for r in buckets['substantive_gaps']:
        stricter_jur = jur_a if r.get('stricter') == 'A' else jur_b
        top_actions.append({'severity': 'medium', 'kind': f'Apply broader eligibility ({stricter_jur})',
                            'topic': r['topic'], 'detail': r['detail'], 'index': r['index']})
    for r in buckets['enforcement_risks']:
        stricter_jur = jur_a if r.get('stricter') == 'A' else jur_b
        top_actions.append({'severity': 'low', 'kind': f'Heightened enforcement risk in {stricter_jur}',
                            'topic': r['topic'], 'detail': r['detail'], 'index': r['index']})

    bbk = {
        'jur_a':       jur_a,
        'jur_b':       jur_b,
        'buckets':     buckets,
        'top_actions': top_actions,
        'totals':      {k: len(v) for k, v in buckets.items()},
        # Plain-prose summary of what BBK needs to think about, derived from
        # the buckets above. Two-sentence paragraph the template renders under
        # the "Compliance impact for clients" heading. Deterministic — no
        # second LLM call needed because the obligation list already carries
        # the key_difference text from the comparison run.
        'compliance_impact': _build_compliance_impact(buckets, jur_a, jur_b),
    }

    return stats, axes, chart_data, bbk


def _build_compliance_impact(buckets, jur_a: str, jur_b: str) -> str:
    """One-paragraph narrative summarising what an operations team needs to
    think about given the bucket counts. Pulls 1–2 specific topic strings off
    the top buckets so the prose stays concrete instead of generic.

    Jurisdiction phrasing handles the same-jurisdiction case (both A and B
    from the same country) — saying "Kuwait and Kuwait" reads as broken."""
    same_jur = jur_a.lower() == jur_b.lower()
    a_vs_b   = f"{jur_a} and {jur_b}" if not same_jur else f"both {jur_a} regulations"
    a_or_b   = f"{jur_a} or {jur_b}" if not same_jur else f"either {jur_a} regulation"
    sides    = (f"Regulation A and Regulation B" if same_jur else f"{jur_a} (A) and {jur_b} (B)")

    parts: list[str] = []

    if buckets['conflicts']:
        topics = ', '.join({r['topic'] for r in buckets['conflicts'][:2] if r.get('topic')})
        parts.append(
            f"BBK should escalate to legal review {len(buckets['conflicts'])} conflict(s) where "
            f"{sides} take contradictory positions"
            f"{' (e.g. on ' + topics + ')' if topics else ''}."
        )

    if buckets['procedural_actions'] or buckets['substantive_gaps']:
        n = len(buckets['procedural_actions']) + len(buckets['substantive_gaps'])
        sample_topics = ', '.join({r['topic'] for r in (buckets['procedural_actions'] + buckets['substantive_gaps'])[:2] if r.get('topic')})
        parts.append(
            f"To operate compliantly under both regimes, BBK should adopt the stricter requirement on "
            f"{n} obligation(s)"
            f"{' covering ' + sample_topics if sample_topics else ''}"
            f" — that means following whichever side imposes a tighter procedural or substantive duty."
        )

    if buckets['enforcement_risks']:
        parts.append(
            f"{len(buckets['enforcement_risks'])} obligation(s) carry heightened enforcement risk on one side; "
            f"these warrant tighter internal controls and audit evidence for the side with stronger penalties."
        )

    if buckets['unilateral_a'] or buckets['unilateral_b']:
        if same_jur:
            parts.append(
                f"{len(buckets['unilateral_a'])} obligation(s) appear only in Regulation A and "
                f"{len(buckets['unilateral_b'])} only in Regulation B — BBK must implement both even though the other regulation is silent."
            )
        else:
            parts.append(
                f"{len(buckets['unilateral_a'])} obligation(s) exist only in {jur_a} and "
                f"{len(buckets['unilateral_b'])} only in {jur_b} — when serving customers in those jurisdictions BBK "
                f"must implement these even though the other side is silent."
            )

    if buckets['aligned'] and not parts:
        parts.append(
            f"All {len(buckets['aligned'])} obligation(s) align between {sides}; no gap "
            f"identified in this comparison scope."
        )

    return ' '.join(parts) if parts else (
        f"No significant divergences identified in this comparison between {a_vs_b}."
    )


# ── Analyst comparison — direct, blocking, full evidence display ─────────────
# Replaces the subprocess+poll workspace flow which kept showing 0 results
# even when the underlying reasoning workflow had produced 8+ obligations.
# This view runs the comparison synchronously in the request thread (1–2 min
# for a single topic) and returns a fully rendered results page with every
# field the reasoning layer produces: verbatim evidence, chunk_id deep-links,
# citation_verified, NLI hallucination_risk, similarity, confidence, key
# difference, stricter-jurisdiction call-out.

@method_decorator(role_required('analyst'), name='dispatch')
class AnalystComparisonView(View):
    """GET /comparison/analyst/  — show form + most-recent results.
    POST /comparison/analyst/ — run a fresh comparison and display the result."""

    TOPIC_CHOICES = [
        ('consent',             'Consent'),
        ('breach_notification', 'Breach notification'),
        ('cross_border',        'Cross-border transfers'),
        ('data_subject_rights', 'Data subject rights'),
        ('retention',           'Data retention'),
        ('security',            'Security obligations'),
        ('dpo',                 'Data Protection Officer'),
        ('children',            'Children\'s data'),
    ]

    def get(self, request):
        return self._render(request, error=None, report=None,
                             topic='', subcategory='', reg_a_pk=None, reg_b_pk=None)

    def post(self, request):
        reg_a_pk    = request.POST.get('reg_a_pk') or ''
        reg_b_pk    = request.POST.get('reg_b_pk') or ''
        topic       = (request.POST.get('topic') or '').strip()
        subcategory = (request.POST.get('subcategory') or '').strip()

        try:
            reg_a = Document.objects.get(pk=int(reg_a_pk),
                                          doc_type=Document.REGULATION,
                                          status=Document.INDEXED)
            reg_b = Document.objects.get(pk=int(reg_b_pk),
                                          doc_type=Document.REGULATION,
                                          status=Document.INDEXED)
        except (ValueError, Document.DoesNotExist):
            return self._render(request, error='Pick two indexed regulations.',
                                  report=None, topic=topic, subcategory=subcategory,
                                  reg_a_pk=reg_a_pk, reg_b_pk=reg_b_pk)

        if reg_a.pk == reg_b.pk:
            return self._render(request, error='Pick two DIFFERENT regulations.',
                                  report=None, topic=topic, subcategory=subcategory,
                                  reg_a_pk=reg_a_pk, reg_b_pk=reg_b_pk)
        if not topic:
            return self._render(request, error='Pick a topic.',
                                  report=None, topic=topic, subcategory=subcategory,
                                  reg_a_pk=reg_a_pk, reg_b_pk=reg_b_pk)

        # Map the legacy quick-pick `topic` (8 hardcoded codes) into the new
        # taxonomy where it isn't already a real taxonomy key. Lets the form
        # accept either the old quick-pick topic or a fresh taxonomy topic.
        from reasoning import taxonomy as _tx
        legacy_to_taxonomy = {
            'consent':             ('lawful_basis',           'consent'),
            'breach_notification': ('breach_management',      'regulator_notification'),
            'cross_border':        ('cross_border',           ''),
            'data_subject_rights': ('data_subject_rights',    ''),
            'retention':           ('retention',              'retention_periods'),
            'security':            ('security',               ''),
            'dpo':                 ('governance',             'dpo_appointment'),
            'children':            ('sensitive_data',         'children_and_minors'),
        }
        if topic in legacy_to_taxonomy:
            tax_topic, tax_sub = legacy_to_taxonomy[topic]
            if not subcategory:
                subcategory = tax_sub
            topic = tax_topic
        elif not _tx.is_valid(topic):
            return self._render(request, error=f'Unknown topic: {topic}',
                                  report=None, topic=topic, subcategory=subcategory,
                                  reg_a_pk=reg_a_pk, reg_b_pk=reg_b_pk)

        # Build the retrieval query from the human label, which gives the BM25
        # side something lexical to match. Topic+sub are already filtering at
        # the DB layer, so the query is just for ranking inside that pool.
        sub_label = _tx.subcategory_label(topic, subcategory) if subcategory else ''
        topic_label = _tx.topic_label(topic)
        query_text = (sub_label or topic_label or topic).replace('_', ' ')

        # Run the reasoning workflow inline. Blocks for 1–2 minutes.
        from reasoning.workflows import compare_regulations
        try:
            report = compare_regulations(
                query        = query_text,
                reg_a        = reg_a.jurisdiction,
                reg_b        = reg_b.jurisdiction,
                # use chunk_doc_title (file stem) — display name doesn't match
                # what ingestion stored as chunk metadata.
                doc_title_a  = reg_a.chunk_doc_title or reg_a.name,
                doc_title_b  = reg_b.chunk_doc_title or reg_b.name,
                top_k        = 5,
                rerank       = True,
                scope_mode   = 'strict',
                topic        = topic       or None,
                subcategory  = subcategory or None,
            )
        except Exception as exc:
            import traceback; traceback.print_exc()
            return self._render(request, error=f'Reasoning workflow failed: {exc}',
                                  report=None, topic=topic, subcategory=subcategory,
                                  reg_a_pk=reg_a_pk, reg_b_pk=reg_b_pk)

        # Persist a ComparisonRun + ComparisonResult rows so the rich tabs
        # (Arc Diagram / Graph / Topic Map / Insights) — which lazy-load via
        # HTMX from /comparison/runs/<pk>/* — have a pk to query against.
        run = self._persist_run(request, reg_a, reg_b, topic, subcategory, report)

        try:
            from apps.history.audit import log_event, Actions
            tag = f'{topic}/{subcategory}' if subcategory else topic
            log_event(request.user, Actions.COMPARISON_COMPLETE,
                      target_type='comparison.ComparisonRun',
                      target_id=run.pk if run else None,
                      request=request,
                      description=(f'Analyst comparison: {reg_a.name} vs {reg_b.name} on {tag} '
                                   f'-> {len(report.obligations)} obligations'),
                      metadata={'reg_a_id': reg_a.pk, 'reg_b_id': reg_b.pk,
                                'topic': topic, 'subcategory': subcategory,
                                'count':    len(report.obligations),
                                'run_id':   run.pk if run else None})
        except Exception:
            pass

        return self._render(request, error=None, report=report,
                              topic=topic, subcategory=subcategory,
                              reg_a_pk=reg_a_pk, reg_b_pk=reg_b_pk,
                              reg_a=reg_a, reg_b=reg_b, run=run)

    def _persist_run(self, request, reg_a, reg_b, topic, subcategory, report):
        """Create the ComparisonRun + ComparisonResult rows for an analyst run.
        Wrapped in try/except — if persistence fails we still render the page,
        we just lose the lazy-load tabs (Arc/Graph/Topic Map/Insights)."""
        try:
            pair_key = f'{reg_a.jurisdiction}_{reg_b.jurisdiction}'
            run = ComparisonRun.objects.create(
                pair_key=pair_key,
                reg_a=reg_a, reg_b=reg_b,
                topics=[topic] if topic else [],
                status=ComparisonRun.RUNNING,
                created_by=request.user if request.user.is_authenticated else None,
            )
            to_create = []
            for i, o in enumerate(report.obligations, 1):
                relationship, confidence, similarity = _map_relationship(
                    o.equivalence, o.stricter_jurisdiction, o.similarity_score,
                    llm_confidence=getattr(o, 'confidence_score', -1),
                )
                if not getattr(o, 'citation_verified', True):
                    confidence = min(confidence, 0.45)
                text_blob = (o.reg_a_requirement or '') + ' ' + (o.reg_b_requirement or '')
                principles = _detect_principles(text_blob)
                to_create.append(ComparisonResult(
                    run=run,
                    citation_a=o.reg_a_citation or o.topic or f'Item {i}',
                    citation_b=o.reg_b_citation or '',
                    preview_a=(o.reg_a_requirement or '')[:300],
                    preview_b=(o.reg_b_requirement or '')[:300],
                    clause_text_a=o.reg_a_requirement or '',
                    clause_text_b=o.reg_b_requirement or '',
                    relationship=relationship,
                    confidence=confidence,
                    similarity_score=similarity,
                    rationale=o.notes or '',
                    key_difference=o.key_difference or '',
                    lifecycle=ComparisonResult.DRAFT,
                    principle_ids=principles,
                    citation_verified=getattr(o, 'citation_verified', True),
                    evidence_a=getattr(o, 'reg_a_evidence', '') or '',
                    evidence_b=getattr(o, 'reg_b_evidence', '') or '',
                    chunk_id_a=getattr(o, 'reg_a_chunk_id', '') or '',
                    chunk_id_b=getattr(o, 'reg_b_chunk_id', '') or '',
                    hallucination_risk=getattr(o, 'hallucination_risk', 0.0) or 0.0,
                ))
            ComparisonResult.objects.bulk_create(to_create)
            try:
                run.report_json = report.model_dump(mode='json')
            except Exception:
                run.report_json = {'obligations': [o.model_dump(mode='json') for o in report.obligations]}
            run.total_pairs = len(report.obligations)
            run.completed_pairs = len(to_create)
            run.status = ComparisonRun.COMPLETE
            run.save(update_fields=['total_pairs', 'completed_pairs', 'status', 'report_json'])
            return run
        except Exception:
            import traceback; traceback.print_exc()
            return None

    def _render(self, request, *, error, report, topic, reg_a_pk, reg_b_pk,
                subcategory='', reg_a=None, reg_b=None, run=None):
        # Only show regulations that ACTUALLY have indexed chunks. A doc can
        # be in the DB with status=indexed but have zero chunks if the
        # ingestion was wiped, retried under a different filename, etc.
        # Without this filter the user can pick a 0-chunk doc and the
        # comparison silently returns 0 obligations.
        regulations = list(
            Document.objects
            .filter(doc_type=Document.REGULATION,
                    status=Document.INDEXED,
                    chunk_count__gt=0)
            .order_by('jurisdiction', 'name')
            .values('pk', 'name', 'jurisdiction', 'chunk_count')
        )

        # HTMX detection: when the form submits via hx-post, return ONLY the
        # results inner HTML (no base layout wrapper). Otherwise we'd nest the
        # whole sidebar/copilot/template inside the results panel.
        is_htmx = request.headers.get('HX-Request') == 'true'

        # Aggregate stats for the top-of-page summary banner.
        stats = None
        if report:
            obs = report.obligations
            verified = sum(1 for o in obs if o.citation_verified)
            avg_hall = sum(o.hallucination_risk for o in obs) / max(len(obs), 1)
            equiv_count = sum(1 for o in obs if o.equivalence == 'Equivalent')
            conflicts   = sum(1 for o in obs if o.equivalence == 'Conflicting')

            # Per-axis tallies. 'A'/'B' are the canonical values from the prompt;
            # the verifier may also fill the legacy single-axis field with a
            # jurisdiction name, which we still tolerate for the roll-up tally.
            def tally(field: str) -> dict:
                a = sum(1 for o in obs if getattr(o, field, '') == 'A')
                b = sum(1 for o in obs if getattr(o, field, '') == 'B')
                eq = sum(1 for o in obs if getattr(o, field, '') == 'Equivalent')
                na = len(obs) - a - b - eq
                return {'a': a, 'b': b, 'equiv': eq, 'na': na}

            stats = {
                'count':       len(obs),
                'verified':    verified,
                'avg_hall':    round(avg_hall, 3),
                'equiv':       equiv_count,
                'conflicts':   conflicts,
                'procedural':  tally('procedural_stricter'),
                'substantive': tally('substantive_stricter'),
                'enforcement': tally('enforcement_stricter'),
            }
        # Template iterates `axes` to render the three-axis tally row.
        axes = []
        if stats:
            axes = [
                ('Procedural',  stats['procedural']),
                ('Substantive', stats['substantive']),
                ('Enforcement', stats['enforcement']),
            ]

        # Charts tab: pre-compute the data points the Chart.js canvases will
        # plot. Done in Python (not JS) so the template can hand Chart.js a
        # ready-to-render JSON literal — keeps the JS minimal and avoids
        # client-side number crunching.
        chart_data = None
        if report and report.obligations:
            obs = report.obligations
            # Confidence histogram in 10-pt buckets, 0-100.
            conf_buckets = [0] * 10
            for o in obs:
                idx = min(max(int(o.confidence_score) // 10, 0), 9)
                conf_buckets[idx] += 1
            # AI risk histogram in 0.2-wide buckets, 0.0-1.0.
            risk_buckets = [0] * 5
            for o in obs:
                idx = min(max(int(float(o.hallucination_risk) * 5), 0), 4)
                risk_buckets[idx] += 1
            # Similarity histogram in 10-pt buckets.
            sim_buckets = [0] * 10
            for o in obs:
                idx = min(max(int(o.similarity_score) // 10, 0), 9)
                sim_buckets[idx] += 1
            # Equivalence breakdown.
            equiv_counts = {}
            for o in obs:
                k = o.equivalence or 'Unspecified'
                equiv_counts[k] = equiv_counts.get(k, 0) + 1
            chart_data = {
                'confidence': {
                    'labels': ['0-10', '10-20', '20-30', '30-40', '40-50',
                               '50-60', '60-70', '70-80', '80-90', '90-100'],
                    'data': conf_buckets,
                },
                'risk': {
                    'labels': ['0.0-0.2 (low)', '0.2-0.4', '0.4-0.6',
                               '0.6-0.8', '0.8-1.0 (high)'],
                    'data': risk_buckets,
                },
                'similarity': {
                    'labels': ['0-10', '10-20', '20-30', '30-40', '40-50',
                               '50-60', '60-70', '70-80', '80-90', '90-100'],
                    'data': sim_buckets,
                },
                'strictness': {
                    'labels': ['A', 'B', 'Equivalent', 'Not Assessable'],
                    'procedural':  [stats['procedural']['a'],  stats['procedural']['b'],
                                    stats['procedural']['equiv'],  stats['procedural']['na']],
                    'substantive': [stats['substantive']['a'], stats['substantive']['b'],
                                    stats['substantive']['equiv'], stats['substantive']['na']],
                    'enforcement': [stats['enforcement']['a'], stats['enforcement']['b'],
                                    stats['enforcement']['equiv'], stats['enforcement']['na']],
                },
                'equivalence': {
                    'labels': list(equiv_counts.keys()),
                    'data':   list(equiv_counts.values()),
                },
            }

        # BBK Implications: derived from the report data without an extra
        # LLM call. Each obligation falls into one of a few impact buckets
        # an operations/compliance team would care about. We surface them
        # categorically so analysts can scan instead of re-reading every row.
        bbk_implications = None
        if report and report.obligations:
            jur_a = (reg_a.jurisdiction if reg_a else '').capitalize() or 'A'
            jur_b = (reg_b.jurisdiction if reg_b else '').capitalize() or 'B'
            buckets = {
                'conflicts':            [],   # contradictory rules — legal review needed
                'unilateral_a':         [],   # only in A — sectoral exemption / unique obligation
                'unilateral_b':         [],   # only in B
                'procedural_actions':   [],   # one side has stricter procedure (deadlines, notifications)
                'substantive_gaps':     [],   # one side has stricter eligibility/scope
                'enforcement_risks':    [],   # one side has stricter penalties / regulator powers
                'aligned':              [],   # genuinely equivalent — no action needed beyond awareness
            }
            for i, o in enumerate(report.obligations, 1):
                row = {
                    'index':       i,
                    'topic':       o.topic,
                    'detail':      o.key_difference or o.notes or '',
                    'reg_a_short': (o.reg_a_citation or '')[:60],
                    'reg_b_short': (o.reg_b_citation or '')[:60],
                }
                if o.equivalence == 'Conflicting':
                    buckets['conflicts'].append(row)
                elif o.equivalence == 'Only in A':
                    buckets['unilateral_a'].append(row)
                elif o.equivalence == 'Only in B':
                    buckets['unilateral_b'].append(row)
                elif o.equivalence == 'Equivalent':
                    buckets['aligned'].append(row)
                else:
                    # Look at strictness axes to decide where to file it.
                    if o.procedural_stricter in ('A', 'B'):
                        buckets['procedural_actions'].append(
                            {**row, 'stricter': o.procedural_stricter}
                        )
                    if o.substantive_stricter in ('A', 'B'):
                        buckets['substantive_gaps'].append(
                            {**row, 'stricter': o.substantive_stricter}
                        )
                    if o.enforcement_stricter in ('A', 'B'):
                        buckets['enforcement_risks'].append(
                            {**row, 'stricter': o.enforcement_stricter}
                        )
                    # If no axis flagged stricter, treat as informational alignment.
                    if all(getattr(o, f, '') in ('Equivalent', 'Not Assessable', '')
                           for f in ('procedural_stricter', 'substantive_stricter', 'enforcement_stricter')):
                        buckets['aligned'].append(row)

            # Headline: operationally what does BBK need to do, ranked.
            top_actions = []
            for r in buckets['conflicts']:
                top_actions.append({
                    'severity': 'high', 'kind': 'Conflict — escalate to legal',
                    'topic': r['topic'], 'detail': r['detail'], 'index': r['index'],
                })
            for r in buckets['procedural_actions']:
                stricter_jur = jur_a if r.get('stricter') == 'A' else jur_b
                top_actions.append({
                    'severity': 'medium', 'kind': f'Adopt stricter procedure ({stricter_jur})',
                    'topic': r['topic'], 'detail': r['detail'], 'index': r['index'],
                })
            for r in buckets['substantive_gaps']:
                stricter_jur = jur_a if r.get('stricter') == 'A' else jur_b
                top_actions.append({
                    'severity': 'medium', 'kind': f'Apply broader eligibility ({stricter_jur})',
                    'topic': r['topic'], 'detail': r['detail'], 'index': r['index'],
                })
            for r in buckets['enforcement_risks']:
                stricter_jur = jur_a if r.get('stricter') == 'A' else jur_b
                top_actions.append({
                    'severity': 'low', 'kind': f'Heightened enforcement risk in {stricter_jur}',
                    'topic': r['topic'], 'detail': r['detail'], 'index': r['index'],
                })

            bbk_implications = {
                'jur_a':       jur_a,
                'jur_b':       jur_b,
                'buckets':     buckets,
                'top_actions': top_actions,
                'totals': {
                    'conflicts':           len(buckets['conflicts']),
                    'unilateral_a':        len(buckets['unilateral_a']),
                    'unilateral_b':        len(buckets['unilateral_b']),
                    'procedural_actions':  len(buckets['procedural_actions']),
                    'substantive_gaps':    len(buckets['substantive_gaps']),
                    'enforcement_risks':   len(buckets['enforcement_risks']),
                    'aligned':             len(buckets['aligned']),
                },
            }

        # Topic + subcategory cascade. We render TWO context variables:
        #   - taxonomy_topics: [(code, label)] for the topic <select>
        #   - taxonomy_subs_flat: [(topic_code, sub_code, sub_label)] — every
        #     subcategory option rendered server-side. The template iterates
        #     this once and uses Alpine x-show to filter by current topic.
        #     This avoids `<template x-for>` inside a <select>, which most
        #     browsers refuse to parse correctly.
        import json as _json
        try:
            from reasoning import taxonomy as _tx
            taxonomy_topics = _tx.all_topics()
            taxonomy_subs_flat = [
                (t_code, s_code, s_label)
                for t_code, _ in taxonomy_topics
                for s_code, s_label in _tx.all_subcategories(t_code)
            ]
            taxonomy_map = {t: _tx.all_subcategories(t) for t, _ in taxonomy_topics}
        except Exception:
            taxonomy_topics = list(self.TOPIC_CHOICES)
            taxonomy_subs_flat = []
            taxonomy_map = {}

        # Tab definitions for the results panel. Order matters — first tab
        # is the default. Keep the keys aligned with the x-show conditions in
        # _analyst_comparison_results.html.
        # When the run was persisted to DB (post path), expose its pk so the
        # template can lazy-load the Arc / Graph / Topic Map / Insights tabs
        # via the existing /comparison/runs/<pk>/* HTMX endpoints. Those tabs
        # are only shown when run_pk is truthy — they need server-side data
        # that doesn't exist on a fresh GET.
        run_pk = run.pk if run else None
        tab_defs = [
            ('obligations', 'Obligations'),
            ('overview',    'Overview'),
            ('charts',      'Charts'),
        ]
        if run_pk:
            tab_defs += [
                ('graph',     'Graph'),
            ]

        ctx = {
            'regulations':        regulations,
            'topic_choices':      taxonomy_topics,
            'taxonomy_map_json':  _json.dumps(taxonomy_map),
            'taxonomy_subs_flat': taxonomy_subs_flat,
            'topic':              topic,
            'subcategory':        subcategory,
            'reg_a_pk':           reg_a_pk,
            'reg_b_pk':           reg_b_pk,
            'reg_a':              reg_a,
            'reg_b':              reg_b,
            'report':             report,
            'stats':              stats,
            'axes':               axes,
            'chart_data_json':    _json.dumps(chart_data) if chart_data else 'null',
            'bbk':                bbk_implications,
            'tab_defs':           tab_defs,
            'run':                run,
            'run_pk':             run_pk,
            'error':              error,
        }
        if is_htmx:
            # return just the inner results fragment for swap into #analyst-results
            return render(request, 'partials/_analyst_comparison_results.html', ctx)
        return render(request, 'pages/analyst_comparison.html', ctx)


# ── Approved-package exports ──────────────────────────────────────────────────
# Mirror of apps.mapping.views' ExecSummary / GapRegister views, scoped to
# ComparisonRun. The two views below produce the same shape of artifact (PDF
# board-pack one-pager + XLSX register) so the reviewer / DPO hand-off works
# the same way regardless of whether the source is a comparison or a mapping.

_DECIDED_RUN_STATES = (
    ComparisonRun.COMPLETE,
    ComparisonRun.PARTIALLY_FAILED,
)


@method_decorator(role_required('analyst', 'reviewer', 'admin'), name='dispatch')
class ComparisonExecSummaryView(View):
    """GET /comparison/runs/<pk>/exports/exec-summary.pdf"""

    def get(self, request, pk):
        run = get_object_or_404(ComparisonRun, pk=pk)
        if run.status not in _DECIDED_RUN_STATES:
            return HttpResponseBadRequest(
                'Exports are only available once the comparison is complete.'
            )
        from apps.review.exports import build_executive_summary_pdf, audit_hash
        data = build_executive_summary_pdf(run)
        try:
            from apps.history.audit import log_event
            log_event(
                request.user, 'exports.downloaded',
                request=request,
                target_type='comparison.ComparisonRun', target_id=run.pk,
                description=f'{request.user.username} downloaded exec summary for run #{run.pk}',
                metadata={'format': 'pdf', 'audit_hash': audit_hash(run), 'run_id': run.pk},
            )
        except Exception:
            pass
        slug = f'{run.reg_a.name}_vs_{run.reg_b.name}'[:60].replace(' ', '_').replace('/', '_')
        response = HttpResponse(data, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="exec-summary_{slug}.pdf"'
        return response


@method_decorator(role_required('analyst', 'reviewer', 'admin'), name='dispatch')
class ComparisonRegisterView(View):
    """GET /comparison/runs/<pk>/exports/comparison-register.xlsx"""

    def get(self, request, pk):
        run = get_object_or_404(ComparisonRun, pk=pk)
        if run.status not in _DECIDED_RUN_STATES:
            return HttpResponseBadRequest(
                'Exports are only available once the comparison is complete.'
            )
        from apps.review.exports import build_gap_register_xlsx, audit_hash
        data = build_gap_register_xlsx(run)
        try:
            from apps.history.audit import log_event
            log_event(
                request.user, 'exports.downloaded',
                request=request,
                target_type='comparison.ComparisonRun', target_id=run.pk,
                description=f'{request.user.username} downloaded comparison register for run #{run.pk}',
                metadata={'format': 'xlsx', 'audit_hash': audit_hash(run), 'run_id': run.pk},
            )
        except Exception:
            pass
        slug = f'{run.reg_a.name}_vs_{run.reg_b.name}'[:60].replace(' ', '_').replace('/', '_')
        response = HttpResponse(
            data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="comparison-register_{slug}.xlsx"'
        return response


# ── Guidance-style comparison (OneTrust DataGuidance layout) ───────────────────
# A separate, clean comparison shell so the client can pick between this and the
# existing clause-vs-clause workspace. Driven by real regulations per
# jurisdiction from the library.

_GC_JUR = {
    'bahrain': ('Bahrain', '\U0001F1E7\U0001F1ED'),
    'india':   ('India',   '\U0001F1EE\U0001F1F3'),
    'kuwait':  ('Kuwait',  '\U0001F1F0\U0001F1FC'),
    'saudi':   ('Saudi Arabia', '\U0001F1F8\U0001F1E6'),
}

_GC_TOPICS = [
    'Breach Notification', 'Data Subject Rights', 'Consent',
    'Cross-border Transfers', 'Data Retention', 'Security Measures',
]

_GC_TOC = [
    {'n': '1', 'title': 'Laws', 'sub': [
        {'n': '1.1', 'title': 'Laws and regulations'},
        {'n': '1.2', 'title': 'Supervisory authority'},
        {'n': '1.3', 'title': 'Guidelines'}]},
    {'n': '2', 'title': 'Definitions', 'sub': [{'n': '2.1', 'title': 'Key terms'}]},
    {'n': '3', 'title': 'Breach notification', 'sub': [
        {'n': '3.1', 'title': 'Supervisory authority notification'},
        {'n': '3.2', 'title': 'Notification to affected individuals'},
        {'n': '3.3', 'title': 'Notification to third parties'}]},
    {'n': '4', 'title': 'Enforcement', 'sub': [
        {'n': '4.1', 'title': 'Civil liability'},
        {'n': '4.2', 'title': 'Criminal liability'}]},
]


@method_decorator(role_required('analyst', 'reviewer', 'admin'), name='dispatch')
class GuidanceComparisonView(View):
    """GET /comparison/guidance/ — clean, aligned side-by-side comparison."""

    def get(self, request):
        regs = Document.objects.filter(doc_type=Document.REGULATION)
        present = [c for c in _GC_JUR if regs.filter(jurisdiction=c).exists()]
        sel = [j for j in request.GET.getlist('jur') if j in present] or present[:2]
        topic = request.GET.get('topic') or _GC_TOPICS[0]

        columns = []
        for j in sel:
            jr = list(regs.filter(jurisdiction=j).order_by('name'))
            authorities = []
            for r in jr:
                a = (r.issuing_authority or '').strip()
                if a and a not in authorities:
                    authorities.append(a)
            primary = next((r for r in jr if 'law' in (r.name or '').lower()
                            or 'pdpl' in (r.document_id or '').lower()
                            or 'act' in (r.name or '').lower()), jr[0] if jr else None)
            columns.append({
                'code': j, 'label': _GC_JUR[j][0], 'flag': _GC_JUR[j][1],
                'reg_count': len(jr),
                'primary': primary.name if primary else '—',
                'authorities': authorities,
                'regs': [{
                    'name': r.name, 'doc_id': r.document_id, 'scope': r.full_name,
                    'auth': r.issuing_authority,
                    'date': r.publication_date or r.effective_date,
                    'articles': r.section_identifiers,
                } for r in jr],
            })

        return render(request, 'pages/comparison_guidance.html', {
            'topics': _GC_TOPICS, 'topic': topic,
            'toc': _GC_TOC,
            'available': [{'code': c, 'label': _GC_JUR[c][0], 'flag': _GC_JUR[c][1]} for c in present],
            'selected': sel,
            'columns': columns,
        })
