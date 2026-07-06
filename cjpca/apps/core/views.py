import json
import re

import requests as http_client

# Word-boundary regex used by the Copilot's chunk-relevance scorer: matches
# alphanumeric runs of 4+ characters, so trailing punctuation never sneaks
# into the keyword list (the previous `query.split()` approach treated
# "consent;" as a distinct token from "consent").
_COPILOT_WORD_RE = re.compile(r"\b\w{4,}\b", re.UNICODE)

from django.views import View
from django.views.generic.edit import CreateView
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django import forms as django_forms
from django.utils.decorators import method_decorator

from apps.accounts.decorators import role_required

ALL_ROLES     = ('analyst', 'reviewer', 'admin')
COPILOT_ROLES = ('analyst', 'reviewer')


# ── Registration ─────────────────────────────────────────────────────────────

class RegistrationForm(UserCreationForm):
    email = django_forms.EmailField(required=False)

    class Meta(UserCreationForm.Meta):
        fields = ('username', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email', '')
        if commit:
            user.save()
        return user


class RegisterView(CreateView):
    """GET/POST /register/ — user registration."""
    form_class = RegistrationForm
    template_name = 'registration/signup.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response

    def get_success_url(self):
        return '/'


# ── Copilot ──────────────────────────────────────────────────────────────────

_COPILOT_PROMPT = """\
You are a compliance analyst assistant for CJPCA, helping analyze cross-jurisdictional \
privacy regulations and BBK (Bank of Bahrain and Kuwait) internal policies.

DATA SOURCE: {data_source_label}
RETRIEVED CONTEXT:
{context}

CONVERSATION HISTORY:
{history}

USER QUESTION: {message}

INSTRUCTIONS:
- Answer based primarily on the retrieved context above.
- Be concise and practical (2-4 short paragraphs).
- When referencing a specific clause, cite it inline, e.g. (Bahrain PDPL, Art. 22).
- If the context does not contain enough to answer confidently, say so clearly.
- Do NOT fabricate regulatory requirements not present in the context.
- This is analytical assistance only — not legal advice.

ANSWER:"""

# ── Intent classification ──────────────────────────────────────────────────────

_COMPARISON_KW = {'compare', 'vs', 'versus', 'difference', 'differ', 'between',
                  'stricter', 'equivalent', 'both regulations', 'both laws'}
_POLICY_KW     = {'bbk', 'our policy', 'our policies', 'internal', 'cover', 'gap',
                  'sop', 'procedure', 'does our', 'do we', 'compliance with'}


def _classify_intent(message: str) -> str:
    msg = message.lower()
    if any(k in msg for k in _COMPARISON_KW):
        return 'comparison_analysis'
    if any(k in msg for k in _POLICY_KW):
        return 'policy_gap'
    return 'regulatory_lookup'


# ── Layer 1 — Regulatory text (indexed regulation chunks) ─────────────────────

def _retrieve_regulatory(message: str, doc_title: str = '') -> tuple[str, list[dict]]:
    """Retrieve relevant regulatory chunks for a copilot message.

    When ``doc_title`` is non-empty, retrieval is constrained to that one
    document (push-down filter at the BM25 + ChromaDB layer — the LLM
    physically cannot see anything else). Empty ``doc_title`` searches the
    whole indexed corpus.

    Fallback path: a generic "what is this document about" query returns no
    BM25/embedding hits because no chunk literally contains that phrase. When
    the user has a doc scope set, falling back to the first few chunks of
    the document gives the LLM the document's intro/definitions and lets it
    actually answer summary-style questions.
    """
    try:
        from retrieval.retriever import hybrid_search
        kwargs = dict(query=message, top_k=5, rerank=True)
        if doc_title:
            kwargs['doc_titles'] = [doc_title]
        nodes = hybrid_search(**kwargs)
    except Exception:
        return '(No relevant regulatory context found.)', []

    if not nodes and doc_title:
        # Generic-question fallback: pull the doc's opening chunks so the LLM
        # has the title, definitions, and first articles to summarise from.
        try:
            from retrieval.bm25_store import search_bm25
            rows = search_bm25('the', top_k=6, doc_title=doc_title)
            rows.sort(key=lambda c: int(c.get('metadata', {}).get('chunk_index') or 0))
            class _StubNode:
                def __init__(self, content, meta): self._c = content; self._m = meta
                @property
                def metadata(self): return self._m
                @property
                def node_id(self): return self._m.get('node_id', '')
                def get_content(self): return self._c
            class _StubScored:
                def __init__(self, node): self.node = node
            nodes = [_StubScored(_StubNode(r.get('content', ''), r.get('metadata', {}))) for r in rows[:5]]
        except Exception:
            nodes = []

    context_lines, citations, seen = [], [], set()
    for i, node in enumerate(nodes, 1):
        meta         = node.node.metadata
        reg_name     = meta.get('regulation_name', '')
        article_ref  = meta.get('article_ref', '')
        jurisdiction = meta.get('jurisdiction', '').lower()
        content      = node.node.get_content()[:400].strip()
        context_lines.append(f"[{i}] {reg_name}{f' ({article_ref})' if article_ref else ''}\n{content}")
        label = f"{reg_name}{f', {article_ref}' if article_ref else ''}"
        if reg_name and label not in seen:
            seen.add(label)
            citations.append({
                'reg_name': reg_name, 'article_ref': article_ref,
                'jurisdiction': jurisdiction, 'label': label,
                'excerpt': content[:150], 'is_draft': False,
            })
    return ('\n\n'.join(context_lines) or '(No relevant regulatory context found.)'), citations


# ── Layer 2 — Approved comparison results ─────────────────────────────────────

def _retrieve_approved_comparisons(message: str, include_drafts: bool = False
                                   ) -> tuple[str, list[dict], bool]:
    """Returns (context_str, citations, has_approved_data)."""
    from apps.comparison.models import ComparisonResult
    lifecycle_filter = ['approved']
    if include_drafts:
        lifecycle_filter.append('draft')

    qs = (ComparisonResult.objects
          .filter(lifecycle__in=lifecycle_filter)
          .select_related('run__reg_a', 'run__reg_b')[:80])

    msg_words = [w.lower() for w in _COPILOT_WORD_RE.findall(message)]
    scored = []
    for r in qs:
        text = ' '.join(filter(None, [r.preview_a, r.preview_b, r.rationale, r.key_difference]))
        score = sum(1 for w in msg_words if w in text.lower())
        if score > 0:
            scored.append((score, r.lifecycle == 'approved', r))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    top = [r for _, _, r in scored[:5]]

    if not top:
        return '', [], False

    has_approved = any(r.lifecycle == 'approved' for r in top)
    context_lines, citations = [], []
    for i, r in enumerate(top, 1):
        reg_a = r.run.reg_a.name if r.run else '—'
        reg_b = r.run.reg_b.name if r.run else '—'
        is_draft = r.lifecycle != 'approved'
        draft_tag = ' [DRAFT — unreviewed]' if is_draft else ''
        context_lines.append(
            f"[{i}] Comparison{draft_tag}: {r.citation_a} ↔ {r.citation_b}\n"
            f"Reg A ({reg_a}): {(r.preview_a or '—')[:200]}\n"
            f"Reg B ({reg_b}): {(r.preview_b or '—')[:200]}\n"
            f"{f'Rationale: {r.rationale}' if r.rationale else ''}"
        )
        citations.append({
            'reg_name': f"{reg_a} vs {reg_b}",
            'article_ref': f"{r.citation_a} ↔ {r.citation_b}",
            'jurisdiction': r.run.reg_a.jurisdiction if r.run else '',
            'label': f"{r.citation_a} ↔ {r.citation_b}",
            'excerpt': (r.preview_a or '')[:150],
            'is_draft': is_draft,
        })
    return '\n\n'.join(context_lines), citations, has_approved


# ── Layer 3 — Approved policy mappings ────────────────────────────────────────

def _retrieve_approved_mappings(message: str, include_drafts: bool = False
                                ) -> tuple[str, list[dict], bool]:
    """Returns (context_str, citations, has_approved_data)."""
    from apps.mapping.models import MappingAnalysis, ObligationMapping
    approved_analyses = MappingAnalysis.objects.filter(status=MappingAnalysis.APPROVED)
    if include_drafts:
        all_analyses = MappingAnalysis.objects.filter(
            status__in=[MappingAnalysis.APPROVED, MappingAnalysis.COMPLETE, MappingAnalysis.REVIEW]
        )
        qs = ObligationMapping.objects.filter(analysis__in=all_analyses).select_related(
            'analysis__policy_doc', 'regulation')[:80]
    else:
        qs = ObligationMapping.objects.filter(analysis__in=approved_analyses).select_related(
            'analysis__policy_doc', 'regulation')[:80]

    msg_words = [w.lower() for w in _COPILOT_WORD_RE.findall(message)]
    scored = []
    for m in qs:
        text = ' '.join(filter(None, [m.obligation_title, m.evidence_text]))
        score = sum(1 for w in msg_words if w in text.lower())
        if score > 0:
            is_approved = m.analysis.status == MappingAnalysis.APPROVED
            scored.append((score, is_approved, m))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    top = [m for _, _, m in scored[:5]]

    if not top:
        return '', [], False

    has_approved = any(m.analysis.status == MappingAnalysis.APPROVED for m in top)
    context_lines, citations = [], []
    for i, m in enumerate(top, 1):
        policy = m.analysis.policy_doc.name
        is_draft = m.analysis.status != MappingAnalysis.APPROVED
        draft_tag = ' [DRAFT — unreviewed]' if is_draft else ''
        context_lines.append(
            f"[{i}] Policy mapping{draft_tag}: {policy} — {m.article_ref}\n"
            f"Obligation: {m.obligation_title}\nCoverage: {m.coverage}\n"
            f"Evidence: {(m.evidence_text or '—')[:300]}"
        )
        citations.append({
            'reg_name': policy,
            'article_ref': m.article_ref,
            'jurisdiction': '',
            'label': f"{policy} § {m.article_ref}",
            'excerpt': (m.obligation_title or '')[:150],
            'is_draft': is_draft,
        })
    return '\n\n'.join(context_lines), citations, has_approved


# ── Top-level retrieval dispatcher ────────────────────────────────────────────

def _approved_retrieve(message: str, include_drafts: bool = False, doc_title: str = '') -> dict:
    """Run the right retrieval mix for a copilot message.

    ``doc_title`` (optional) constrains regulatory retrieval to that single
    document. The approved-comparisons / approved-mappings layers don't take
    a doc filter — those are already user-curated artifacts.
    """
    intent = _classify_intent(message)

    if intent == 'comparison_analysis':
        ctx, cits, has_approved = _retrieve_approved_comparisons(message, include_drafts)
        if ctx:
            quality = 'approved' if has_approved else 'draft_fallback'
            label = 'Approved comparison results' if has_approved else 'Draft comparisons (unreviewed)'
            return {'context': ctx, 'citations': cits, 'layer': intent,
                    'data_quality': quality, 'label': label, 'fallback_msg': None}
        # No comparison data — fall back to regulatory text
        reg_ctx, reg_cits = _retrieve_regulatory(message, doc_title=doc_title)
        return {
            'context': reg_ctx, 'citations': reg_cits, 'layer': intent,
            'data_quality': 'none',
            'label': f'Regulatory text — {doc_title}' if doc_title else 'Regulatory text (no approved comparisons yet)',
            'fallback_msg': (
                'No approved comparison results exist for this question yet. '
                'I\'m answering from the raw regulatory text instead. '
                'Once comparison pairs are reviewed and approved, '
                'my answers here will be based on verified analysis.'
            ),
        }

    if intent == 'policy_gap':
        ctx, cits, has_approved = _retrieve_approved_mappings(message, include_drafts)
        if ctx:
            quality = 'approved' if has_approved else 'draft_fallback'
            label = 'Approved policy mappings' if has_approved else 'Draft mappings (unreviewed)'
            return {'context': ctx, 'citations': cits, 'layer': intent,
                    'data_quality': quality, 'label': label, 'fallback_msg': None}
        return {
            'context': '(No approved policy mappings found.)', 'citations': [], 'layer': intent,
            'data_quality': 'none',
            'label': 'No approved mappings',
            'fallback_msg': (
                'No approved policy mappings cover this question. '
                'Run a policy mapping from the Policy Mapping page, '
                'then review and approve the results to make them available here.'
            ),
        }

    # regulatory_lookup or mixed
    reg_ctx, reg_cits = _retrieve_regulatory(message, doc_title=doc_title)
    if intent == 'regulatory_lookup':
        label = f'Active regulatory text — {doc_title}' if doc_title else 'Active regulatory text'
        return {'context': reg_ctx, 'citations': reg_cits, 'layer': intent,
                'data_quality': 'regulatory', 'label': label,
                'fallback_msg': None}

    # mixed — combine all three
    comp_ctx, comp_cits, comp_approved = _retrieve_approved_comparisons(message, include_drafts)
    map_ctx,  map_cits,  map_approved  = _retrieve_approved_mappings(message, include_drafts)
    all_ctx = '\n\n'.join(filter(None, [reg_ctx, comp_ctx, map_ctx]))
    all_cits = reg_cits + comp_cits + map_cits
    has_any_approved = comp_approved or map_approved
    quality = 'approved' if has_any_approved else 'regulatory'
    label = (f'Regulatory text ({doc_title}) + approved analysis' if doc_title
             else 'Regulatory text + approved analysis')
    return {'context': all_ctx or '(No context found.)', 'citations': all_cits,
            'layer': 'mixed', 'data_quality': quality,
            'label': label, 'fallback_msg': None}


@method_decorator(role_required(*COPILOT_ROLES), name='dispatch')
class CopilotMessageView(View):
    """POST /copilot/message/ — HTMX: send message, get AI response fragment.

    Wired through ``reasoning.orchestrator.reasoning_graph`` so the chat gets
    the same guard-rails as the structured workflows:

      route → draft → verify (citation grounding + NLI) → correct (max_retries) → finalize
                                                              ↓
                                                          fallback (safe canned)

    Retrieval still goes through the trust-tier dispatcher (``_approved_retrieve``)
    so the chat preferentially uses reviewed comparison/mapping artifacts when
    they exist. Those chunks are then handed to the orchestrator's verify node
    which checks citations against the chunks before shipping the answer.
    """

    def post(self, request):
        import asyncio
        from reasoning.orchestrator import reasoning_graph
        from reasoning.schemas      import SearchRequest

        message = request.POST.get('message', '').strip()
        if not message:
            return HttpResponse('')

        include_drafts: bool = request.session.get('copilot_include_drafts', False)
        history: list[dict]  = request.session.get('copilot_history', [])
        doc_title: str       = (request.POST.get('copilot_doc_select') or '').strip()
        # Mode toggle — 'approved' = only reviewed comparison + mapping rows;
        # 'document' = pure document Q&A against the picked doc_title's chunks.
        mode: str            = (request.POST.get('copilot_mode') or 'approved').strip()

        if mode == 'document':
            # Pure doc Q&A — needs a doc_title scope to make sense. Without it
            # there's nothing to ground answers in, so short-circuit to a
            # helpful nudge instead of letting retrieval return empty.
            if not doc_title:
                from django.template.loader import render_to_string
                history.append({'role': 'user',      'content': message})
                history.append({'role': 'assistant', 'content':
                    "Pick a document from the **Scope** chip above first — Document Q&A mode "
                    "answers strictly from one document's chunks, so I need to know which one."})
                request.session['copilot_history'] = history[-20:]
                return render(request, 'partials/_copilot_fragment.html', {
                    'user_message':    message,
                    'ai_response':     history[-1]['content'],
                    'confidence':      0.0,
                    'hallucination_risk': None,
                    'citations':       [],
                    'data_quality':    'guidance',
                    'data_label':      'Document Q&A — pick a doc',
                    'fallback_msg':    None,
                })
            reg_ctx, reg_cits = _retrieve_regulatory(message, doc_title=doc_title)
            retrieval = {
                'context': reg_ctx, 'citations': reg_cits, 'layer': 'document',
                'data_quality': 'regulatory',
                'label': f'Document — {doc_title}',
                'fallback_msg': None,
            }
        else:
            # Approved-analysis mode (default) — answers from reviewed
            # comparison + mapping results; falls back to raw regulatory text
            # when no approved artifacts cover the question.
            retrieval = _approved_retrieve(message, include_drafts=include_drafts,
                                            doc_title=doc_title)

        # convert retrieved chunks (already dicts from _retrieve_*) to the
        # shape orchestrator.verify_node expects: node_id + content + jurisdiction.
        # _approved_retrieve returns 'context' (formatted string) and 'citations'
        # (list of dicts) — citations don't have content. We have to re-fetch
        # the underlying chunks for the orchestrator's verify step.
        from retrieval.retriever import hybrid_search
        try:
            kwargs_h = dict(query=message, top_k=5, rerank=True)
            if doc_title:
                kwargs_h['doc_titles'] = [doc_title]
            nodes = hybrid_search(**kwargs_h)
        except Exception:
            nodes = []
        chunks = []
        for n in nodes:
            m = n.node.metadata
            chunks.append({
                'node_id':         m.get('node_id') or n.node.node_id or '',
                'content':         n.node.get_content(),
                'jurisdiction':    m.get('jurisdiction', ''),
                'regulation_name': m.get('regulation_name', ''),
                'article_ref':     m.get('article_ref', ''),
            })
        # Same generic-question fallback as _retrieve_regulatory: if the user
        # has a doc scope set but retrieval found nothing, pull the doc's
        # opening chunks so the orchestrator has substrate for summary-style
        # questions like "what is this document about?".
        if not chunks and doc_title:
            try:
                from retrieval.bm25_store import search_bm25
                rows = search_bm25('the', top_k=6, doc_title=doc_title)
                rows.sort(key=lambda c: int(c.get('metadata', {}).get('chunk_index') or 0))
                for r in rows[:5]:
                    m = r.get('metadata', {})
                    chunks.append({
                        'node_id':         m.get('node_id', ''),
                        'content':         r.get('content', ''),
                        'jurisdiction':    m.get('jurisdiction', ''),
                        'regulation_name': m.get('regulation_name', ''),
                        'article_ref':     m.get('article_ref', ''),
                    })
            except Exception:
                pass

        # short-circuit to a friendly canned reply on no retrieval
        if not chunks:
            ai_response = (
                "I can't find anything relevant in the indexed documents for that. "
                "Try rephrasing, picking a different document scope, or running "
                "a comparison/mapping first so I have analysis to draw from."
            )
            confidence = 0.3
            hall_risk  = None
            citations  = retrieval.get('citations') or []
        else:
            req = SearchRequest(query=message)
            state = {'request': req, 'retrieved_chunks': chunks,
                     'reasoning_trace': [], 'retries': 0}
            # Unique thread_id per message — the orchestrator is wired with a
            # MemorySaver checkpointer, and reusing the same thread_id makes it
            # merge with cached state instead of running fresh retrieval. That
            # caused every follow-up question to mirror the first answer even
            # after the user changed the scope chip. uuid4 forces a fresh run.
            import uuid
            cfg = {'configurable': {'thread_id': f'copilot-{request.user.pk}-{uuid.uuid4().hex}'}}

            try:
                # orchestrator is async; wrap the same way reasoning.workflows
                # does — modern asyncio probe so we don't hit the get_event_loop
                # deprecation on Python 3.14+, and a worker thread when we're
                # already inside a running loop (nested asyncio.run would raise).
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    # No loop running — the normal sync-view case.
                    result = asyncio.run(reasoning_graph.ainvoke(state, config=cfg))
                else:
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as exe:
                        result = exe.submit(
                            asyncio.run,
                            reasoning_graph.ainvoke(state, config=cfg),
                        ).result()

                answer = result['final_output']
                ai_response = answer.summary
                confidence  = answer.confidence
                hall_risk   = result.get('hallucination_risk')

                # map ReasonedAnswer.citations → fragment's citation chips.
                citations = []
                for c in (answer.citations or []):
                    citations.append({
                        'reg_name':     c.regulation_name,
                        'article_ref':  c.article_ref or '',
                        'jurisdiction': c.jurisdiction,
                        'label':        f'{c.regulation_name}{f", {c.article_ref}" if c.article_ref else ""}',
                        'excerpt':      (c.exact_quote or '')[:150],
                        'is_draft':     False,
                    })
                if not citations and confidence > 0.3:
                    citations = retrieval.get('citations') or []

                # Orchestrator gave up (safe_fallback returns conf == 0.3 with
                # no citations) — but retrieval succeeded. Replace the canned
                # "I cannot provide" body with a previews-based summary so the
                # user still gets something useful from the chunks we found.
                _hit_fallback = (
                    confidence <= 0.31
                    and not answer.citations
                    and chunks
                    and 'cannot provide a fully grounded answer' in (ai_response or '')
                )
                if _hit_fallback:
                    bullets = []
                    for ch in chunks[:5]:
                        body = (ch.get('content') or '').strip().replace('\n', ' ')
                        if len(body) > 220:
                            body = body[:220].rsplit(' ', 1)[0] + '…'
                        label = ch.get('article_ref') or ch.get('regulation_name') or 'Chunk'
                        if body:
                            bullets.append(f'• **{label}** — {body}')
                    if bullets:
                        ai_response = (
                            "I couldn't synthesise a fully-verified answer, but here is "
                            "what the retrieved passages say about your question. Treat as "
                            "a starting point — verify against the source documents.\n\n"
                            + '\n\n'.join(bullets)
                        )
                        confidence = 0.45
                        citations  = retrieval.get('citations') or citations

            except Exception as exc:
                # network / parser / auth failure — degrade gracefully
                ai_response = ("I can't reach the AI engine right now. "
                                "Check OPENROUTER_API_KEY and try again.")
                confidence = 0.0
                hall_risk  = None
                citations  = []

        history.append({'role': 'user',      'content': message})
        history.append({'role': 'assistant', 'content': ai_response})
        request.session['copilot_history'] = history[-20:]

        return render(request, 'partials/_copilot_fragment.html', {
            'user_message':       message,
            'ai_response':        ai_response,
            'confidence':         confidence,
            'hallucination_risk': hall_risk,
            'citations':     retrieval['citations'],
            'data_quality':  retrieval['data_quality'],
            'fallback_msg':  retrieval['fallback_msg'],
        })


@method_decorator(role_required(*COPILOT_ROLES), name='dispatch')
class CopilotToggleDraftsView(View):
    """POST /copilot/toggle-drafts/ — flip the include-drafts session flag (legacy)."""

    def post(self, request):
        current = request.session.get('copilot_include_drafts', False)
        request.session['copilot_include_drafts'] = not current
        return HttpResponse(status=204)


# ── Scope API ─────────────────────────────────────────────────────────────────

@method_decorator(role_required(*COPILOT_ROLES), name='dispatch')
class ScopeStateView(View):
    """GET /copilot/scope/ — return current scope state as JSON."""

    def get(self, request):
        from .scope import compute_scope_state
        include_drafts = request.session.get('copilot_include_drafts', False)
        state = compute_scope_state(include_drafts=include_drafts)
        return JsonResponse(state)


@method_decorator(role_required(*COPILOT_ROLES), name='dispatch')
class ScopePreferencesView(View):
    """PATCH /copilot/scope/preferences/ — update include_drafts session flag."""

    def patch(self, request):
        try:
            body = json.loads(request.body)
            include_drafts = bool(body.get('include_drafts', False))
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        request.session['copilot_include_drafts'] = include_drafts
        return JsonResponse({'include_drafts': include_drafts})


@method_decorator(role_required(*COPILOT_ROLES), name='dispatch')
class CopilotClearView(View):
    """POST /copilot/clear/ — clear conversation history from session."""

    def post(self, request):
        request.session['copilot_history'] = []
        # Return the empty state placeholder so HTMX can replace #cp-messages content
        return HttpResponse(
            '<p class="text-xs text-gray-400 text-center">'
            'Ask me anything about the regulations or your policy mappings.'
            '</p>'
        )


# ── Doc Viewer ────────────────────────────────────────────────────────────────

@method_decorator(role_required(*ALL_ROLES), name='dispatch')
class DocViewerView(View):
    """GET /viewer/<doc_id>/<article_id>/ — HTMX: doc viewer content fragment."""

    def get(self, request, doc_id, article_id):
        import sqlite3

        sections = []
        try:
            from config import CHROMA_DIR
            bm25_path = CHROMA_DIR / 'bm25.db'
            if bm25_path.exists():
                conn = sqlite3.connect(str(bm25_path))
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute(
                        "SELECT node_id, article_ref, content "
                        "FROM bm25_index WHERE jurisdiction = ? ORDER BY node_id",
                        [doc_id],
                    ).fetchall()
                    grouped: dict = {}
                    for row in rows:
                        ref = row['article_ref'] or ''
                        if ref not in grouped:
                            grouped[ref] = {'article_ref': ref, 'parts': []}
                        grouped[ref]['parts'].append(row['content'])
                    sections = list(grouped.values())
                finally:
                    conn.close()
        except Exception:
            pass

        target = article_id if article_id != 'all' else ''
        return render(request, 'partials/_doc_viewer_content.html', {
            'sections': sections,
            'article_id': target,
        })
