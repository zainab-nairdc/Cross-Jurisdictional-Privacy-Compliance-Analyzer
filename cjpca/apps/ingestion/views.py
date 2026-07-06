from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, View

from apps.accounts.decorators import role_required
from apps.ingestion.models import IngestionJob, QuarantinedChunk


@method_decorator(role_required('admin'), name='dispatch')
class IngestionWidgetView(View):
    """
    GET /ingestion/widget/
    HTMX polling endpoint — returns the ingestion progress widget fragment.
    Polled every 3s from the home page.
    """
    # Map internal pipeline stage (1–6) to 4 user-facing display steps.
    STAGE_TO_DISPLAY_STEP = {1: 1, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4}

    def get(self, request):
        jobs = IngestionJob.objects.filter(
            status__in=[IngestionJob.QUEUED, IngestionJob.RUNNING]
        ).select_related('document')

        # Annotate each job with its plain-English display step (1–4)
        active_jobs = []
        for job in jobs:
            job.display_step = self.STAGE_TO_DISPLAY_STEP.get(job.current_stage, 1)
            active_jobs.append(job)

        return render(request, 'partials/_ingestion_widget.html', {'active_jobs': active_jobs})


@method_decorator(role_required('admin'), name='dispatch')
class QuarantineQueueView(TemplateView):
    """GET /ingestion/quarantine/ — admin review queue for chunks flagged by the
    prompt-injection scanner.

    The page is intentionally simple: a stat strip, a status filter, and a list
    where each row shows the matched rule, severity, the chunk content with the
    matched snippet highlighted, and Approve / Reject buttons. The point of the
    feature for the thesis demo is to make the defense visible — every flagged
    chunk surfaces here so the admin can prove the system caught it.
    """
    template_name = 'pages/quarantine_queue.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status = (self.request.GET.get('status') or QuarantinedChunk.PENDING).strip()
        if status not in dict(QuarantinedChunk.STATUS_CHOICES):
            status = QuarantinedChunk.PENDING

        qs = QuarantinedChunk.objects.select_related(
            'document', 'job', 'decided_by',
        ).order_by('-created_at')

        all_qs = qs
        if status:
            qs = qs.filter(status=status)

        ctx['rows']    = list(qs[:200])
        ctx['status']  = status
        ctx['status_choices'] = QuarantinedChunk.STATUS_CHOICES
        ctx['stats']   = {
            'pending':  all_qs.filter(status=QuarantinedChunk.PENDING).count(),
            'approved': all_qs.filter(status=QuarantinedChunk.APPROVED).count(),
            'rejected': all_qs.filter(status=QuarantinedChunk.REJECTED).count(),
            'high':     all_qs.filter(severity=QuarantinedChunk.SEVERITY_HIGH,
                                      status=QuarantinedChunk.PENDING).count(),
            'total':    all_qs.count(),
        }
        return ctx


@method_decorator(role_required('admin'), name='dispatch')
class QuarantineDecideView(View):
    """POST /ingestion/quarantine/<pk>/<action>/

    action ∈ {approve, reject}. Approve releases the chunk into Chroma + BM25
    so retrieval can surface it; reject marks it permanently held. Both write
    an AuditLog row tied to the acting admin so the chain of custody is clean.

    We deliberately do not allow a single endpoint to flip a decided chunk
    back to pending — once a human has reviewed it, the audit trail should
    show the original decision and a separate re-review event.
    """

    def post(self, request, pk: int, action: str):
        qc = get_object_or_404(QuarantinedChunk, pk=pk)
        if qc.status != QuarantinedChunk.PENDING:
            messages.warning(request, f'This chunk is already {qc.get_status_display().lower()}.')
            return HttpResponseRedirect(reverse('quarantine-queue'))

        from apps.history.audit import log_event, Actions

        if action == 'approve':
            ok = _release_chunk_to_index(qc)
            if not ok:
                messages.error(
                    request,
                    'Could not release the chunk to the index. Check the server log; '
                    'the chunk remains in the queue.',
                )
                return HttpResponseRedirect(reverse('quarantine-queue'))
            qc.status = QuarantinedChunk.APPROVED
            qc.decided_by = request.user
            qc.decided_at = timezone.now()
            qc.decision_note = (request.POST.get('note') or '').strip()[:500]
            qc.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
            log_event(
                request.user, Actions.QUARANTINE_APPROVED,
                request=request,
                target_type='ingestion.QuarantinedChunk', target_id=qc.pk,
                description=(
                    f'Released quarantined chunk #{qc.chunk_index} from "{qc.document.name}" '
                    f'(rule {qc.rule_id}) into the index'
                ),
                metadata={'document_id': qc.document_id, 'rule_id': qc.rule_id,
                          'severity': qc.severity, 'tier': qc.tier},
            )
            messages.success(request, f'Chunk released to index ({qc.rule_id}, {qc.severity}).')

        elif action == 'reject':
            qc.status = QuarantinedChunk.REJECTED
            qc.decided_by = request.user
            qc.decided_at = timezone.now()
            qc.decision_note = (request.POST.get('note') or '').strip()[:500]
            qc.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
            log_event(
                request.user, Actions.QUARANTINE_REJECTED,
                request=request,
                target_type='ingestion.QuarantinedChunk', target_id=qc.pk,
                description=(
                    f'Permanently rejected quarantined chunk #{qc.chunk_index} '
                    f'from "{qc.document.name}" (rule {qc.rule_id})'
                ),
                metadata={'document_id': qc.document_id, 'rule_id': qc.rule_id,
                          'severity': qc.severity, 'tier': qc.tier},
            )
            messages.success(request, f'Chunk rejected and permanently quarantined.')

        else:
            messages.error(request, f'Unknown action "{action}".')

        return HttpResponseRedirect(
            reverse('quarantine-queue') + f'?status={qc.status}'
        )


def _release_chunk_to_index(qc: QuarantinedChunk) -> bool:
    """Embed and index a single approved chunk into Chroma + BM25.

    Mirrors the embed + index stages of the main pipeline but on a single
    record. Best-effort: returns False on any error so the caller can leave
    the chunk in the queue rather than silently lose it.
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        meta = qc.chunk_metadata or {}
        chunk = {
            'content':         qc.content,
            'node_id':         qc.node_id or f'qc_{qc.pk}',
            'article_ref':     qc.section_title,
            'section_title':   qc.section_title,
            'hierarchy_path':  meta.get('hierarchy_path', ''),
            'chunk_id':        f'qc_{qc.pk}',
            'section_level':   meta.get('section_level', 1),
            'chunk_index':     qc.chunk_index,
            'chunk_total':     meta.get('chunk_total', 1),
            'parent_chunk_id': meta.get('parent_chunk_id', ''),
            'embed_skip':      False,
            'is_obligation':   meta.get('is_obligation', False),
            'chunk_type':      meta.get('chunk_type', 'body'),
            'jurisdiction':    meta.get('jurisdiction', ''),
            'regulation_name': meta.get('regulation_name', ''),
            'doc_title':       qc.document.full_name or qc.document.name,
            'doc_type':        meta.get('doc_type', ''),
            'issuing_authority': meta.get('issuing_authority', ''),
            'effective_date':  meta.get('effective_date', ''),
            'publication_date': meta.get('publication_date', ''),
            'last_updated':    meta.get('last_updated', ''),
            'language':        meta.get('language', 'English'),
            'scope_summary':   meta.get('scope_summary', ''),
            'source_url':      meta.get('source_url', ''),
        }
        from ingestion.embedder    import get_model, embed_chunks
        from ingestion.indexer     import get_collection, index_chunks
        from retrieval.bm25_store  import upsert_chunks as bm25_upsert
        st_model    = get_model()
        embeddings  = embed_chunks([chunk], st_model)
        collection  = get_collection()
        index_chunks([chunk], embeddings, collection)
        bm25_upsert([chunk])
        return True
    except Exception as exc:
        log.warning('Could not release quarantined chunk %s: %s', qc.pk, exc)
        return False
