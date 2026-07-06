import json
import re

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

_JUR_LABELS = {
    Document.BAHRAIN: 'Bahrain',
    Document.INDIA:   'India',
    Document.KUWAIT:  'Kuwait',
    Document.BBK:     'BBK',
    Document.OTHER:   'Other',
}


@method_decorator(role_required(*ALL_ROLES), name='dispatch')
@method_decorator(ensure_csrf_cookie, name='dispatch')
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

        docs_json = json.dumps([
            {
                'id':                d.pk,
                'name':              d.name,
                'type_label':        _type_label(d.name),
                'full_name':         d.full_name or '',
                'jurisdiction':      d.jurisdiction,
                'jurisdiction_display': d.get_jurisdiction_display(),
                'status':            d.status,
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
                'superseded_by':       d.superseded_by or '',
                'parent_regulation':   d.parent_regulation or '',
                'cross_references':    d.cross_references or '',
                'concept_tags_csv':    d.concept_tags_csv or [],
            }
            for d in regs_list
        ])

        ctx.update({
            'regulations': regs_list,
            'docs_json':   docs_json,
            'preset_tags': PRESET_TAGS,
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
                'superseded_by':       d.superseded_by or '',
                'parent_regulation':   d.parent_regulation or '',
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
class DocumentDeleteView(View):
    """GET/POST /library/delete/<pk>/ — confirm + delete a document."""

    def get(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        chunk_count = getattr(doc, 'chunk_count', None) or 0
        return render(request, 'pages/document_delete_confirm.html', {
            'doc': doc,
            'chunk_count': chunk_count,
        })

    def post(self, request, pk):
        try:
            doc = Document.objects.get(pk=pk)
            doc_name = doc.name
            doc_type = doc.doc_type
            doc.delete()
            from apps.history.audit import log_event, Actions
            log_event(
                request.user, Actions.DOCUMENT_DELETE,
                request=request,
                target_type='library.Document', target_id=pk,
                description=f'{request.user.username} deleted document "{doc_name}"',
                metadata={'doc_name': doc_name, 'doc_type': doc_type},
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
        # Pull chunks WITH their node_ids so we can highlight by chunk_id
        # (rock-solid) when the caller provides one, with the existing
        # substring-match path as a fallback for legacy callers.
        from apps.comparison.concepts import get_doc_chunks_with_ids
        chunks_with_ids = get_doc_chunks_with_ids(doc, limit=200)
        chunks = [c for _, c in chunks_with_ids]
        node_ids = [nid for nid, _ in chunks_with_ids]

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

        # Extract section headings for the navigation sidebar.
        sections = []
        for i, chunk in enumerate(chunks):
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

        return render(request, 'partials/_doc_viewer_body.html', {
            'doc':           doc,
            'chunks':        chunks,
            'sections':      sections,
            'highlight_ref': highlight_ref,
            'highlight_idx': highlight_idx,
        })


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
