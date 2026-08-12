"""Requirement extraction v2 — segment, then normalise.

v1 asked one prompt to find an obligation AND restate it. Measured on Bahrain
PDPL that produced two failures: it under-extracted (Article 10 lists four
Guardian duties, two came back; 151 binding verbs across productive chunks
yielded 82 requirements), and it barely normalised (67% of outputs were
identical or near-identical to their own quote — asking for the rule and the
quote in one reply invites copying one into the other).

v2 splits the work so each step is small enough for a 7B model:

    chunk
      -> segment_clauses()      deterministic; enumerated sub-clauses become
                                separate units, so a four-duty article arrives
                                as four prompts instead of one
      -> stage 1                find the exact obligation-bearing SPANS.
                                Segmentation only — no prose, no rewriting.
      -> stage 2                restate ONE span as WHO + MUST + ACTION +
                                CONDITION. Rewriting only — the span is given.
      -> gates                  quote must be real, rule must not be a copy,
                                applicability must be supported or empty

Severity is deliberately not requested: v1's was 41% "medium" / 41% empty and
its single "critical" was a data-quality principle, so it is left NULL.

v1 remains importable and unchanged; v2 writes its own extractor version so the
two can coexist in the store.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

from ingestion.chunker import _OBLIGATION_RE, _PREAMBLE_RE   # noqa: E402
from reasoning.doc_intel import _chat_json                    # noqa: E402

MODEL = "qwen2.5:7b"
EXTRACTOR_VERSION = "qwen2.5:7b/v2"

# A quote may be short — "shall be published in the Official Gazette" is a
# complete provision — but a short one must still carry binding language, so a
# bare noun phrase cannot pass as a provision. See verify().
_MIN_QUOTE_CHARS = 12
_SHORT_QUOTE_CHARS = 25
_MIN_REQUIREMENT_CHARS = 15
# Above this word overlap the "normalised rule" is really the quote again.
_MAX_COPY_JACCARD = 0.9
# A segment shorter than this cannot carry a quote of _MIN_QUOTE_CHARS plus
# any context, so it is merged into its neighbour rather than prompted alone.
_MIN_SEGMENT_CHARS = 40

_VERDICT_RE = re.compile(
    r'\b(?:covered|not covered|complies|compliant|gap|adequate|'
    r'satisfies|meets the requirement)\b', re.IGNORECASE)

# A stem that introduces EXCEPTIONS rather than duties. Article (4) reads
# "Processing ... is prohibited without consent, unless the processing is
# necessary for: 1. ... 2. ...". The numbered items are the circumstances in
# which the prohibition lifts — they are not themselves obligations, and
# extracting them separately produced "Data subjects must take steps to enter
# into a contract", a duty on the wrong party that the law does not impose.
_EXCEPTION_STEM_RE = re.compile(
    r'\b(?:unless|except\s+where|except\s+in|except\s+for|other\s+than|'
    r'provided\s+that|save\s+where|save\s+in|'
    r'shall\s+not\s+apply\s+to|is\s+not\s+required)\b', re.IGNORECASE)

# "subject to" is only an exception marker when it governs a cross-reference or
# a condition ("subject to the provisions of Article 5", "subject to prior
# approval"). Bare "subject to penalties" is a consequence, and reading it as an
# exception made Article (59) discard its own sub-clauses.
_QUALIFIED_SUBJECT_TO_RE = re.compile(
    r'\bsubject\s+to\s+(?:the\s+|any\s+)?'
    r'(?:provision|article|paragraph|section|clause|condition|approval|'
    r'prior|exception|limitation|requirement)', re.IGNORECASE)

# The Stage 2 instruction is "WHO + must/shall + ACTION + CONDITION or
# DEADLINE". The model has been observed emitting that skeleton verbatim —
# "WHO must/shall process data only if necessary for: ..." — which is not a
# legal rule at all. Matched by SHAPE, not by vocabulary: a placeholder standing
# in the subject slot, or the literal "must/shall" alternation that no drafter
# writes. An ordinary provision that happens to mention a "condition" is
# untouched, which is why this is not a plain word blocklist.
_TEMPLATE_LEAK_RE = re.compile(
    r'^\s*(?:who|action|condition)\b'          # placeholder occupying the subject
    r'|\bmust\s*/\s*shall\b'                   # the literal alternation
    r'|\bshall\s*/\s*must\b'
    r'|\b(?:who|action)\s+(?:must|shall)\b'    # "WHO shall ..." anywhere
    r'|\bcondition\s+or\s+deadline\b'          # the tail of the template
    r'|\+\s*(?:action|condition)\b',
    re.IGNORECASE)

# Binding language, used to decide whether a SHORT quote is a real provision.
_MODAL_RE = re.compile(
    r'\b(?:shall|must|may\s+not|may|is\s+prohibited|is\s+required|'
    r'required\s+to|is\s+obliged)\b', re.IGNORECASE)

# Head nouns that denote a legal actor. A requirement whose subject is not one
# of these — "processing must be necessary for" — names no one who could be
# held to it.
_ACTOR_NOUNS = (
    'controller', 'processor', 'subject', 'authority', 'board', 'guardian',
    'person', 'party', 'bank', 'entity', 'applicant', 'executive', 'minister',
    'committee', 'chairman', 'employer', 'employee', 'operator', 'provider',
    'institution', 'company', 'organisation', 'organization', 'recipient',
    'officer', 'government', 'court', 'prosecution', 'council', 'licensee',
)


# Subjects that are not a party but still carry a rule. "A fee shall be
# imposed", "The register shall comprise ...", "Notifications shall be promptly
# recorded" are real obligations written impersonally — the law acts on an
# instrument rather than naming who acts. Deliberately concrete: 'processing'
# and similar abstractions are excluded, because "Processing must be necessary
# for ..." is an exception fragment, not a rule.
_INSTRUMENT_NOUNS = (
    'fee', 'register', 'notification', 'notice', 'record', 'report',
    'application', 'decision', 'resolution', 'penalty', 'fine', 'authorisation',
    'authorization', 'request', 'complaint', 'licence', 'license', 'certificate',
    'decree', 'order', 'budget', 'data', 'appointment', 'register',
)


def _singular(word: str) -> str:
    """Crude morphological singulariser — enough for legal actor nouns.

    Replaces a substring test that could not see "parties" as "party", because
    'party' is not a substring of 'parties'. The same blindness hit
    "authorities" and "companies", and each cost real requirements.
    """
    w = (word or '').lower()
    for suf, rep in (('ies', 'y'), ('sses', 'ss'), ('ches', 'ch'),
                     ('shes', 'sh'), ('xes', 'x'), ('ses', 's'), ('s', '')):
        if w.endswith(suf) and len(w) > len(suf) + 1:
            return w[:-len(suf)] + rep
    return w


def _head_noun(phrase: str, vocabulary: tuple) -> str:
    """First word of `phrase` whose singular form is in `vocabulary`."""
    for tok in re.findall(r'[A-Za-z]+', phrase or ''):
        s = _singular(tok)
        if s in vocabulary:
            return s
    return ''


def stem_introduces_exceptions(stem: str) -> bool:
    """Does this lead-in introduce exceptions rather than a list of duties?

    "subject to" alone is not enough: "shall be subject to penalties" is an
    ordinary consequence clause, not an exception, and treating it as one made
    Article (59) drop its sub-clauses. The phrase only marks an exception when
    it governs a cross-reference or a condition.
    """
    if not stem:
        return False
    if _EXCEPTION_STEM_RE.search(stem):
        return True
    return bool(_QUALIFIED_SUBJECT_TO_RE.search(stem))


def actor_of(text: str) -> str:
    """The words before the first modal — the party the rule binds."""
    m = _MODAL_RE.search(text or '')
    if not m:
        return ''
    return (text[:m.start()] or '').strip(' ,.;:')


# "... shall be published BY THE AUTHORITY" — a passive provision that names
# its agent explicitly. Only the agent of the obligation counts, so the phrase
# has to be a `by <actor>` immediately governed by the modal, not any later
# mention of an actor elsewhere in the sentence.
_PASSIVE_AGENT_RE = re.compile(
    r'\bby\s+(?:the\s+|a\s+|an\s+)?[\w\s]{0,30}?\b(' + '|'.join(_ACTOR_NOUNS) + r')\b',
    re.IGNORECASE)


def has_grounded_actor(text: str, *sources: str) -> tuple[bool, str]:
    """Is a legal actor in the SUBJECT position of this rule?

    Searching the whole sentence for an actor word was too weak: it accepted
    "WHO must/shall process data ... of the data subject" because "subject"
    appeared downstream, and it accepted subject-less fragments like "shall
    assist the data controller" because "controller" was the OBJECT. Who is
    bound is determined by the subject, so only the subject is consulted —
    or, for a passive rule, the explicit `by <actor>` agent.
    """
    body = (text or '').strip()
    m = _MODAL_RE.search(body)
    if not m:
        return False, 'requirement states no obligation (no modal verb)'

    subject = body[:m.start()].strip(' ,.;:')
    if not subject:
        # "shall assist the data controller ..." — the duty is stated with no
        # one attached to it. The object cannot stand in for the subject.
        return False, 'requirement has no grammatical subject'

    src = _norm(' '.join(sources))
    src_tokens = {_singular(t) for t in re.findall(r'[A-Za-z]+', src)}

    # 1. A named legal actor in the subject. Matched by singularised token, so
    #    "parties" resolves to "party".
    head = _head_noun(subject, _ACTOR_NOUNS)
    if head:
        if head not in src_tokens:
            return False, f'actor {head!r} is not named in the source'
        return True, ''

    # 2. Passive with a named agent: the subject is the thing acted on, so the
    #    actor is whoever the `by` phrase names.
    # An ungrounded agent is not fatal on its own — the rule may still be a
    # valid impersonal provision, checked next — so this falls through rather
    # than returning.
    pm = _PASSIVE_AGENT_RE.search(body[m.end():])
    if pm and _singular(pm.group(1)) in src_tokens:
        return True, ''

    # 3. Impersonal provision. The law can bind an instrument rather than a
    #    party — "A fee shall be imposed", "The register shall comprise". These
    #    are real requirements, so they get their own path rather than the actor
    #    gate being loosened for everyone: the subject must still be a concrete
    #    legal instrument named in the source, which an arbitrary subject-less
    #    or invented output cannot satisfy.
    inst = _head_noun(subject, _INSTRUMENT_NOUNS)
    if inst:
        if inst not in src_tokens:
            return False, f'impersonal subject {inst!r} is not named in the source'
        return True, ''

    return False, f'subject {subject[:40]!r} is not a legal actor'

# Enumerated sub-clause markers: "1." "2)" "(3)" "(a)" at a clause boundary.
# Anchored to start-of-line or after sentence punctuation so a numeral inside a
# sentence ("within 72 hours") cannot split it.
_CLAUSE_MARKER = re.compile(
    r'(?:(?<=^)|(?<=[.;:])|(?<=\n))\s*'
    r'(\(?\d{1,2}\)?[.)]|\([a-z]\))\s+',
    re.MULTILINE)


# Prepended when a first Stage 1 reply came back with span objects but no
# quotes in any of them.
_STAGE1_RETRY_NOTE = (
    'Your previous answer returned spans with an EMPTY "source_quote". That is '
    'never acceptable. Every element must carry words copied from the passage. '
    'If the passage imposes no obligation, return {"spans": []}.\n\n')

# Content words carried by a provision. A normalised rule that keeps almost none
# of them has thrown the substance away — see _keeps_substance.
_STOPWORDS = {
    'the', 'and', 'or', 'of', 'to', 'in', 'for', 'a', 'an', 'shall', 'must',
    'may', 'be', 'is', 'are', 'this', 'that', 'which', 'with', 'by', 'on',
    'at', 'as', 'from', 'any', 'such', 'not', 'his', 'her', 'its',
    'their', 'it', 'he', 'she', 'they', 'under', 'upon', 'been',
}
# Only applied to substantial provisions; a short one legitimately normalises to
# something of similar length.
_SUBSTANCE_MIN_QUOTE = 80
_SUBSTANCE_MIN_KEPT = 0.35


def _content_words(text: str) -> set:
    return {_singular(t) for t in re.findall(r'[A-Za-z]{3,}', (text or '').lower())
            if t.lower() not in _STOPWORDS}


def _keeps_substance(text: str, quote: str) -> tuple[bool, float]:
    """Does the rule still carry what the provision was about?

    Article (11) showed the failure this catches: "The Board shall pass a
    resolution prescribing the conditions to be considered when creating the
    registers" was normalised to "The board shall pass a resolution", dropping
    the entire purpose. That is not a rephrasing, it is a truncation, and it
    reached the anti-copy gate disguised as a copy.
    """
    qw = _content_words(quote)
    if len(quote) < _SUBSTANCE_MIN_QUOTE or not qw:
        return True, 1.0
    kept = len(qw & _content_words(text)) / len(qw)
    return kept >= _SUBSTANCE_MIN_KEPT, kept


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()


def _words(s: str) -> set:
    return set(re.findall(r'[a-z0-9]+', _norm(s)))


def jaccard(a: str, b: str) -> float:
    """Word overlap between two texts, 0-1."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def is_obligation_text(text: str) -> bool:
    """Binding language present and not preamble — the chunker's own signal."""
    body = text or ''
    return bool(_OBLIGATION_RE.search(body)) and not _PREAMBLE_RE.search(body)


def segment_clauses(chunk_text: str) -> list[dict]:
    """Split a provision into its enumerated sub-clauses, deterministically.

    Article 10's four Guardian duties are one chunk but four obligations; asked
    as a single prompt the model returned two. Splitting first means each duty
    is presented on its own, which is the measured under-extraction case.

    Every segment is a verbatim SUBSTRING of the chunk, so a quote verified
    against a segment is automatically verified against the chunk. Segments too
    short to carry an obligation are merged forward rather than dropped — a
    lone "3." must not become a unit.
    """
    text = (chunk_text or '').strip()
    if not text:
        return []
    marks = list(_CLAUSE_MARKER.finditer(text))
    if not marks:
        return [{'label': '', 'text': text, 'start': 0}]

    pieces: list[dict] = []
    # Anything before the first marker is the stem ("The Guardian is
    # responsible for the following:") and is kept — it carries the subject the
    # sub-clauses inherit.
    if marks[0].start() > 0:
        head = text[:marks[0].start()].strip()
        if head:
            pieces.append({'label': '', 'text': head, 'start': 0})
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        if body:
            pieces.append({'label': m.group(1), 'text': body, 'start': m.end()})

    # Merge runts so no prompt receives a fragment: backwards into the previous
    # segment where there is one, otherwise forwards into the next. A leading
    # runt has nothing behind it, so a backwards-only pass would leave it.
    merged: list[dict] = []
    for p in pieces:
        if merged and len(p['text']) < _MIN_SEGMENT_CHARS:
            merged[-1]['text'] += ' ' + p['text']
        else:
            merged.append(p)
    while len(merged) > 1 and len(merged[0]['text']) < _MIN_SEGMENT_CHARS:
        merged[1]['text'] = merged[0]['text'] + ' ' + merged[1]['text']
        merged[1]['start'] = merged[0]['start']
        merged.pop(0)
    return merged


_STAGE1_PROMPT = """Mark the spans of this passage that impose a legal obligation.

Stage 1 does ONE job: point at the exact words. Do not rewrite, summarise,
classify or judge anything.

An obligation binds someone to act, to refrain, or to exercise a function.
Include all of these — each has been missed before:
- a duty on a party:            "the controller shall notify the Authority"
- a prohibition:                "processing is prohibited without consent"
- a passive duty:               "the report shall be submitted to the Board"
- an institutional or statutory duty, including general ones:
                                "the Authority shall carry out its duties
                                 efficiently and transparently"
                                "the Board shall elect a Deputy Chairman"
- an impersonal duty:           "a fee shall be imposed on an application"
- a duty with a deadline or condition:
                                "shall reply within ten working days"

A provision does not need a concrete transaction to be an obligation. A duty to
exercise a function, or to act in a particular manner, counts.

Exclude definitions, scope statements ("this Law shall apply to ..."), recitals,
and descriptions of what something contains.

Copy each span EXACTLY from the passage. Never return an element whose
"source_quote" is empty — leave it out instead. If nothing qualifies, return
{"spans": []}, which is a correct answer.

Return JSON: {"spans": [{"source_quote": "...", "reason": "..."}]}

Passage{ref}:
---
{body}
---
JSON:"""




_STAGE2_PROMPT = """Restate ONE regulatory provision as a single normalised rule.

The provision:
---
{quote}
---

Write it as: the bound party, then must/shall/may, then the COMPLETE action,
then every condition, deadline, limit and qualification the provision attaches.

Rules:
- ONE sentence, but a COMPLETE one. Rephrase — do not copy word for word.
- Keep EVERYTHING the provision makes legally operative: what must be done, to
  what or to whom, by when, under what conditions, subject to what limits.
- Do NOT stop at the opening clause. A provision reading "The Board shall pass a
  resolution prescribing the conditions to be considered when creating the
  registers" becomes "The Board must issue a resolution setting the conditions
  that apply when registers are created" — NOT "The Board shall pass a
  resolution", which discards what the resolution is for.
- Add nothing the provision does not say.
- If the provision names no party, keep the rule impersonal ("A fee must be
  imposed on an application to record in the register"). Do not invent a party.
- Never state whether anyone complies with it.

Return a JSON object:
- "requirement_text": the normalised rule
- "title": a short label, at most 80 characters
- "applicability": the party bound, EXACTLY as the provision names them
  (e.g. "data controller", "the Authority"). "" if the provision does not say.
- "topics": 1-3 short lowercase subject tags

JSON:"""


# Stage 1 outcome categories. The distinction that matters is whether the model
# FAILED to answer or DECIDED there was nothing — those were previously
# indistinguishable, because doc_intel._chat_json returns {} for both a timeout
# and a well-formed reply, so 20 "no spans array" rejections could not be told
# apart from genuine judgements.
STAGE1_TECHNICAL = 'TECHNICAL_FAILURE'
STAGE1_EMPTY     = 'EMPTY_SPANS'
STAGE1_VALID     = 'VALID_SPANS'

_STAGE1_MAX_ATTEMPTS = 2      # bounded: one retry, never a loop


def _call_model(prompt: str, *, model: str = MODEL, timeout: int = 120) -> tuple:
    """One model call that classifies its own failure. Never raises.

    Deliberately not doc_intel._chat_json: that is shared with v1 and collapses
    every failure into {}. This keeps v1 untouched while making the failure mode
    observable — which is the whole point of the exercise.

    Returns (data|None, diagnostic). The diagnostic never contains document text.
    """
    t0 = time.perf_counter()
    try:
        import ollama
        from config import OLLAMA_URL
        resp = ollama.Client(host=OLLAMA_URL, timeout=timeout).chat(
            model=model, messages=[{'role': 'user', 'content': prompt}],
            format='json', options={'temperature': 0, 'num_ctx': 8192})
        raw = (resp.get('message', {}) or {}).get('content', '') or ''
    except Exception as exc:
        name = type(exc).__name__
        status = 'timeout' if 'timeout' in name.lower() or 'timeout' in str(exc).lower() \
            else 'call_failed'
        return None, {'status': status, 'error': name, 'detail': str(exc)[:120],
                      'elapsed': round(time.perf_counter() - t0, 1),
                      'response_chars': 0, 'prompt_chars': len(prompt)}

    elapsed = round(time.perf_counter() - t0, 1)
    base = {'elapsed': elapsed, 'response_chars': len(raw), 'prompt_chars': len(prompt)}
    if not raw.strip():
        return None, {'status': 'empty_response', **base}
    try:
        data = json.loads(raw)
    except Exception as exc:
        return None, {'status': 'parse_failed', 'error': type(exc).__name__, **base}
    if not isinstance(data, dict):
        return None, {'status': 'shape_failed', **base}
    return data, {'status': 'ok', **base}


def _spans_of(data) -> list | None:
    """The spans array from a reply, or None when the field is absent/ill-typed."""
    if not isinstance(data, dict):
        return None
    spans = data.get('spans')
    if isinstance(spans, dict):
        spans = [spans]
    return spans if isinstance(spans, list) else None


def find_spans(segment_text: str, article_ref: str = '', *, context: str = '',
               chat=None, diag: dict | None = None) -> tuple[list[dict], list[str]]:
    """Stage 1 — locate obligation-bearing spans. No rewriting happens here.

    `context` is the enclosing stem ("The Guardian is responsible for the
    following:"). It is shown so the model knows who is bound, but quotes must
    still come from the passage, so a quote can never span the two.
    """
    body = (segment_text or '').strip()
    if diag is None:
        diag = {}
    diag.update({'category': STAGE1_TECHNICAL, 'attempts': 0, 'elapsed': 0.0,
                 'statuses': [], 'article_ref': article_ref})
    if not body:
        diag['category'] = STAGE1_EMPTY
        return [], []

    prompt = (f'Context (for meaning only — do NOT quote from this):\n{context}\n\n'
              if context else '') + _STAGE1_PROMPT.replace('{body}', body) \
        .replace('{ref}', f' ({article_ref})' if article_ref else '')

    spans = None
    for attempt in range(1, _STAGE1_MAX_ATTEMPTS + 1):
        diag['attempts'] = attempt
        text = prompt if attempt == 1 else (_STAGE1_RETRY_NOTE + prompt)
        if chat is not None:                      # injected stub (tests)
            data, d = chat(text, MODEL), {'status': 'ok', 'elapsed': 0.0}
        else:
            data, d = _call_model(text)
        diag['statuses'].append(d['status'])
        diag['elapsed'] = round(diag['elapsed'] + d.get('elapsed', 0.0), 1)
        for k in ('error', 'detail', 'response_chars', 'prompt_chars'):
            if k in d:
                diag[k] = d[k]

        candidate = _spans_of(data)
        if candidate is None:
            continue                              # technical: no usable spans field
        if candidate == []:
            spans = []                            # a judgement: nothing here
            break
        # An array of span objects that all lack a quote is a malformed answer,
        # not a judgement — leave `spans` unset so this retries and, if it fails
        # again, is reported as the technical failure it is.
        if all(not (s.get('source_quote') or '').strip()
               for s in candidate if isinstance(s, dict)):
            continue
        spans = candidate
        break

    if spans is None:
        diag['category'] = STAGE1_TECHNICAL
        return [], [f'stage1: technical failure ({",".join(diag["statuses"])})']
    if not spans:
        # The model answered cleanly and found nothing. Distinct from a failure,
        # and deliberately NOT retried further — that is a judgement to evaluate,
        # not an error to paper over.
        diag['category'] = STAGE1_EMPTY
        return [], []

    diag['category'] = STAGE1_VALID
    ok, bad = [], []
    seen: set = set()
    for s in spans:
        if not isinstance(s, dict):
            bad.append('stage1: span not an object')
            continue
        q = (s.get('source_quote') or '').strip()
        # Diagnosed by sampling: the great majority of what used to be counted
        # as "span too short" was the model returning a span object with NO
        # quote at all. That is a malformed reply, not a short provision being
        # lost, so lowering the length floor further would achieve nothing —
        # it is reported separately to keep that visible.
        if not q:
            bad.append('stage1: span had no quote')
            continue
        # A lead-in that introduces a list ("the data controller shall:") is not
        # an obligation by itself; its sub-clauses are segmented separately and
        # carry the duty. Skipped rather than counted as a failure.
        if q.rstrip().endswith(':'):
            bad.append('stage1: span is a list lead-in, not a provision')
            continue
        if len(q) < _MIN_QUOTE_CHARS:
            bad.append('stage1: span too short')
            continue
        if _norm(q) not in _norm(body):
            bad.append('stage1: span not verbatim in the passage')
            continue
        if _norm(q) in seen:
            bad.append('stage1: duplicate span')
            continue
        seen.add(_norm(q))
        ok.append({'source_quote': q, 'marker': str(s.get('marker') or '').strip()})
    return ok, bad


def normalise_span(quote: str, *, conditions: str = '', chat=None) -> tuple[dict | None, str]:
    """Stage 2 — turn one verified span into a normalised rule.

    `conditions` carries the exception list belonging to this rule, so the rule
    can be stated WITH its exceptions ("may process without consent where
    necessary for performance of a contract") instead of the exceptions being
    split off into duties of their own.
    """
    chat = chat or _chat_json
    prompt = _STAGE2_PROMPT.replace('{quote}', quote)
    if conditions:
        prompt = (prompt + '\n\nThe provision is subject to these exceptions. '
                  'State them as CONDITIONS of the rule above — they are not '
                  'separate obligations and impose nothing on anyone named '
                  'inside them:\n' + conditions[:900])
    data = chat(prompt, MODEL)
    if not isinstance(data, dict) or not data:
        return None, 'stage2: non-object reply'
    text = (data.get('requirement_text') or '').strip()
    if len(text) < _MIN_REQUIREMENT_CHARS:
        return None, 'stage2: requirement_text missing or too short'
    topics = data.get('topics') or []
    if isinstance(topics, str):
        topics = [topics]
    return {
        'requirement_text': text,
        'title':            (data.get('title') or text)[:300],
        'applicability':    (data.get('applicability') or '').strip(),
        'topics':           [str(t).strip().lower() for t in topics if str(t).strip()][:3],
    }, ''


def verify(rule: dict, quote: str, chunk_text: str, *, stem: str = '') -> tuple[bool, str]:
    """Every gate a v2 candidate must pass.

    The first three are v1's, kept because they caught real failures on live
    output (3 fabricated quotes, 2 coverage verdicts). The last two are new and
    target what the v1 evaluation measured: text that is really the quote again,
    and an actor the provision never names.
    """
    text  = (rule.get('requirement_text') or '').strip()
    appl  = (rule.get('applicability') or '').strip()

    if len(text) < _MIN_REQUIREMENT_CHARS:
        return False, 'requirement_text missing or too short'
    if len(quote) < _MIN_QUOTE_CHARS:
        return False, 'source_quote missing or too short'
    # A short quote is allowed — many provisions genuinely are short — but it
    # must still read as a provision, so it has to carry binding language rather
    # than being a stray noun phrase the model happened to lift.
    if len(quote) < _SHORT_QUOTE_CHARS and not _MODAL_RE.search(quote):
        return False, 'short quote carries no binding language'
    # The anti-invention gate: the quote has to be real.
    if _norm(quote) not in _norm(chunk_text):
        return False, 'source_quote is not present in the source chunk'
    if _VERDICT_RE.search(text):
        return False, 'reads as a coverage verdict, not a requirement'
    # Checked before the copy gates so a leaked template is diagnosed as what it
    # is rather than as some downstream symptom.
    if _TEMPLATE_LEAK_RE.search(text):
        return False, 'requirement contains prompt-template text'
    # NEW — the rule must actually be a restatement, not the quote again.
    if _norm(text) == _norm(quote):
        return False, 'requirement is identical to the source quote'
    j = jaccard(text, quote)
    if j >= _MAX_COPY_JACCARD:
        return False, f'requirement is a near-copy of the quote (jaccard {j:.2f})'
    # Actor before substance: a rule with no valid subject is defective in a more
    # fundamental way than one that is merely short, and diagnosing it as a
    # truncation would hide that.
    ok_actor, why = has_grounded_actor(text, chunk_text, stem)
    if not ok_actor:
        return False, why
    # Truncation: a rule that keeps almost none of the provision's content words
    # is not a shorter statement of it, it is a different and smaller claim.
    kept_ok, kept = _keeps_substance(text, quote)
    if not kept_ok:
        return False, (f"requirement drops the provision's substance "
                       f"({kept:.0%} of content retained)")
    # NEW — an actor the provision does not name is an inference, not evidence.
    if appl:
        head = appl.lower().replace('the ', '').split()
        head = head[0].rstrip('s') if head else ''
        if head and head not in _norm(chunk_text):
            return False, 'applicability is not supported by the source chunk'
    return True, ''


def extract_from_chunk(chunk: dict, *, chat=None) -> tuple[list[dict], list[str]]:
    """Run the whole v2 pipeline over ONE chunk.

    Returns (accepted, rejections). Rejections are returned, not swallowed, so a
    caller can tell a quiet provision from a failing prompt.
    """
    body = (chunk.get('content') or '').strip()
    if not body:
        return [], []
    ref = (chunk.get('article_ref') or '').strip()
    node = chunk.get('node_id') or ''

    # The obligation filter is applied to the CHUNK, never to a segment. A
    # sub-clause inherits its binding verb from the stem — Article 10's duties
    # read "Assisting...", "liaising...", with the "is responsible for" sitting
    # above them — so filtering per segment would discard precisely the
    # multi-duty articles this stage exists to recover.
    if not is_obligation_text(body):
        return [], []

    segments = segment_clauses(body)
    # The stem carries the subject the sub-clauses inherit. It is passed as
    # CONTEXT, not as part of the passage, so a quote can never straddle the
    # join and fail verbatim verification against the chunk.
    # The stem is the lead-in that introduces a list of duties. It may itself be
    # numbered ("1. The Guardian is responsible for the following:"), so it is
    # recognised by the trailing colon as well as by having no marker.
    stem = ''
    if segments:
        first = segments[0]['text']
        if not segments[0]['label'] or first.rstrip().endswith(':'):
            stem = first

    # When the stem introduces EXCEPTIONS, the listed items are the conditions
    # under which the parent rule lifts, not rules of their own. Only the stem
    # is extracted; the exception text stays with it as context so the rule can
    # be stated with its conditions rather than split into fictitious duties.
    exceptions = stem_introduces_exceptions(stem)
    condition_text = ''
    if exceptions:
        condition_text = ' '.join(s['text'] for s in segments if s['text'] != stem)
        segments = [s for s in segments if s['text'] == stem]


    accepted, rejected = [], []
    seen: set = set()
    for seg in segments:
        context = '' if seg['text'] == stem else stem
        spans, bad = find_spans(seg['text'], ref, context=context, chat=chat)
        rejected.extend(bad)
        for sp in spans:
            quote = sp['source_quote']
            rule, why = normalise_span(quote, conditions=condition_text, chat=chat)
            if rule is None:
                rejected.append(why)
                continue
            ok, why = verify(rule, quote, body, stem=stem)
            if not ok:
                rejected.append(why)
                continue
            key_text = _norm(rule['requirement_text'])
            if key_text in seen:
                rejected.append('duplicate requirement within the chunk')
                continue
            seen.add(key_text)
            accepted.append({
                'text':              rule['requirement_text'],
                'title':             rule['title'],
                'article_ref':       ref,
                'source_chunk_id':   node,
                'source_quote':      quote,
                'applicability':     rule['applicability'],
                'topics':            rule['topics'],
                # Left NULL on purpose — v1's severity was 41% "medium",
                # 41% empty, and its one "critical" was a data-quality principle.
                'inherent_severity': None,
                'extraction_model':  EXTRACTOR_VERSION,
            })
    return accepted, rejected
