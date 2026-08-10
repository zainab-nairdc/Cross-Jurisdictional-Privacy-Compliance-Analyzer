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


def _ollama_reachable() -> bool:
    """Quick health probe of the local Ollama server (the PoC's primary LLM).

    Lets the Copilot return a precise 'start Ollama' message instantly instead
    of running the whole orchestrator only to fail on a connection error the
    catch-all used to mislabel as an OpenRouter/API-key problem. Cheap: a couple
    of ms when Ollama is up, ~2s worst case when it's down."""
    import urllib.request
    try:
        from config import OLLAMA_URL
        base = OLLAMA_URL
    except Exception:
        base = 'http://localhost:11434'
    try:
        urllib.request.urlopen(f'{base}/api/tags', timeout=2)
        return True
    except Exception:
        return False


# ── Layer 1 — Regulatory text (indexed regulation chunks) ─────────────────────

def _retrieve_regulatory(message: str, doc_title: str = '', jurisdiction: str = '') -> tuple[str, list[dict]]:
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
        elif jurisdiction:
            # Country scope: one or more jurisdictions (comma-joined) as a single
            # source. The retriever normalises the codes (bahrain -> Bahrain).
            js = [j.strip() for j in jurisdiction.split(',') if j.strip()]
            if len(js) == 1:
                kwargs['jurisdiction'] = js[0]
            elif js:
                kwargs['jurisdictions'] = js
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

    # Map chunk doc_title → Document pk so a citation click can open the viewer.
    from apps.library.models import Document as _Doc
    _title_to_pk = {d.chunk_doc_title: d.pk for d in _Doc.objects.only('id', 'file')}

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
            doc_title = meta.get('doc_title', '')
            citations.append({
                'reg_name': reg_name, 'article_ref': article_ref,
                'jurisdiction': jurisdiction, 'label': label,
                'excerpt': content[:150], 'is_draft': False,
                # carry the source doc + chunk so a click can open the viewer,
                # scroll to the cited paragraph and highlight it.
                'doc_title': doc_title,
                'doc_pk': _title_to_pk.get(doc_title, ''),
                'node_id': node.node.node_id,
                'quote': content[:220],
            })
    return ('\n\n'.join(context_lines) or '(No relevant regulatory context found.)'), citations


# ── Layer 2 — Approved comparison results ─────────────────────────────────────

def _retrieve_approved_comparisons(message: str, include_drafts: bool = False
                                   ) -> tuple[str, list[dict], bool, list[dict]]:
    """Returns (context_str, citations, has_approved_data, chunks).

    ``chunks`` are orchestrator-ready dicts (node_id + content + metadata) built
    from the approved comparison rows themselves, so the LLM answers FROM the
    reviewed analysis — not from freshly re-fetched raw regulation text. Without
    this the "Approved data" badge was misleading: the citations came from the
    approved rows but the answer was synthesised from unrelated regulatory chunks.
    """
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
        return '', [], False, []

    has_approved = any(r.lifecycle == 'approved' for r in top)
    context_lines, citations, chunks = [], [], []
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
        # Ground the LLM on the reviewed verdict itself. The relationship label
        # (Equivalent / Stricter in A / Conflicting …) is the finding — include
        # it verbatim so the answer reflects the approved analysis.
        chunks.append({
            'node_id': r.chunk_id_a or f'approved-comparison-{r.id}',
            'content': (
                f"Approved comparison{draft_tag}: {reg_a} vs {reg_b}.\n"
                f"Topic / citation: {r.citation_a} vs {r.citation_b}.\n"
                f"Relationship (reviewed finding): {r.rel_label}.\n"
                f"{reg_a}: {(r.preview_a or '').strip()}\n"
                f"{reg_b}: {(r.preview_b or '').strip()}\n"
                f"{('Key difference: ' + r.key_difference) if r.key_difference else ''}\n"
                f"{('Rationale: ' + r.rationale) if r.rationale else ''}"
            ).strip(),
            'jurisdiction': r.run.reg_a.jurisdiction if r.run else '',
            'regulation_name': f"{reg_a} vs {reg_b}",
            'article_ref': f"{r.citation_a} / {r.citation_b}",
        })
    return '\n\n'.join(context_lines), citations, has_approved, chunks


# ── Layer 3 — Approved policy mappings ────────────────────────────────────────

def _retrieve_approved_mappings(message: str, include_drafts: bool = False
                                ) -> tuple[str, list[dict], bool, list[dict]]:
    """Returns (context_str, citations, has_approved_data, chunks).

    ``chunks`` are orchestrator-ready dicts built from the approved policy-mapping
    rows, so a "do our policies cover X?" answer is grounded in the reviewed
    coverage verdict (covered / partial / none) rather than raw regulation text
    that never mentions BBK's policies at all.
    """
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
        return '', [], False, []

    has_approved = any(m.analysis.status == MappingAnalysis.APPROVED for m in top)
    context_lines, citations, chunks = [], [], []
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
        # The coverage status IS the finding — feed it to the LLM verbatim so it
        # can't contradict the reviewed verdict (e.g. answering "not covered"
        # when the approved mapping says "covered").
        chunks.append({
            'node_id': f'approved-mapping-{m.id}',
            'content': (
                f"Approved policy mapping{draft_tag} for {policy}.\n"
                f"Regulatory obligation: {m.obligation_title} ({m.article_ref}).\n"
                f"Coverage status (reviewed verdict): {m.coverage}.\n"
                f"Evidence from policy: {(m.evidence_text or '').strip()}"
            ).strip(),
            'jurisdiction': '',
            'regulation_name': policy,
            'article_ref': m.article_ref,
        })
    return '\n\n'.join(context_lines), citations, has_approved, chunks


# ── Top-level retrieval dispatcher ────────────────────────────────────────────

def _approved_retrieve(message: str, include_drafts: bool = False, doc_title: str = '') -> dict:
    """Run the right retrieval mix for a copilot message.

    ``doc_title`` (optional) constrains regulatory retrieval to that single
    document. The approved-comparisons / approved-mappings layers don't take
    a doc filter — those are already user-curated artifacts.
    """
    intent = _classify_intent(message)

    if intent == 'comparison_analysis':
        ctx, cits, has_approved, chunks = _retrieve_approved_comparisons(message, include_drafts)
        if ctx:
            quality = 'approved' if has_approved else 'draft_fallback'
            label = 'Approved comparison results' if has_approved else 'Draft comparisons (unreviewed)'
            return {'context': ctx, 'citations': cits, 'layer': intent,
                    'data_quality': quality, 'label': label, 'fallback_msg': None,
                    'chunks': chunks}
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
        ctx, cits, has_approved, chunks = _retrieve_approved_mappings(message, include_drafts)
        if ctx:
            quality = 'approved' if has_approved else 'draft_fallback'
            label = 'Approved policy mappings' if has_approved else 'Draft mappings (unreviewed)'
            return {'context': ctx, 'citations': cits, 'layer': intent,
                    'data_quality': quality, 'label': label, 'fallback_msg': None,
                    'chunks': chunks}
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
    comp_ctx, comp_cits, comp_approved, comp_chunks = _retrieve_approved_comparisons(message, include_drafts)
    map_ctx,  map_cits,  map_approved,  map_chunks  = _retrieve_approved_mappings(message, include_drafts)
    all_ctx = '\n\n'.join(filter(None, [reg_ctx, comp_ctx, map_ctx]))
    all_cits = reg_cits + comp_cits + map_cits
    has_any_approved = comp_approved or map_approved
    quality = 'approved' if has_any_approved else 'regulatory'
    label = (f'Regulatory text ({doc_title}) + approved analysis' if doc_title
             else 'Regulatory text + approved analysis')
    return {'context': all_ctx or '(No context found.)', 'citations': all_cits,
            'layer': 'mixed', 'data_quality': quality,
            'label': label, 'fallback_msg': None,
            'chunks': comp_chunks + map_chunks}


_COPILOT_CAPABILITIES = (
    "I'm the compliance copilot for this workspace. I answer **only** from your "
    "indexed regulations and internal policies, and I cite the exact articles I "
    "use — I don't guess or answer from general knowledge.\n\n"
    "Here's how I can help:\n\n"
    "- **Ask about one document** — pick it from the **Scope** chip, then ask e.g. "
    "*\"What does this say about data retention?\"* or *\"Summarise the breach-notification rules.\"*\n"
    "- **Ask across a country** — toggle a jurisdiction in **Sources** to search all "
    "its regulations at once.\n"
    "- **Use reviewed analysis** — in **Approved** mode I draw on the comparison and "
    "mapping results your team has validated.\n"
    "- **Trace everything** — each answer links back to the source article so you can verify it.\n\n"
    "Pick a document or country scope above, then ask your question."
)

_GREETINGS = {"hi", "hello", "hey", "yo", "hiya", "heya", "sup", "hii", "helloo",
              "good morning", "good afternoon", "good evening", "thanks", "thank you"}

_META_TRIGGERS = (
    "what can you do", "what can you help", "what do you do", "how can you help",
    "how do you help", "who are you", "what are you", "how do you work",
    "what sort of thing", "what kind of thing", "what can this do", "help me do",
    "things you can do", "what you can do", "what can you help me", "what else can you",
    "capabilit", "how to use you", "how do i use you",
)

_CORPUS_TRIGGERS = (
    "what document", "which document", "what sources", "what laws", "what regulation",
    "list document", "documents exist", "documents are", "documents do you",
    "what files", "what do you have", "what's in this source", "what is in this source",
    "what docs", "which laws", "what's indexed",
)


def _meta_reply(message: str):
    """Direct answer for greetings + capability/meta questions so they never get
    forced through the compliance RAG (which returns 'Insufficient information to
    determine compliance'). Returns a string, or None if not a meta question."""
    raw = message.strip().lower()
    bare = raw.strip("!?.,; ")
    if bare in _GREETINGS:
        return "Hi! " + _COPILOT_CAPABILITIES
    # normalise txt-speak ("what can u do" -> "what can you do")
    m = " " + re.sub(r"[^a-z0-9 ]", " ", raw) + " "
    m = re.sub(r"\bu\b", "you", m)
    m = re.sub(r"\bur\b", "your", m)
    m = re.sub(r"\s+", " ", m)
    if any(t in m for t in _META_TRIGGERS):
        return _COPILOT_CAPABILITIES
    return None


def _corpus_reply(message: str, doc_title: str = "", jurisdiction: str = ""):
    """Answer 'what documents / laws exist?' by listing the actual indexed corpus,
    respecting the current scope. Returns a markdown string, or None."""
    m = " " + re.sub(r"[^a-z0-9 ]", " ", message.lower()) + " "
    if not any(t in m for t in _CORPUS_TRIGGERS):
        return None
    from apps.library.models import Document
    qs = Document.objects.filter(status=Document.INDEXED)
    if jurisdiction:
        codes = [c.strip().lower() for c in jurisdiction.split(",") if c.strip()]
        qs = qs.filter(jurisdiction__in=codes)
    regs = list(qs.filter(doc_type=Document.REGULATION).order_by("jurisdiction", "name"))
    pols = list(qs.filter(doc_type=Document.POLICY).order_by("name"))
    if not regs and not pols:
        return ("There are no indexed documents in the current scope yet. Upload "
                "documents from the **Regulations** or **Internal Policies** pages first.")
    lines = [f"Here are the **{len(regs) + len(pols)} documents** currently indexed"
             + (f" for {jurisdiction.title()}" if jurisdiction else "") + ":\n"]
    if regs:
        lines.append(f"**Regulations ({len(regs)})**")
        for d in regs[:40]:
            jur = d.get_jurisdiction_display() or ""
            lines.append(f"- {d.name}" + (f" · {jur}" if jur else ""))
        if len(regs) > 40:
            lines.append(f"- …and {len(regs) - 40} more")
    if pols:
        lines.append(f"\n**Internal policies ({len(pols)})**")
        for d in pols[:40]:
            lines.append(f"- {d.name}")
    lines.append("\nPick one from the **Scope** chip to ask about it specifically.")
    return "\n".join(lines)


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
        # Country scope — all documents of a jurisdiction as one source.
        jurisdiction: str    = (request.POST.get('copilot_jurisdiction') or '').strip()
        # Mode toggle — 'approved' = only reviewed comparison + mapping rows;
        # 'document' = pure document Q&A against the picked scope (doc or country).
        mode: str            = (request.POST.get('copilot_mode') or 'approved').strip()

        # ── Intent gate ───────────────────────────────────────────────────────
        # Greetings, capability questions ("what can you do?") and "what
        # documents exist?" get a direct, helpful answer. Without this they were
        # forced through the compliance RAG and came back as "Insufficient
        # information to determine compliance" with 0% confidence.
        _direct = (_meta_reply(message)
                   or _corpus_reply(message, doc_title=doc_title, jurisdiction=jurisdiction))
        if _direct is not None:
            history.append({'role': 'user',      'content': message})
            history.append({'role': 'assistant', 'content': _direct})
            request.session['copilot_history'] = history[-20:]
            return render(request, 'partials/_copilot_fragment.html', {
                'user_message':       message,
                'ai_response':        _direct,
                'confidence':         None,
                'hallucination_risk': None,
                'citations':          [],
                'data_quality':       'guidance',
                'fallback_msg':       None,
            })

        # ── Arabic documents ──────────────────────────────────────────────────
        # Arabic docs live in the isolated bge-m3 collection (regulations_ar) and
        # are answered by the Arabic pipeline: qwen2.5 reads the Arabic and replies
        # in English with article citations. We detect them by asking the Arabic
        # store whether it holds chunks for this doc_title (its ``source`` id ==
        # the doc's chunk_doc_title, the same value the scope chip sends).
        if doc_title:
            try:
                from arabic import store as _ar_store
                _is_arabic = _ar_store.count(source=doc_title) > 0
            except Exception:
                _is_arabic = False
            if _is_arabic:
                from arabic.query import answer as _arabic_answer
                _res = _arabic_answer(message, source=doc_title)
                # resolve the Arabic doc's pk so the citation can open the viewer
                from apps.library.models import Document as _Doc
                _ar_pk = next((d.pk for d in _Doc.objects.only('id', 'file')
                               if d.chunk_doc_title == doc_title), '')
                _cits = []
                for h in _res['hits']:
                    _art = h.get('article_number')
                    _text = (h.get('text') or '')
                    _cits.append({
                        'reg_name':     h.get('law_name') or doc_title,
                        'article_ref':  f"Article ({_art})" if _art else '',
                        'jurisdiction': '',
                        'label':        f"Article ({_art})" if _art else doc_title,
                        'excerpt':      _text[:220],
                        'is_draft':     False,
                        # click → open the Arabic source, highlight the cited article
                        'doc_pk':       _ar_pk,
                        'node_id':      '',
                        'quote':        _text[:180],
                    })
                history.append({'role': 'user',      'content': message})
                history.append({'role': 'assistant', 'content': _res['answer']})
                request.session['copilot_history'] = history[-20:]
                return render(request, 'partials/_copilot_fragment.html', {
                    'user_message':       message,
                    'ai_response':        _res['answer'],
                    'confidence':         0.7,
                    'hallucination_risk': None,
                    'citations':          _cits,
                    'data_quality':       'regulatory',
                    'fallback_msg':       None,
                })

        if jurisdiction:
            # Country sources selected (from the Sources chip) — answer from the
            # regulatory text of those jurisdictions, regardless of the mode.
            reg_ctx, reg_cits = _retrieve_regulatory(message, jurisdiction=jurisdiction)
            _codes = ', '.join(c.strip().title() for c in jurisdiction.split(',') if c.strip())
            retrieval = {
                'context': reg_ctx, 'citations': reg_cits, 'layer': 'document',
                'data_quality': 'regulatory',
                'label': f'Sources — {_codes}',
                'fallback_msg': None,
            }
        elif mode == 'document':
            # Pure doc Q&A — needs a single-document scope to ground answers.
            if not doc_title:
                history.append({'role': 'user',      'content': message})
                history.append({'role': 'assistant', 'content':
                    "Pick a **document** from the Scope chip, or toggle a **country** in "
                    "**Sources** below — I answer strictly from the selected source(s)."})
                request.session['copilot_history'] = history[-20:]
                return render(request, 'partials/_copilot_fragment.html', {
                    'user_message':    message,
                    'ai_response':     history[-1]['content'],
                    'confidence':      0.0,
                    'hallucination_risk': None,
                    'citations':       [],
                    'data_quality':    'guidance',
                    'data_label':      'Document Q&A — pick a scope',
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

        # Prefer the chunks the retrieval layer already produced. In approved
        # mode these ARE the reviewed comparison/mapping rows (coverage verdict,
        # relationship, evidence) — so the LLM grounds its answer on the approved
        # analysis instead of on freshly re-fetched raw regulation text that the
        # "Approved data" badge implied but the model never actually saw.
        chunks = list(retrieval.get('chunks') or [])

        # Only re-fetch raw regulatory chunks when we DON'T already have grounded
        # chunks (document mode, regulatory lookups, or the no-approved fallback).
        if not chunks:
            from retrieval.retriever import hybrid_search
            try:
                kwargs_h = dict(query=message, top_k=5, rerank=True)
                if doc_title:
                    kwargs_h['doc_titles'] = [doc_title]
                elif jurisdiction:
                    js = [j.strip() for j in jurisdiction.split(',') if j.strip()]
                    if len(js) == 1:
                        kwargs_h['jurisdiction'] = js[0]
                    elif js:
                        kwargs_h['jurisdictions'] = js
                nodes = hybrid_search(**kwargs_h)
            except Exception:
                nodes = []
            # Structure-aware augmentation ("read like a person"): similarity
            # above found the document; now walk its outline, pick the relevant
            # article(s) and read them WHOLE, prepended ahead of the flat chunks.
            from django.conf import settings as _settings
            if getattr(_settings, 'NAVIGATOR_ENABLED', False):
                try:
                    from reasoning.navigator import navigate, top_doc_title
                    target = doc_title or top_doc_title(nodes)
                    nav_nodes = navigate(message, target) if target else []
                    if nav_nodes:
                        seen = {n.node.metadata.get('node_id') for n in nav_nodes}
                        nodes = nav_nodes + [n for n in nodes
                                             if n.node.metadata.get('node_id') not in seen]
                except Exception:
                    pass
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
        elif not _ollama_reachable():
            # Pre-flight: the PoC's LLM is local Ollama. If it isn't running,
            # say so precisely (and instantly) instead of letting the async
            # call fail with a connection error the catch-all mislabels as an
            # OpenRouter/API-key problem.
            ai_response = (
                "I can't reach the local AI engine (Ollama), so I can't generate "
                "an answer right now. Start it with `ollama serve` (or open the "
                "Ollama app), then ask again. Retrieval is working — I found "
                f"{len(chunks)} relevant passage(s), I just can't summarise them."
            )
            confidence = 0.0
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
                # network / parser / model-host failure — degrade gracefully.
                # The PoC's LLM is local Ollama, so a connection error means the
                # Ollama server isn't running — NOT an OpenRouter/API-key issue
                # (the old message here sent people down the wrong path). Give
                # the real remedy, and log the actual exception for diagnosis.
                import logging
                logging.getLogger(__name__).warning('copilot generation failed: %r', exc)
                _err = str(exc).lower()
                if 'connect' in _err or 'refused' in _err or 'timeout' in _err:
                    ai_response = (
                        "I can't reach the local AI engine (Ollama). Make sure it's "
                        "running — start it with `ollama serve` or open the Ollama "
                        "app — then try again."
                    )
                else:
                    ai_response = (
                        "The AI engine hit an error while answering. Please try again; "
                        "if it keeps happening, check the server logs for details."
                    )
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
