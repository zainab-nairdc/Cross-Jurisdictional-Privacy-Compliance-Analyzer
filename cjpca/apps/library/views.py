import collections
import json
import logging
import re
import threading

from django.views.generic import TemplateView
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.utils.decorators import method_decorator

from apps.accounts.decorators import role_required
from apps.library.models import Document
from apps.ingestion.models import IngestionJob
from apps.comparison.concepts import CONCEPT_SEEDS

ALL_ROLES = ('analyst', 'reviewer', 'admin')

logger = logging.getLogger(__name__)

_JUR_LABELS = {
    Document.BAHRAIN: 'Bahrain',
    Document.INDIA:   'India',
    Document.KUWAIT:  'Kuwait',
    Document.BBK:     'BBK',
    Document.OTHER:   'Other',
}


def _purge_document(doc, actor=None, reason='', learning_mode='keep', request=None):
    """Delete a document AND its indexed content. Chunks live in bm25 + chroma (and
    the Arabic store for Arabic docs); doc.delete() alone leaves them searchable as
    ghost citations. Fail-soft per store so one unavailable backend can't strand a
    half-deleted document. Returns the purged document's name."""
    name, doc_type, pk = doc.name, doc.doc_type, doc.pk
    title = getattr(doc, 'chunk_doc_title', '') or doc.full_name or doc.name
    try:
        from apps.feedback.services import purge_document_learning
        learning = purge_document_learning(doc, mode=learning_mode)
    except Exception:
        learning = {'mode': learning_mode, 'signals': 0, 'gold': 0}
    try:
        from retrieval.bm25_store import delete_by_doc_title
        from ingestion.indexer import delete_doc_chunks
        delete_by_doc_title(title)
        delete_doc_chunks(title)
    except Exception:
        logger.exception('chunk purge failed for %s', title)
    if getattr(doc, 'language', '') == Document.ARABIC:
        try:
            from arabic import store as ar_store
            ar_store.delete_source(title)
        except Exception:
            pass
    doc.delete()
    try:
        from apps.history.audit import log_event, Actions
        who = getattr(actor, 'username', None) or 'system'
        log_event(actor, Actions.DOCUMENT_DELETE,
                  request=request,
                  target_type='library.Document', target_id=pk,
                  description=f'{who} deleted document "{name}"' + (f' ({reason})' if reason else ''),
                  metadata={'doc_name': name, 'doc_type': doc_type, 'reason': reason,
                            'learning_mode': learning.get('mode'),
                            'learning_signals': learning.get('signals'),
                            'learning_gold': learning.get('gold')})
    except Exception:
        pass
    return name


def _jur_label(doc):
    """Display label for a jurisdiction. get_jurisdiction_display() only maps the
    built-in choices, so countries added later (qatar, oman, egypt...) come back as
    the raw lowercase key. Title-case those, keep short codes upper: 'qatar' ->
    'Qatar', 'saudi_arabia' -> 'Saudi Arabia', 'eu' -> 'EU'."""
    raw = (getattr(doc, 'jurisdiction', '') or '').strip()
    label = doc.get_jurisdiction_display() if raw else ''
    if label and label != raw:
        return label
    if not raw:
        return ''
    return raw.upper() if len(raw) <= 3 else raw.replace('_', ' ').title()


def _learning_counts(docs):
    """{doc_pk: {'signals': n, 'gold': n}}: what the RAG feedback loop has learned
    from each document, so the delete dialog can state the cost of purging it in
    numbers. Built with a handful of aggregate queries rather than per-document
    lookups. Fail-soft: an empty map just hides the counts."""
    from django.db.models import Q
    counts = {d.pk: {'signals': 0, 'gold': 0} for d in docs}
    try:
        from apps.comparison.models import ComparisonResult
        from apps.feedback.models import FeedbackSignal, GoldExemplar
    except Exception:
        return counts
    try:
        ids = list(counts.keys())
        by_name = {d.name: d.pk for d in docs}
        # result pk -> the document(s) whose run produced it
        result_docs: dict[int, set] = {}
        rows = (ComparisonResult.objects
                .filter(Q(run__reg_a_id__in=ids) | Q(run__reg_b_id__in=ids))
                .values_list('pk', 'run__reg_a_id', 'run__reg_b_id'))
        for rpk, a, b in rows:
            for dpk in (a, b):
                if dpk in counts:
                    result_docs.setdefault(rpk, set()).add(dpk)
        for sid in (FeedbackSignal.objects
                    .filter(source_app='comparison', source_id__in=result_docs.keys())
                    .values_list('source_id', flat=True)):
            for dpk in result_docs.get(sid, ()):
                counts[dpk]['signals'] += 1
        for sid, reg_a, reg_b in GoldExemplar.objects.values_list('source_id', 'reg_a', 'reg_b'):
            hit = set(result_docs.get(sid, ()))
            for name in (reg_a, reg_b):          # gold also references docs by NAME
                if name in by_name:
                    hit.add(by_name[name])
            for dpk in hit:
                counts[dpk]['gold'] += 1
    except Exception:
        logger.exception('_learning_counts failed')
    return counts


def _prune_stale_drafts(max_age_hours: int = 2):
    """Delete abandoned upload drafts — documents that were analysed (status
    'review') but never confirmed/indexed — once they're older than a couple
    hours (well past any active review session). Stops unfinished drafts from
    piling up in the library. Files are removed too; drafts have no indexed
    chunks, so the pre_delete purge is a no-op. Fail-soft."""
    import os
    from datetime import timedelta
    from django.utils import timezone
    try:
        cutoff = timezone.now() - timedelta(hours=max_age_hours)
        stale = list(Document.objects.filter(status='review', upload_date__lt=cutoff))
        for d in stale:
            try:
                if d.file and d.file.name and os.path.exists(d.file.path):
                    os.remove(d.file.path)
            except Exception:
                pass
        if stale:
            Document.objects.filter(pk__in=[d.pk for d in stale]).delete()
            logger.info('Pruned %d stale upload draft(s).', len(stale))
    except Exception:
        logger.exception('stale-draft prune failed')


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
@method_decorator(ensure_csrf_cookie, name='dispatch')
class AddDocumentView(TemplateView):
    """GET /library/add/ — the guided upload wizard on its own full page
    (instead of the global modal). Renders the same wizard component in
    page mode, with a Format-guidelines panel and recent uploads alongside."""
    template_name = 'pages/add_document.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['recent_uploads'] = list(
            Document.objects.order_by('-upload_date')[:5]
            .only('id', 'name', 'doc_type', 'status', 'upload_date'))
        ctx['guidelines'] = [
            'PDF, DOCX or TXT — one document per upload.',
            'Text-based PDFs work best; scanned pages are OCR’d (slower).',
            'Language, jurisdiction and structure are auto-detected — you confirm them.',
            'Everything is processed locally; nothing leaves this machine.',
        ]
        # Tell base.html not to also render the global modal wizard here.
        ctx['on_add_document_page'] = True
        return ctx


class RegulationsView(TemplateView):
    """GET /library/regulations/ — regulations library (Page 5, §8.7).

    ``ensure_csrf_cookie`` forces Django to set the csrftoken cookie on every
    GET. Without it, non-admin users (who don't see the upload modal that
    contains ``{% csrf_token %}``) never get the cookie set, and tag-add
    POSTs fail with "CSRF token has incorrect length" (the JS reads an
    empty cookie and sends an empty header).
    """
    template_name = 'pages/regulations.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        _prune_stale_drafts()

        # Send the full regulation set to the browser; Alpine filters/searches
        # client-side from the docs_json payload (see regsPage() in
        # templates/pages/regulations.html). No server-side ?jur= or ?q=
        # filtering — those URL params have no effect.
        regs_list = list(
            Document.objects
            .filter(doc_type=Document.REGULATION)
            .prefetch_related('ingestion_jobs')
            .order_by('-upload_date')
        )

        # Stat tabs at top of the page (All / Indexed / Processing / Failed).
        all_regs = Document.objects.filter(doc_type=Document.REGULATION)
        ctx['stats'] = {
            'total':      all_regs.count(),
            'indexed':    all_regs.filter(status=Document.INDEXED).count(),
            'processing': all_regs.filter(status=Document.PROCESSING).count(),
            'failed':     all_regs.filter(status=Document.FAILED).count(),
        }

        def _type_label(name):
            n = name.lower()
            if 'ministerial' in n or 'order' in n: return 'Implementing Reg.'
            if 'act' in n or 'law' in n:           return 'Primary Law'
            if 'guide' in n or 'circular' in n:    return 'Guidance'
            return 'Regulation'

        def _enrich_topics(doc):
            """Normalise cached_topics to the [{id, label}] shape the template
            renders. Tolerates both the legacy regex format (list of concept-id
            strings keyed on CONCEPT_SEEDS) and the new LLM format (list of
            {id, label} dicts from classify_doc_topics)."""
            raw = doc.cached_topics or []
            out: list[dict] = []
            for item in raw[:5]:
                if isinstance(item, dict) and item.get('id') and item.get('label'):
                    out.append({'id': item['id'], 'label': item['label']})
                elif isinstance(item, str) and item in CONCEPT_SEEDS:
                    seed = CONCEPT_SEEDS[item]
                    out.append({'id': item, 'label': seed['label']})
            return out

        # Compute topic badges once per doc; reused for the rendered cards
        # AND the JSON blob Alpine consumes.
        for d in regs_list:
            d.topics = _enrich_topics(d)
            # get_jurisdiction_display() returns the raw lowercase key for
            # jurisdictions added after the model's choices were fixed ('ksa',
            # 'qatar', ...). The rendered table needs the same tidy label the
            # JSON payload gets, so attach it here.
            d.jur_label = _jur_label(d)

        _learned = _learning_counts(regs_list)

        docs_json = json.dumps([
            {
                'id':                d.pk,
                'name':              d.name,
                'type_label':        _type_label(d.name),
                'full_name':         d.full_name or '',
                'jurisdiction':      d.jurisdiction,
                'jurisdiction_display': _jur_label(d),
                'status':            d.status,
                'attention':         d.attention,
                'issuing_authority': d.issuing_authority or '',
                'effective_date':    d.effective_date.strftime('%d %b %Y') if d.effective_date else '',
                'version':           d.version or '',
                'chunk_count':       d.chunk_count,
                'notes':             d.notes or '',
                'source_url':        d.source_url or '',
                'file_url':          d.file.url if d.file else '',
                'upload_date':       d.upload_date.strftime('%d %b %Y'),
                'delete_url':        f'/library/delete/{d.pk}/',
                'tags':              _normalise_tag_list(d.tags),
                'cached_topics':     d.topics,
                # Hydrated from data/metadata.csv via manage.py full_ingest.
                'publication_date':    d.publication_date.strftime('%d %b %Y') if d.publication_date else '',
                'last_updated':        d.last_updated.strftime('%d %b %Y') if d.last_updated else '',
                'section_identifiers': d.section_identifiers or '',
                'document_id':         d.document_id or '',
                'regulation_category': d.regulation_category or '',
                'privacy_relevance':   d.privacy_relevance or '',
                'applicable_sector':   d.applicable_sector or '',
                'superseded':          bool(d.superseded),
                'version_status':      d.version_status,
                'superseded_by':       d.superseded_by or '',
                'parent_regulation':   d.parent_regulation or '',
                'family_id':           d.family_root_id,
                'version_of':          d.version_of_id,
                'cross_references':    d.cross_references or '',
                'concept_tags_csv':    d.concept_tags_csv or [],
                # Feedback-loop footprint, shown in the delete dialog.
                'learned_signals':     _learned.get(d.pk, {}).get('signals', 0),
                'learned_gold':        _learned.get(d.pk, {}).get('gold', 0),
            }
            for d in regs_list
        ])

        # Custom jurisdictions / categories the app has learned (created from
        # prior uploads via the "NEW — will be added" confirm). These extend the
        # wizard's built-in option lists so previously-added countries/categories
        # are selectable and don't re-register as new.
        from apps.library.models import TaxonomyNode
        custom_jurisdictions = list(
            TaxonomyNode.objects.filter(node_type=TaxonomyNode.COUNTRY, is_active=True))
        custom_categories = list(
            TaxonomyNode.objects.filter(node_type=TaxonomyNode.TOPIC, is_active=True))

        ctx.update({
            'regulations': regs_list,
            'docs_json':   docs_json,
            'preset_tags': PRESET_TAGS,
            'custom_jurisdictions': custom_jurisdictions,
            'custom_categories':    custom_categories,
        })
        return ctx


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
@method_decorator(ensure_csrf_cookie, name='dispatch')
class PoliciesView(TemplateView):
    """GET /library/policies/ — internal policies library (Page 6).

    See RegulationsView for why ``ensure_csrf_cookie`` is here — same
    reason: non-admins need the csrftoken cookie set so the in-page tag
    POSTs succeed.
    """
    template_name = 'pages/policies.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        _prune_stale_drafts()

        # one query, materialised so we can iterate twice (stats + docs_json)
        # without re-hitting the DB. Alpine handles all filtering client-side.
        policies_list = list(
            Document.objects.filter(doc_type=Document.POLICY).order_by('-upload_date')
        )

        ctx['stats'] = {
            'indexed':    sum(1 for d in policies_list if d.status == Document.INDEXED),
            'processing': sum(1 for d in policies_list if d.status == Document.PROCESSING),
            'failed':     sum(1 for d in policies_list if d.status == Document.FAILED),
        }

        def _type_label(name):
            n = name.lower()
            if 'sop' in n or 'procedure' in n: return 'SOP'
            if 'guideline' in n or 'guide' in n: return 'Guideline'
            if 'standard' in n: return 'Standard'
            return 'Policy'

        # Topic stickers — same shape RegulationsView emits, reused for cards
        # and the JSON blob Alpine consumes.
        for d in policies_list:
            raw = d.cached_topics or []
            d.topics = [
                {'id': item['id'], 'label': item['label']}
                for item in raw[:5]
                if isinstance(item, dict) and item.get('id') and item.get('label')
            ]

        docs_json = json.dumps([
            {
                'id':                d.pk,
                'name':              d.name,
                'type_label':        _type_label(d.name),
                'full_name':         d.full_name or '',
                'jurisdiction':      d.jurisdiction,
                'status':            d.status,
                'attention':         d.attention,
                'issuing_authority': d.issuing_authority or '',
                'effective_date':    d.effective_date.strftime('%d %b %Y') if d.effective_date else '',
                'version':           d.version or '',
                'chunk_count':       d.chunk_count,
                'notes':             d.notes or '',
                'source_url':        d.source_url or '',
                'file_url':          d.file.url if d.file else '',
                'upload_date':       d.upload_date.strftime('%d %b %Y'),
                'delete_url':        f'/library/delete/{d.pk}/',
                'tags':              _normalise_tag_list(d.tags),
                # Hydrated from data/metadata.csv via manage.py full_ingest.
                'publication_date':    d.publication_date.strftime('%d %b %Y') if d.publication_date else '',
                'last_updated':        d.last_updated.strftime('%d %b %Y') if d.last_updated else '',
                'section_identifiers': d.section_identifiers or '',
                'document_id':         d.document_id or '',
                'regulation_category': d.regulation_category or '',
                'privacy_relevance':   d.privacy_relevance or '',
                'applicable_sector':   d.applicable_sector or '',
                'superseded':          bool(d.superseded),
                'version_status':      d.version_status,
                'superseded_by':       d.superseded_by or '',
                'parent_regulation':   d.parent_regulation or '',
                'family_id':           d.family_root_id,
                'version_of':          d.version_of_id,
                'cross_references':    d.cross_references or '',
                'concept_tags_csv':    d.concept_tags_csv or [],
            }
            for d in policies_list
        ])

        ctx.update({
            'policies':    policies_list,
            'docs_json':   docs_json,
            'preset_tags': PRESET_TAGS,
        })
        return ctx


@method_decorator(role_required('admin'), name='dispatch')
class DocumentSupersedeView(View):
    """POST /library/<pk>/supersede/  {new_pk} — mark this regulation version
    superseded by a newer one, link the lineage, and report the approved analyses
    that now need re-review. The old version is kept (never deleted).

    Auth: authenticated only, matching the PoC's relaxed RBAC. In production this
    is an Admin/Business-Administrator action (per the roles definition)."""

    def post(self, request, pk):
        from django.http import JsonResponse
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Sign in required.'}, status=403)
        old = get_object_or_404(Document, pk=pk)
        new = Document.objects.filter(pk=request.POST.get('new_pk')).first()
        if not new:
            return JsonResponse({'error': 'Pick the new version.'}, status=400)
        if new.pk == old.pk:
            return JsonResponse({'error': 'A version cannot supersede itself.'}, status=400)
        affected = old.supersede_with(new, actor=request.user)
        rows = [{'run_id': r.run_id, 'citation_a': r.citation_a, 'citation_b': r.citation_b or ''}
                for r in (affected[:50] if affected is not None else [])]
        return JsonResponse({
            'ok': True, 'old': old.name, 'new': new.name,
            'old_status': old.version_status, 'new_status': new.version_status,
            'affected_count': affected.count() if affected is not None else 0,
            'affected': rows,
        })


class DocumentDeleteView(View):
    """GET/POST /library/delete/<pk>/ — confirm + delete a document."""

    def get(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        chunk_count = getattr(doc, 'chunk_count', None) or 0
        try:
            from apps.feedback.services import document_learning_footprint
            learning = document_learning_footprint(doc)
        except Exception:
            learning = {'signals': 0, 'gold': 0}
        return render(request, 'pages/document_delete_confirm.html', {
            'doc': doc,
            'chunk_count': chunk_count,
            'learning': learning,
            'jur_label': _jur_label(doc),
        })

    def post(self, request, pk):
        try:
            doc = Document.objects.get(pk=pk)
            # One purge path shared with the upload wizard's "delete the old
            # version" choice, so the two can't drift: chunks out of bm25 + chroma
            # (+ the Arabic store) before the row goes, or doc.delete() leaves
            # searchable ghost chunks that still surface as citations.
            _purge_document(
                doc, actor=request.user, request=request,
                learning_mode=('purge' if request.POST.get('learning_mode') == 'purge' else 'keep'),
            )
        except Document.DoesNotExist:
            pass
        if request.htmx:
            response = HttpResponse()
            response['HX-Redirect'] = request.META.get('HTTP_REFERER', '/library/regulations/')
            return response
        return redirect(request.META.get('HTTP_REFERER', 'library-regulations'))


@method_decorator(role_required('admin'), name='dispatch')
class DocumentUploadView(View):
    """POST /library/upload/ — upload new regulation or policy document."""

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return HttpResponseBadRequest('No file provided.')

        required = {
            'name':              request.POST.get('name', '').strip(),
            'jurisdiction':      request.POST.get('jurisdiction', '').strip(),
            'effective_date':    request.POST.get('effective_date', '').strip(),
            'issuing_authority': request.POST.get('issuing_authority', '').strip(),
            'full_name':         request.POST.get('full_name', '').strip(),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            return HttpResponseBadRequest(f'Missing required fields: {", ".join(missing)}')

        name         = request.POST.get('name', '').strip() or file.name
        doc_type     = request.POST.get('doc_type', Document.REGULATION)
        jurisdiction = request.POST.get('jurisdiction', Document.OTHER)

        effective_raw = request.POST.get('effective_date', '').strip()
        effective_date = None
        if effective_raw:
            from datetime import date
            try:
                effective_date = date.fromisoformat(effective_raw)
            except ValueError:
                pass

        doc = Document.objects.create(
            name=name,
            full_name=request.POST.get('full_name', '').strip(),
            doc_type=doc_type,
            jurisdiction=jurisdiction,
            language=(request.POST.get('language') or 'en').strip(),
            version=request.POST.get('version', '').strip(),
            issuing_authority=request.POST.get('issuing_authority', '').strip(),
            effective_date=effective_date,
            source_url=request.POST.get('source_url', '').strip(),
            notes=request.POST.get('notes', '').strip(),
            status=Document.PROCESSING,
            file=file,
        )
        job = IngestionJob.objects.create(
            document=doc,
            status=IngestionJob.QUEUED,
            current_stage=1,
            created_by=request.user if request.user.is_authenticated else None,
        )

        from apps.history.audit import log_event, Actions
        log_event(
            request.user, Actions.DOCUMENT_UPLOAD,
            request=request,
            target_type='library.Document', target_id=doc.pk,
            description=f'{request.user.username} uploaded {doc_type} "{name}"',
            metadata={
                'doc_name': name, 'doc_type': doc_type,
                'jurisdiction': jurisdiction,
            },
        )

        # Kick off the background ingestion pipeline immediately.
        from apps.ingestion.pipeline import run_job
        run_job(job.pk)

        # HTMX: redirect back to home so the polling widget picks up the new job
        if request.htmx:
            response = HttpResponse()
            response['HX-Redirect'] = '/'
            return response

        return redirect('home')


# ── Document viewer ────────────────────────────────────────────────────────────

_HEADING_RE = re.compile(
    r'^(Article|Section|Chapter|Part|Schedule|Annex|Clause)\s+\d+',
    re.IGNORECASE,
)


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class DocumentViewerView(View):
    """GET /library/view/<pk>/?highlight=<article_ref> — HTMX partial."""

    def get(self, request, pk):
        doc    = get_object_or_404(Document, pk=pk)

        # Arabic documents are stored in the isolated Arabic collection, not in
        # bm25_index — read their chunks from there and render the same viewer.
        if doc.language == Document.ARABIC:
            from arabic import store as ar_store
            ar_chunks = ar_store.get_chunks(doc.chunk_doc_title)
            rows = []
            for i, c in enumerate(ar_chunks):
                n = c.get('article_number')
                ref = f"Article ({n})" if isinstance(n, int) else (c.get('term') or '')
                rows.append({'idx': i, 'content': c.get('text', ''), 'ref': ref})
            # Highlight the cited article: match the quote (from the citation) to
            # its chunk by whitespace-insensitive substring — robust because the
            # quote comes from the same stored Arabic chunk text.
            import re as _re
            highlight_ref = request.GET.get('highlight', '').strip()
            highlight_idx = None
            if highlight_ref:
                _hn = _re.sub(r'\s+', '', highlight_ref)[:80]
                if _hn:
                    for r in rows:
                        if _hn in _re.sub(r'\s+', '', r['content'] or ''):
                            highlight_idx = r['idx']
                            break
            return render(request, 'partials/_doc_viewer_body.html', {
                'doc':           doc,
                'chunks':        [r['content'] for r in rows],
                'chunk_rows':    rows,
                'sections':      [{'index': r['idx'], 'heading': r['ref']} for r in rows if r['ref']],
                'highlight_ref': highlight_ref,
                'highlight_idx': highlight_idx,
                'is_arabic':     True,
            })

        # Pull chunks WITH their node_ids so we can highlight by chunk_id
        # (rock-solid) when the caller provides one, with the existing
        # substring-match path as a fallback for legacy callers.
        from apps.comparison.concepts import get_doc_chunks_with_ids
        chunks_with_ids = get_doc_chunks_with_ids(doc, limit=200)
        chunks   = [c for _, c, _ in chunks_with_ids]
        node_ids = [nid for nid, _, _ in chunks_with_ids]
        refs     = [r for _, _, r in chunks_with_ids]

        highlight_ref = request.GET.get('highlight', '').strip()
        chunk_id      = request.GET.get('chunk_id', '').strip()
        highlight_idx = None

        # Pass 0 — exact chunk_id match. Always works regardless of OCR
        # artifacts, LLM verbatim drift, or whitespace differences. Used
        # by the policy mapping workspace which stores chunk_ids on every
        # ObligationMapping row.
        if chunk_id:
            try:
                highlight_idx = node_ids.index(chunk_id)
            except ValueError:
                highlight_idx = None  # chunk_id from a different doc; fall through

        # Pass 1 — whitespace-normalized substring match. Used when the
        # caller only has the verbatim quote (legacy paths, comparison view).
        # Pass 2 — no-whitespace fallback for OCR space artifacts.
        # Pass 3 — alpha-num only fallback. Strips smart quotes, dashes,
        # parentheses, periods etc. that the LLM frequently normalises
        # differently from the indexed text (e.g. "Article (10)" vs
        # "Article 10", em-dash vs hyphen, "don't" vs "don’t").
        import re as _re
        norm_needle  = " ".join(highlight_ref.lower().split()) if highlight_ref else ""
        sq_needle    = norm_needle.replace(" ", "")
        alpha_needle = _re.sub(r'[^a-z0-9]+', '', norm_needle) if norm_needle else ""

        # Build the navigation sidebar from the stored article_ref. The chunker
        # strips headings out of the chunk body, so parsing the first line no
        # longer finds them — article_ref is the reliable source of "Article (N)".
        # Fall back to first-line heading detection only for chunks with no ref.
        sections = []
        for i, chunk in enumerate(chunks):
            ref = (refs[i] or '').strip()
            if ref:
                sections.append({'index': i, 'heading': ref})
            else:
                first_line = chunk.strip().split('\n')[0][:100].strip()
                if _HEADING_RE.match(first_line):
                    sections.append({'index': i, 'heading': first_line})
            # Substring-match path — only run if chunk_id didn't already pin
            # the highlight idx.
            if highlight_idx is None and norm_needle:
                norm_hay = " ".join(chunk.lower().split())
                if norm_needle in norm_hay:
                    highlight_idx = i
                elif len(sq_needle) >= 30:
                    sq_hay = norm_hay.replace(" ", "")
                    if sq_needle in sq_hay:
                        highlight_idx = i
                # Punctuation-stripped fallback: try increasingly short
                # prefixes of the needle so a quote that only matches the
                # first half still pins to the right chunk. Floors at 40
                # alphanum chars to avoid spurious matches.
                if highlight_idx is None and len(alpha_needle) >= 40:
                    alpha_hay = _re.sub(r'[^a-z0-9]+', '', norm_hay)
                    if alpha_needle in alpha_hay:
                        highlight_idx = i
                    else:
                        # Try the first 80 alphanum chars only — the LLM
                        # often drops trailing punctuation/citations.
                        prefix = alpha_needle[:80]
                        if len(prefix) >= 40 and prefix in alpha_hay:
                            highlight_idx = i

        # Pair each chunk with its article_ref so the viewer can print the
        # "Article (N)" label above the body (headings were stripped at ingest).
        chunk_rows = [
            {'idx': i, 'content': chunks[i], 'ref': (refs[i] or '').strip()}
            for i in range(len(chunks))
        ]

        return render(request, 'partials/_doc_viewer_body.html', {
            'doc':           doc,
            'chunks':        chunks,
            'chunk_rows':    chunk_rows,
            'sections':      sections,
            'highlight_ref': highlight_ref,
            'highlight_idx': highlight_idx,
        })


def _count_divisions(text: str) -> dict:
    """Count a document's legal divisions by regex over the full text — exact and
    deterministic (Article/Chapter/Section/Part + Recitals). Returns {name: count}
    keyed lowercase. Numbered runs (Articles 1..N) use the sequential run length so
    stray cross-references (e.g. 'Article 263 TFEU') don't inflate the total."""
    if not text:
        return {}
    out = {}
    for name in ('part', 'chapter', 'section', 'article', 'rule', 'clause'):
        nums = {m.group(1).upper() for m in re.finditer(
            rf'(?im)^[ \t#>*]*{name}[ \t]*\(?\s*([0-9]+|[IVXLCM]+)\b', text)}
        arabic = sorted(int(n) for n in nums if n.isdigit())
        if arabic:
            present, run = set(arabic), 0
            for i in range(1, max(arabic) + 2):
                if i in present:
                    run = i
                elif i - run > 5:      # a big gap → past the real sequence
                    break
            cnt = run or len(nums)
        else:
            cnt = len(nums)
        if cnt >= 2:
            out[name] = cnt
    # Recitals — "(N)" paragraphs in the preamble (before the first Article 1).
    fa = re.search(r'(?im)^[ \t#>*]*article[ \t]*\(?\s*1\b', text)
    head = text[:fa.start()] if fa else ''
    recs = {int(m.group(1)) for m in re.finditer(r'(?m)^\s*[-*]?\s*\(\s*(\d+)\s*\)', head)}
    if len(recs) >= 5:
        out['recitals'] = max(recs)
    return out


def _flat_chunk_summary(doc):
    """Fallback: a flat article list built from the indexed chunks. Deduped by
    article_ref so long sub-chunked articles don't repeat."""
    from collections import OrderedDict
    from apps.comparison.concepts import get_doc_chunks_with_ids
    rows = get_doc_chunks_with_ids(doc, limit=400)
    if not rows:
        return None
    nodes = []
    seen = set()
    for _nid, content, ref in rows:
        ref = (ref or '').strip().strip('()').strip()
        key = ref.lower()
        if key in seen:
            continue
        seen.add(key)
        first = (content or '').strip().split('\n', 1)[0][:70]
        nodes.append({'type': 'article', 'number': None,
                      'label': ref or 'Section', 'title': first})
    tree = OrderedDict([('Articles', OrderedDict([('—', nodes)]))])
    return {'parts': 0, 'sections': 0, 'articles': len(nodes),
            'definitions': 0, 'total_nodes': len(nodes), 'tree': tree,
            'suggested_type': 'regulation'}


def _english_structure_summary(doc):
    """Clean HIERARCHICAL structure for an English doc: reads the whole document
    and uses the LLM structure detector to produce Chapters → Articles (with
    recitals grouped), instead of a flat dump of every chunk. Cached by content
    hash so the LLM pass runs once per document."""
    from collections import OrderedDict
    from django.core.cache import cache
    ck = f'struct_v2_{doc.pk}_{(doc.content_hash or "")[:12]}'
    cached = cache.get(ck)
    if cached is not None:
        return cached or None

    structure = {}
    text = ''
    try:
        if doc.file and doc.file.name:
            from reasoning.doc_intel import head_text, infer_structure
            text = head_text(doc.file.path, max_pages=1000)
            if text:
                structure = infer_structure(text)
    except Exception:
        logger.exception('structure inference failed for doc %s', doc.pk)

    outline = structure.get('outline') or []
    if not outline:
        # No hierarchy detected — fall back to the deduped flat list.
        return _flat_chunk_summary(doc)

    tree = OrderedDict()
    n_parts = n_articles = 0
    for node in outline:
        label = (node.get('label') or '').strip()
        title = (node.get('title') or '').strip()
        kids = node.get('children') or []
        head = f"{label} — {title}" if title else (label or 'Section')
        if kids:
            n_parts += 1
            n_articles += len(kids)
            tree[head] = OrderedDict([('—', [
                {'type': 'article', 'number': None,
                 'label': (c.get('label') or '').strip() or '—',
                 'title': (c.get('title') or '').strip()}
                for c in kids])])
        else:
            # Standalone node — a recitals/preamble group or a flat article.
            is_recital = label.lower().startswith(('recital', 'preamble'))
            tree[head] = OrderedDict([('—', [
                {'type': 'note' if is_recital else 'article', 'number': None,
                 'label': label or '—', 'title': title}])])
            if not is_recital:
                n_articles += 1

    # Dynamic level counts — labelled by the document's OWN scheme (Chapters /
    # Articles / Recitals …), counted DETERMINISTICALLY by regex over the full
    # text so they're exact (11/99/173 for GDPR), not the LLM's grouped estimate.
    def _plural(w):
        w = (w or '').strip() or 'Section'
        return w if w.endswith('s') else w + 's'
    levels = [lv for lv in (structure.get('levels') or []) if lv]
    div = _count_divisions(text)
    counts = []
    if len(levels) > 1 and div.get(levels[0].lower()):
        counts.append({'label': _plural(levels[0]), 'value': div[levels[0].lower()]})
    inner = levels[1] if len(levels) > 1 else (levels[0] if levels else 'Article')
    counts.append({'label': _plural(inner),
                   'value': div.get(inner.lower()) or n_articles})
    if div.get('recitals'):
        counts.append({'label': 'Recitals', 'value': div['recitals']})

    summary = {'parts': n_parts, 'sections': 0, 'articles': n_articles,
               'definitions': 0, 'total_nodes': n_articles,
               'tree': tree, 'scheme': structure.get('scheme', ''),
               'counts': counts,
               'suggested_type': doc.doc_type or 'regulation'}
    cache.set(ck, summary, 3600)
    return summary


class DocumentStructureView(View):
    """GET /library/structure/<pk>/ — the Legal-Node structure preview.

    Renders the detected hierarchy for a document. Arabic docs read a full
    part > section > article/definition tree from the isolated Arabic store;
    English docs get a flat article list built from their indexed chunks."""

    def get(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        summary = None
        rtl = (doc.language == Document.ARABIC)
        if doc.language == Document.ARABIC:
            try:
                from arabic import store as ar_store
                from arabic.analyze import structure_summary, suggest_type
                chunks = ar_store.get_chunks(doc.chunk_doc_title)
                if chunks:
                    summary = structure_summary(chunks)
                    summary['suggested_type'] = suggest_type(summary)
            except Exception:
                summary = None
        else:
            try:
                summary = _english_structure_summary(doc)
            except Exception:
                summary = None
        return render(request, 'partials/_structure_preview.html',
                      {'doc': doc, 'summary': summary, 'rtl': rtl})


def _run_doc_intel(pdf_path, metadata_only=False, progress=None):
    """Local-LLM metadata (+ optional structure) inference over the WHOLE document.

    Both passes read every page: extract_metadata sweeps the full text window by
    window (one model call per ~20k chars) and structure regex-scans all of it.
    That makes analyze slower on a long regulation, deliberately — metadata
    inferred from the first pages alone was wrong on documents that only name
    their jurisdiction and governing law well past the opening.

    Returns (suggested_meta: dict, structure_html: str). Everything is a
    suggestion the user confirms; fail-soft to ({}, '') so a model hiccup never
    blocks an upload."""
    try:
        from reasoning.doc_intel import (
            head_text, extract_metadata, infer_structure, structure_to_html,
            metadata_steps, AnalysisCancelled,
        )
    except Exception:
        return {}, ''
    try:
        # Read the file ONCE, in full, and share it between both passes.
        text = head_text(pdf_path, max_pages=1000)
        if not text:
            return {}, ''
        # The denominator is fixed BEFORE any work starts: the metadata calls
        # (head + one per window) plus the single structure call. A total that
        # grew as phases were discovered would make the bar slide backwards.
        total = metadata_steps(text) + (0 if metadata_only else 1)
        meta = extract_metadata(text, progress=progress, step_total=total)
        scan = (meta or {}).get('scan') or {}
        if scan:
            logger.info('doc-intel %s: read %d/%d windows (%d chars), '
                        'jurisdiction votes=%s', pdf_path,
                        scan.get('windows_read'), scan.get('windows_total'),
                        scan.get('chars_read'), scan.get('jurisdiction_votes'))
        if metadata_only:
            return meta, ''
        structure = infer_structure(text)
        # Structure is the last model call, so this completes the count.
        if progress:
            try:
                progress(total, total, 'Preparing your review')
            except Exception:
                logger.debug('progress callback failed', exc_info=True)
        return meta, structure_to_html(structure)
    except AnalysisCancelled:
        # Not a failure — the caller asked to stop because nobody is waiting for
        # the answer any more. Propagate so it isn't logged as an error.
        raise
    except Exception:
        logger.exception('doc-intel failed for %s', pdf_path)
        return {}, ''


def _streaming_analysis(doc, lang):
    """Run doc-intel and stream its progress as newline-delimited JSON.

    A full-document analysis is many model calls — 43 on the largest document in
    the corpus — and the wizard used to show a spinner for the whole of it with
    no way to tell a working scan from a hung one. Progress is delivered on the
    SAME request rather than by polling a status endpoint: the response body is
    written incrementally as the work happens, so there is one request, one
    source of truth, and nothing to reconcile between a job and its status.

    Each line is a complete JSON object:
        {"type": "progress", "done": 12, "total": 43, "label": "..."}
        {"type": "result",   ...the payload the wizard already consumes...}
        {"type": "error",    "error": "..."}
    The final line is always a result or an error, so the client can treat the
    last object exactly as it treated the old single JSON response.
    """
    from django.http import StreamingHttpResponse
    from reasoning.doc_intel import AnalysisCancelled

    def stream():
        # Progress events are produced deep inside doc-intel and consumed here,
        # so they are handed over through a queue the callback appends to and
        # the generator drains — the callback cannot yield on its own. Every
        # name here is created per call, so two concurrent analyses share
        # nothing; there is no module-level progress state anywhere.
        # deque.append/popleft are individually atomic, which is the only
        # synchronisation needed between the worker and this generator.
        pending: "collections.deque" = collections.deque()
        cancelled = threading.Event()

        def on_progress(done, total, label=''):
            # Checked here because progress is reported between model calls —
            # the one place it is safe to abandon the work. Raising unwinds the
            # scan; a thread cannot be killed from outside, so cancellation has
            # to be cooperative.
            if cancelled.is_set():
                raise AnalysisCancelled()
            pending.append({'type': 'progress', 'done': int(done),
                            'total': int(total), 'label': str(label)})

        def drain():
            while pending:
                yield json.dumps(pending.popleft()) + '\n'

        # doc-intel blocks, so run it off-thread and flush whatever the callback
        # has queued while it works. Without this the queue would only be
        # readable after the analysis had already finished.
        box: dict = {}

        def work():
            try:
                box['out'] = _run_doc_intel(doc.file.path, progress=on_progress)
            except AnalysisCancelled:
                box['cancelled'] = True
                logger.info('analysis cancelled for %s — client disconnected', doc.pk)
            except BaseException as exc:     # noqa: BLE001 — see 'unfinished' below
                logger.exception('analysis failed for %s', doc.pk)
                box['exc'] = exc

        t = threading.Thread(target=work, daemon=True,
                             name=f'doc-intel-{doc.pk}')
        t.start()
        try:
            while t.is_alive():
                yield from drain()
                t.join(timeout=0.25)
            yield from drain()                          # anything queued at the end
        finally:
            # Reached on normal completion AND when the client goes away, which
            # closes this generator and raises GeneratorExit at the yield above.
            # Without this the worker would keep running model calls — minutes
            # of GPU time — for an upload nobody is waiting for.
            cancelled.set()

        if box.get('cancelled'):
            return

        # Neither a result nor an exception means the worker died in a way it
        # could not report. Emitting the default empty result here would look
        # like a successful analysis that simply found nothing, and the wizard
        # would walk the user straight on to indexing.
        if 'exc' not in box and 'out' not in box:
            box['exc'] = RuntimeError('analysis worker exited without a result')

        if 'exc' in box:
            doc.status = Document.FAILED
            doc.status_detail = str(box['exc'])[:500]
            doc.save(update_fields=['status', 'status_detail'])
            yield json.dumps({'type': 'error',
                              'error': f'Analysis failed: {box["exc"]}'}) + '\n'
            return

        meta, tree_html = box['out']
        yield json.dumps({
            'type': 'result',
            'pk': doc.pk, 'language': lang,
            # Route to the review step whenever the LLM produced anything.
            'structured': bool(tree_html or meta),
            'suggested_meta': meta,
            'suggested_type': (meta.get('doc_type') or 'regulation').capitalize(),
            'tree_html': tree_html,
            'ai_suggested': True,
        }) + '\n'

    resp = StreamingHttpResponse(stream(), content_type='application/x-ndjson')
    # Without this a reverse proxy may buffer the whole body and deliver it in
    # one piece at the end, which is exactly the behaviour being fixed.
    resp['X-Accel-Buffering'] = 'no'
    resp['Cache-Control'] = 'no-cache'
    return resp


class AnalyzeView(View):
    """POST /library/analyze/ — Phase 1 of the guided upload: create the doc,
    extract/OCR + chunk it (NO embedding yet), cache the chunks, and return the
    detected structure so the user can confirm before it's indexed."""

    def post(self, request):
        from django.http import JsonResponse
        file = request.FILES.get('file')
        if not file:
            return HttpResponseBadRequest('No file provided.')
        # Format guard — the pipeline (PyMuPDF + docling) handles PDF / DOCX / TXT.
        # A legacy binary .doc can't be parsed by either, so reject it up front with
        # a clear fix rather than letting the ingestion job fail deep in the parser.
        _name = (file.name or '').lower()
        if not _name.endswith(('.pdf', '.docx', '.txt')):
            _kind = 'Legacy .doc files' if _name.endswith('.doc') else 'This file type'
            return JsonResponse(
                {'error': f'{_kind} aren’t supported. Please save the document as '
                          f'PDF or .docx and upload it again.'}, status=400)
        # Language + jurisdiction are DETECTED, not asked upfront. The user only
        # supplies the file; we detect the language here and the LLM proposes the
        # jurisdiction, both surfaced in the review step to confirm.
        forced_lang = (request.POST.get('language') or '').strip().lower()
        doc = Document.objects.create(
            name=(request.POST.get('name') or file.name).strip(),
            full_name=(request.POST.get('full_name') or '').strip(),
            doc_type=(request.POST.get('doc_type') or Document.REGULATION),
            jurisdiction=(request.POST.get('jurisdiction') or Document.OTHER),
            language=(forced_lang or 'en'),
            issuing_authority=(request.POST.get('issuing_authority') or '').strip(),
            version=(request.POST.get('version') or '').strip(),
            notes=(request.POST.get('notes') or '').strip(),
            status='review',
            file=file,
        )
        # Auto-detect the language from the file (Arabic-char ratio over the text
        # layer) unless the user explicitly forced one.
        if forced_lang in ('', 'auto'):
            try:
                from arabic.detect import detect_language
                doc.language = detect_language(doc.file.path)
                doc.save(update_fields=['language'])
            except Exception:
                logger.exception('language auto-detect failed for %s', doc.pk)
        lang = doc.language
        # English: no regex structure engine, but the local LLM can read the
        # first pages to (a) suggest metadata for the user to confirm and
        # (b) infer the document's own hierarchy. Both are suggestions — the
        # user reviews them in step 3 before anything is indexed.
        if lang != Document.ARABIC:
            return _streaming_analysis(doc, lang)

        try:
            from arabic.analyze import analyze
            result = analyze(doc.file.path, declared_language=Document.ARABIC)
        except Exception as exc:
            doc.status = Document.FAILED
            doc.status_detail = str(exc)[:500]
            doc.save(update_fields=['status', 'status_detail'])
            return JsonResponse({'pk': doc.pk, 'error': f'Analysis failed: {exc}'}, status=500)

        summary = result.get('structure')
        from django.core.cache import cache
        cache.set(f'analyze_{doc.pk}', result.get('chunks', []), 3600)
        from django.template.loader import render_to_string
        tree_html = render_to_string('partials/_structure_tree.html', {'summary': summary})
        counts = {k: summary[k] for k in
                  ('parts', 'sections', 'articles', 'definitions', 'total_nodes')} if summary else {}
        # Also offer LLM-suggested metadata on the Arabic text (title/authority/
        # number live up front) for the same confirm-before-index flow.
        ar_meta = _run_doc_intel(doc.file.path, metadata_only=True)[0]
        return JsonResponse({
            'pk': doc.pk, 'language': 'ar', 'structured': True,
            'used_ocr': result.get('used_ocr', False),
            'suggested_type': result.get('suggested_type', ''),
            'suggested_meta': ar_meta,
            'ai_suggested': bool(ar_meta),
            'counts': counts, 'tree_html': tree_html,
        })


class FinalizeView(View):
    """POST /library/finalize/<pk>/ — Phase 2: apply the user's confirmed
    metadata and index. Arabic docs embed the chunks cached during analysis;
    everything else runs the normal ingestion pipeline."""

    def post(self, request, pk):
        from django.http import JsonResponse
        from django.core.cache import cache
        doc = get_object_or_404(Document, pk=pk)

        fields = []
        for f in ('name', 'full_name', 'language', 'doc_type', 'jurisdiction',
                  'chunk_strategy', 'citation_format', 'citation_template',
                  'citation_abbr', 'doc_year', 'department', 'confidentiality',
                  'document_id', 'issuing_authority', 'regulation_category',
                  'privacy_relevance', 'version', 'scope_summary'):
            v = request.POST.get(f)
            if v:
                setattr(doc, f, v.strip()); fields.append(f)
        # key_topics: LLM-extracted subject tags, sent comma-separated → stored as
        # a list on concept_tags_csv so they ride into chunk metadata for retrieval.
        kt = (request.POST.get('key_topics') or '').strip()
        if kt:
            doc.concept_tags_csv = [t.strip() for t in kt.split(',') if t.strip()]
            fields.append('concept_tags_csv')
        # Version lineage — the uploader linked this document as a newer version of
        # an existing regulation. Set the explicit family link, guarding against a
        # self-link or an obviously invalid target.
        vof = (request.POST.get('version_of') or '').strip()
        if vof.isdigit() and int(vof) != doc.pk:
            # Same kind of document only: a policy supersedes a policy, a
            # regulation a regulation. Anything else would build a nonsense family.
            parent = Document.objects.filter(
                pk=int(vof), doc_type=doc.doc_type).first()
            if parent and parent.family_root_id != doc.pk:   # no cycle
                # What happens to the version being replaced is the uploader's
                # choice in the wizard. Default keeps it: an audit trail usually
                # needs the text that was in force at the time.
                old_action = (request.POST.get('old_version_action') or 'supersede').strip().lower()
                if old_action == 'delete':
                    # No version_of link: the FK target is about to disappear, and
                    # saving a pointer to a deleted row would fail. Carry the
                    # identity across instead, then purge the old document exactly
                    # the way DocumentDeleteView does.
                    if parent.document_id and not doc.document_id:
                        doc.document_id = parent.document_id
                        fields.append('document_id')
                    doc.parent_regulation = parent.document_id or parent.chunk_doc_title or parent.name
                    fields.append('parent_regulation')
                    _purge_document(parent, actor=request.user,
                                    reason=f'replaced by new version "{doc.name}"')
                else:
                    doc.version_of = parent
                    fields.append('version_of')
                    if old_action != 'keep':
                        # supersede: flags the old version and any approved
                        # analyses that cited it for re-review.
                        try:
                            parent.supersede_with(doc, actor=request.user)
                        except Exception:
                            logger.exception('supersede_with failed for %s -> %s', parent.pk, doc.pk)

        # effective_date is a real date field — parse the ISO string the LLM/user
        # confirmed, ignore anything unparseable.
        eff = (request.POST.get('effective_date') or '').strip()
        if eff:
            from datetime import datetime
            try:
                doc.effective_date = datetime.strptime(eff[:10], '%Y-%m-%d').date()
                fields.append('effective_date')
            except ValueError:
                pass

        # Persist a newly-detected country / category the user confirmed as new,
        # so it becomes a known option in the Structure manager and future
        # uploads. Uses the admin taxonomy tree (TaxonomyNode) — a "collection"
        # of jurisdictions and categories the app learns over time.
        try:
            from apps.library.models import TaxonomyNode
            if request.POST.get('new_jurisdiction') == '1' and doc.jurisdiction:
                code = doc.jurisdiction.strip().lower()
                if not TaxonomyNode.objects.filter(node_type=TaxonomyNode.COUNTRY, code=code).exists():
                    TaxonomyNode.objects.create(
                        name=code.capitalize(), code=code,
                        node_type=TaxonomyNode.COUNTRY,
                        description='Added from document upload.')
            cat = (request.POST.get('regulation_category') or '').strip()
            if request.POST.get('new_category') == '1' and cat:
                if not TaxonomyNode.objects.filter(node_type=TaxonomyNode.TOPIC, name__iexact=cat).exists():
                    TaxonomyNode.objects.create(
                        name=cat, code=cat.lower().replace(' ', '_'),
                        node_type=TaxonomyNode.TOPIC,
                        description='Added from document upload.')
        except Exception:
            logger.exception('failed to persist new taxonomy node during finalize')

        # Opt-in classification: the uploader ticks "Classify topics now" in the
        # wizard. When set, we tag this doc's sections into the taxonomy right
        # after indexing so it's immediately usable in the coverage flow. When
        # unticked, the doc still indexes — classification just happens later
        # (on demand at first coverage run). Accept a few truthy spellings so
        # the checkbox posts cleanly.
        classify_now = (request.POST.get('classify') or '').strip().lower() in ('1', 'true', 'on', 'yes')

        # content_hash: cache-invalidation key for tags + mapping results.
        # The file is on disk by now, so hash it once at finalize.
        ch = doc.compute_content_hash()
        if ch:
            doc.content_hash = ch
            fields.append('content_hash')

        chunks = cache.get(f'analyze_{doc.pk}')
        if doc.language == Document.ARABIC and chunks:
            from arabic import store as ar_store
            from arabic.chunk import embed_text, restrategize
            from arabic.embed import embed_texts
            chunks = restrategize(chunks, doc.chunk_strategy)
            # arabic.analyze chunks under the placeholder source '_analyze_' —
            # it only receives a file path, so it can't know the title. Stamp the
            # real one before storing. Without this the chunks are invisible to
            # every source-filtered query (the doc reads as indexed but returns
            # nothing) AND survive delete_source(), which filters on the real
            # title — the ghost-chunk bug, on the Arabic side.
            for c in chunks:
                c['source'] = doc.chunk_doc_title
            vecs = embed_texts([embed_text(c) for c in chunks])
            ar_store.delete_source(doc.chunk_doc_title)
            ar_store.add([f'{doc.chunk_doc_title}::{i}' for i in range(len(chunks))],
                         vecs, [c['text'] for c in chunks], chunks)
            doc.status = Document.INDEXED
            doc.chunk_count = len(chunks)
            fields += ['status', 'chunk_count']
            doc.save(update_fields=list(dict.fromkeys(fields)))
            cache.delete(f'analyze_{doc.pk}')
            # Arabic chunks live in the Arabic store, not the bm25 side-table the
            # classifier reads; topic classification for Arabic is out of scope
            # for the opt-in path for now.
            return JsonResponse({'ok': True, 'chunks': len(chunks)})

        # English / cache miss → normal background pipeline
        doc.status = Document.PROCESSING
        fields.append('status')
        doc.save(update_fields=list(dict.fromkeys(fields)))
        from apps.ingestion.models import IngestionJob
        from apps.ingestion.pipeline import run_job
        job = IngestionJob.objects.create(
            document=doc, status=IngestionJob.QUEUED, current_stage=1,
            created_by=request.user if request.user.is_authenticated else None)
        run_job(job.id)
        # Kick off classification if opted in — the worker waits for indexing
        # to finish before tagging, so it's safe to launch now.
        if classify_now:
            try:
                from apps.library.classification import classify_document_async
                classify_document_async(doc.pk)
            except Exception:
                logger.exception('failed to launch classification for doc %s', doc.pk)
        return JsonResponse({'ok': True, 'processing': True, 'classifying': classify_now})


# ── Tag management ─────────────────────────────────────────────────────────────

PRESET_TAGS = [
    'High priority', 'Under review', 'Needs legal input',
    'Compliant', 'Action required', 'Archived',
]


def _normalise_tag_list(raw) -> list[dict]:
    """Accept either the legacy plain-string list or the new dict list.

    Old format:  ["High priority", "Under review"]
    New format:  [{"label": "High priority", "by": "sarah.jones",
                    "by_name": "Sarah Jones", "at": "2026-05-06T..."}, ...]

    Always returns the new format so callers don't have to branch. Tags
    saved before the author-tracking feature get an empty ``by`` so the
    UI can still display them.
    """
    out = []
    for entry in (raw or []):
        if isinstance(entry, dict):
            label = (entry.get('label') or '').strip()
            if not label:
                continue
            out.append({
                'label':   label,
                'by':      entry.get('by') or '',
                'by_name': entry.get('by_name') or '',
                'at':      entry.get('at') or '',
            })
        elif isinstance(entry, str):
            label = entry.strip()
            if label:
                out.append({'label': label, 'by': '', 'by_name': '', 'at': ''})
    return out


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class DocumentTagView(View):
    """POST /library/<pk>/tags/ — add or remove a tag from a document.

    Any authenticated user with a role can tag (analyst / reviewer / admin).
    Tags are stored on Document.tags as a list of dicts that record the
    author and timestamp, so the UI can show "added by X" tooltips. Tags
    are SHARED across users — every user sees every other user's tags on
    the same document.
    """

    def post(self, request, pk):
        from datetime import datetime, timezone
        doc = get_object_or_404(Document, pk=pk)
        try:
            body   = json.loads(request.body)
            action = body.get('action')           # 'add' | 'remove'
            tag    = (body.get('tag') or '').strip()
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'error': 'invalid JSON'}, status=400)

        if not tag:
            return JsonResponse({'error': 'tag required'}, status=400)

        tags = _normalise_tag_list(doc.tags)
        existing_labels = {t['label'].lower() for t in tags}

        if action == 'add':
            if tag.lower() not in existing_labels:
                tags.append({
                    'label':   tag,
                    'by':      request.user.username,
                    'by_name': request.user.get_full_name() or request.user.username,
                    'at':      datetime.now(timezone.utc).isoformat(timespec='seconds'),
                })
        elif action == 'remove':
            tags = [t for t in tags if t['label'].lower() != tag.lower()]
        else:
            return JsonResponse({'error': 'invalid action'}, status=400)

        doc.tags = tags
        doc.save(update_fields=['tags'])

        # audit so admins can trace who tagged what
        try:
            from apps.history.audit import log_event, Actions
            log_event(
                request.user,
                getattr(Actions, 'DOCUMENT_TAG', 'library.document_tag'),
                target_type='library.Document', target_id=doc.pk, request=request,
                description=f'{action} tag "{tag}" on {doc.name}',
                metadata={'action': action, 'tag': tag, 'doc_id': doc.pk},
            )
        except Exception:
            pass

        return JsonResponse({'tags': tags})


# ── Cross-Jurisdiction Term Dictionary ───────────────────────────────────────
# Backs /library/terms/. Data lives in reasoning/term_dictionary.py — that
# module is the single source of truth and is also imported by retrieval for
# query expansion, so the dictionary you see on this page literally matches
# the synonyms the retriever uses.

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class TermDictionaryView(TemplateView):
    """GET /library/terms/ — cross-jurisdiction term dictionary."""
    template_name = 'pages/terms.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # imported here (not at module scope) so a broken dictionary file
        # only affects this page, not the rest of the library app.
        from reasoning.term_dictionary import all_terms, CATEGORIES
        from django.utils.text import slugify

        search   = (self.request.GET.get('q') or '').strip().lower()
        category = (self.request.GET.get('cat') or '').strip()

        terms = all_terms()
        # pre-compute a stable slug per term — the template uses it as the
        # HTML id for json_script and as the alpine selection key.
        for t in terms:
            t['slug'] = slugify(t['canonical'])

        if category and category in CATEGORIES:
            terms = [t for t in terms if t.get('category') == category]

        if search:
            def _matches(t):
                # match against canonical, definition, synonyms, and every
                # jurisdiction-specific label so a user typing "data
                # principal" finds the controller entry.
                if search in t['canonical'].lower():
                    return True
                if search in (t.get('definition') or '').lower():
                    return True
                for s in t.get('synonyms', []) or []:
                    if search in s.lower():
                        return True
                for j in (t.get('jurisdictions') or {}).values():
                    if search in (j.get('term') or '').lower():
                        return True
                    if search in (j.get('citation') or '').lower():
                        return True
                return False
            terms = [t for t in terms if _matches(t)]

        # group by category for display, preserving the explicit ordering
        from collections import OrderedDict
        grouped = OrderedDict((c, []) for c in CATEGORIES)
        for t in terms:
            grouped.setdefault(t.get('category', 'Governance'), []).append(t)
        # drop empty categories so the UI doesn't render blank sections
        grouped = OrderedDict((c, items) for c, items in grouped.items() if items)

        # category counts (over the unfiltered set) — for the chip filter row
        unfiltered = all_terms()
        category_counts = {c: 0 for c in CATEGORIES}
        for t in unfiltered:
            cat = t.get('category', 'Governance')
            category_counts[cat] = category_counts.get(cat, 0) + 1

        ctx['grouped']         = grouped
        ctx['categories']      = list(CATEGORIES)
        ctx['category_counts'] = category_counts
        ctx['active_category'] = category
        ctx['active_search']   = self.request.GET.get('q') or ''
        ctx['total_count']     = len(unfiltered)
        ctx['filtered_count']  = sum(len(items) for items in grouped.values())
        ctx['jurisdictions']   = ['Bahrain', 'India', 'Kuwait']
        ctx['jur_labels']      = {
            'Bahrain': 'Bahrain', 'India': 'India', 'Kuwait': 'Kuwait',
        }
        return ctx


# ── Upload-metadata preview (autofill on upload) ─────────────────────────────
# Lightweight server-side guess of doc_type / jurisdiction / suggested name
# from the filename (and optionally the first page of content). The upload
# modal calls this on file-change to pre-fill the form so the user only has
# to confirm/correct the metadata rather than re-type it. Fast, no LLM call.

@method_decorator(role_required('admin'), name='dispatch')
class UploadMetadataPreviewView(View):
    """POST /library/upload/preview/ (multipart) — returns JSON with
    suggested doc_type, jurisdiction, name, full_name based on filename and
    (when present) the first ~5KB of file content."""

    _JUR_KEYWORDS = {
        'bahrain': ['bahrain', 'pdpl', 'cbb', 'pdpa'],
        'india':   ['india',   'dpdp',  'dpdpa', 'rbi', 'sebi'],
        'kuwait':  ['kuwait',  'dppr',  'citra', 'cbk', 'corf'],
        'bbk':     ['bbk',     'internal', 'policy_'],
    }
    _POLICY_KEYWORDS  = ['policy', 'sop', 'manual', 'procedure', 'guidelines',
                          'lgl-', 'ops-', 'sec-', 'hr-']
    _REGULATION_KEYWORDS = ['law', 'act', 'regulation', 'order', 'directive',
                             'circular', 'rule', 'framework', 'decision']

    def post(self, request):
        import re
        from pathlib import Path
        f = request.FILES.get('file')
        if not f:
            return JsonResponse({'error': 'No file uploaded'}, status=400)

        filename = f.name
        stem = Path(filename).stem
        # normalise for keyword matching: lowercase + replace separators with spaces
        norm = re.sub(r'[_\-\.]+', ' ', stem.lower())
        norm_squashed = norm.replace(' ', '')

        # 1) jurisdiction guess
        jur_guess = ''
        for code, keywords in self._JUR_KEYWORDS.items():
            if any(k in norm or k in norm_squashed for k in keywords):
                jur_guess = code
                break

        # 2) doc_type guess — BBK names usually = policy, otherwise look at keywords
        type_guess = Document.REGULATION
        if jur_guess == 'bbk' or any(k in norm for k in self._POLICY_KEYWORDS):
            type_guess = Document.POLICY
        elif any(k in norm for k in self._REGULATION_KEYWORDS):
            type_guess = Document.REGULATION

        # 3) name suggestion = stem with separators tidied
        name_guess = re.sub(r'[_\-]+', ' ', stem).strip()
        # collapse multi-space, title-case proper-noun-ish parts but keep
        # acronyms in caps. cheap heuristic.
        parts = []
        for p in re.split(r'\s+', name_guess):
            if p.isupper() or len(p) <= 4:
                parts.append(p)
            else:
                parts.append(p.capitalize())
        name_guess = ' '.join(parts)

        # 4) optional content peek for full_name. only PDFs/DOCX get this;
        # txt/md skip the import since content is the file itself.
        full_name_guess = ''
        try:
            f.seek(0)
            sample = f.read(5000)
            f.seek(0)
            # look for a likely title in the first 5KB. heuristic: a line
            # 20-120 chars long with mostly letters and few lowercase 'and's.
            try:
                text = sample.decode('utf-8', errors='ignore')
            except Exception:
                text = ''
            if text:
                for line in text.split('\n')[:30]:
                    line = line.strip()
                    if 20 <= len(line) <= 120 and sum(c.isalpha() or c.isspace() for c in line) > len(line) * 0.7:
                        full_name_guess = line
                        break
        except Exception:
            pass

        return JsonResponse({
            'doc_type':     type_guess,
            'jurisdiction': jur_guess,
            'name':         name_guess,
            'full_name':    full_name_guess,
            'filename':     filename,
            'size_bytes':   f.size,
        })


# ── Cross-reference search ───────────────────────────────────────────────────
# "Find every regulation that mentions concept X." Thin wrapper over
# hybrid_search that scans across all jurisdictions and groups hits by document
# so the analyst can see which laws speak to a topic at a glance. Uses the
# Term Dictionary's query expansion automatically (expand_synonyms=True), so
# searching "consent" still finds Bahrain chunks that say "permission".

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class CrossReferenceSearchView(TemplateView):
    """GET /library/search/ — concept search across all jurisdictions."""
    template_name = 'pages/cross_reference_search.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        query = (self.request.GET.get('q') or '').strip()
        jur   = self.request.GET.get('jur') or ''   # '' = all
        only_obligations = self.request.GET.get('only_obligations') == '1'

        groups = []
        total_hits = 0
        if query:
            from retrieval.retriever import hybrid_search
            from collections import OrderedDict
            try:
                kwargs_h = dict(query=query, top_k=15, rerank=True, expand_synonyms=True)
                if jur:
                    kwargs_h['jurisdiction'] = jur
                nodes = hybrid_search(**kwargs_h)

                # filter to obligation chunks if requested — re-detect on the
                # fly because BM25 metadata doesn't persist is_obligation.
                if only_obligations:
                    import re as _re
                    rx = _re.compile(
                        r'\b(?:shall|must|required to|mandatory|prohibited|may not|shall not|is required)\b',
                        _re.IGNORECASE,
                    )
                    nodes = [n for n in nodes if rx.search(n.node.get_content() or '')]

                # group by document title for the UI
                buckets = OrderedDict()
                for n in nodes:
                    m = n.node.metadata
                    title = m.get('doc_title') or m.get('regulation_name') or 'Unknown'
                    bucket = buckets.setdefault(title, {
                        'doc_title':       title,
                        'jurisdiction':    m.get('jurisdiction', ''),
                        'doc_id':          m.get('doc_id') or m.get('document_id'),
                        'hits':            [],
                    })
                    bucket['hits'].append({
                        'article_ref': m.get('article_ref', ''),
                        'snippet':     (n.node.get_content() or '').strip()[:380],
                        'score':       round(n.score, 3) if n.score is not None else None,
                        'node_id':     m.get('node_id') or n.node.node_id or '',
                    })
                    total_hits += 1
                groups = list(buckets.values())
            except Exception as e:
                ctx['error'] = f'Search failed: {e}'

        # also resolve doc_id → Document.pk for "View" links where possible
        if groups:
            titles = [g['doc_title'] for g in groups]
            doc_pk_by_title = dict(
                Document.objects.filter(name__in=titles).values_list('name', 'pk')
            )
            for g in groups:
                g['doc_pk'] = doc_pk_by_title.get(g['doc_title'])

        ctx['query']             = query
        ctx['jur']               = jur
        ctx['only_obligations']  = only_obligations
        ctx['groups']            = groups
        ctx['total_hits']        = total_hits
        ctx['jur_options']       = [('', 'All jurisdictions'),
                                     ('Bahrain', 'Bahrain'),
                                     ('India', 'India'),
                                     ('Kuwait', 'Kuwait'),
                                     ('BBK', 'BBK policies')]
        return ctx


# ── Obligation register ──────────────────────────────────────────────────────
# Lists every chunk that contains binding-rule language ("shall", "must", etc.)
# so an analyst can scan obligations document-by-document. Reads directly from
# the BM25 store (search_bm25) rather than going through hybrid retrieval since
# the user wants ALL obligations, not the top-k most relevant.

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class ObligationRegisterView(TemplateView):
    """GET /library/obligations/ — filtered list of obligation chunks."""
    template_name = 'pages/obligations.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        jur      = (self.request.GET.get('jur') or '').strip()
        doc_pk   = (self.request.GET.get('doc') or '').strip()
        keyword  = (self.request.GET.get('q')   or '').strip().lower()

        from retrieval.bm25_store import search_bm25
        # search BM25 with the strongest obligation keyword to seed the result
        # set, then post-filter. covers ~95% of real obligations.
        rows = search_bm25('shall must required prohibited', top_k=200,
                            jurisdiction=jur or None)
        import re as _re
        rx = _re.compile(
            r'\b(?:shall|must|required to|mandatory|prohibited|may not|shall not|is required)\b',
            _re.IGNORECASE,
        )

        selected_doc = None
        if doc_pk:
            try:
                selected_doc = Document.objects.get(pk=int(doc_pk))
            except (Document.DoesNotExist, ValueError):
                pass

        from collections import OrderedDict
        buckets = OrderedDict()
        for r in rows:
            text = (r.get('content') or '')
            if not rx.search(text):
                continue
            if keyword and keyword not in text.lower():
                continue
            m = r.get('metadata', {})
            title = m.get('doc_title') or m.get('regulation_name') or 'Unknown'
            if selected_doc and title != selected_doc.name:
                continue
            bucket = buckets.setdefault(title, {
                'doc_title':    title,
                'jurisdiction': m.get('jurisdiction', ''),
                'rows':         [],
            })
            # highlight which obligation verb fired so the analyst sees it fast
            match = rx.search(text)
            verb = match.group(0).lower() if match else ''
            bucket['rows'].append({
                'article_ref': m.get('article_ref', ''),
                'snippet':     text.strip()[:380],
                'verb':        verb,
                'node_id':     m.get('node_id', ''),
            })

        # sort docs by jurisdiction then title for predictable order
        groups = sorted(buckets.values(),
                        key=lambda g: (g['jurisdiction'], g['doc_title']))
        # cap rows per doc — full export is a separate concern
        for g in groups:
            g['hidden_count'] = max(0, len(g['rows']) - 12)
            g['rows'] = g['rows'][:12]

        # resolve titles → pk for "View" links
        if groups:
            titles = [g['doc_title'] for g in groups]
            doc_pk_by_title = dict(
                Document.objects.filter(name__in=titles).values_list('name', 'pk')
            )
            for g in groups:
                g['doc_pk'] = doc_pk_by_title.get(g['doc_title'])

        # for the doc filter dropdown
        all_docs = Document.objects.filter(
            status=Document.INDEXED
        ).order_by('jurisdiction', 'name').values('pk', 'name', 'jurisdiction')

        ctx['groups']          = groups
        ctx['total_obligations'] = sum(len(g['rows']) for g in groups)
        ctx['jur']             = jur
        ctx['doc_pk']          = doc_pk
        ctx['keyword']         = keyword
        ctx['selected_doc']    = selected_doc
        ctx['all_docs']        = list(all_docs)
        ctx['jur_options']     = [('', 'All jurisdictions'),
                                   ('Bahrain', 'Bahrain'),
                                   ('India', 'India'),
                                   ('Kuwait', 'Kuwait'),
                                   ('BBK', 'BBK policies')]
        return ctx

