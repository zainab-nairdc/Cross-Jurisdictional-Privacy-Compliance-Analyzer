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

import logging
import re
import sys
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
    r'\b(?:unless|except\s+where|except\s+in|other\s+than|'
    r'provided\s+that|subject\s+to|save\s+where|save\s+in|'
    r'shall\s+not\s+apply\s+to|is\s+not\s+required)\b', re.IGNORECASE)

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


def stem_introduces_exceptions(stem: str) -> bool:
    """Does this lead-in introduce exceptions rather than a list of duties?"""
    return bool(stem) and bool(_EXCEPTION_STEM_RE.search(stem))


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
    head = next((n for n in _ACTOR_NOUNS if n in subject.lower()), '')
    if head:
        if head not in src:
            return False, f'actor {head!r} is not named in the source'
        return True, ''

    # Passive with a named agent: the subject is the thing acted on, so the
    # actor is whoever the `by` phrase names.
    pm = _PASSIVE_AGENT_RE.search(body[m.end():])
    if pm:
        agent = pm.group(1).lower()
        if agent not in src:
            return False, f'passive agent {agent!r} is not named in the source'
        return True, ''

    return False, f'subject {subject[:40]!r} is not a legal actor'

# Enumerated sub-clause markers: "1." "2)" "(3)" "(a)" at a clause boundary.
# Anchored to start-of-line or after sentence punctuation so a numeral inside a
# sentence ("within 72 hours") cannot split it.
_CLAUSE_MARKER = re.compile(
    r'(?:(?<=^)|(?<=[.;:])|(?<=\n))\s*'
    r'(\(?\d{1,2}\)?[.)]|\([a-z]\))\s+',
    re.MULTILINE)


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


_STAGE1_PROMPT = """You are marking up ONE passage of a regulation. Find every
span that imposes an obligation.

An obligation is something a party MUST do, MUST NOT do, or MAY do subject to
conditions. Include ALL of these forms — they are commonly missed:
- prohibition with exceptions: "X is prohibited unless ..."
- passive obligation: "the report shall be submitted", "employees shall be recruited"
- deadline-bearing duty: "shall notify ... within ten working days"
- conditional duty: "where processing is necessary, the controller shall ..."
- each item of a numbered list of duties is a SEPARATE obligation

Definitions, scope statements and recitals impose nothing — return an empty list
for those.

DO NOT rewrite, summarise or explain anything at this stage. Your only job is to
COPY the exact spans.

Return a JSON object with one key "spans", an array. Each element:
- "source_quote": the span copied CHARACTER FOR CHARACTER from the passage
  below. It must be long enough to state the obligation on its own.
- "marker": the clause number/letter it came from if the passage shows one, else ""

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

Write it in this shape:
    WHO + must/shall/may + ACTION + CONDITION or DEADLINE

Rules:
- ONE sentence. Concise. State the rule, not a description of the text.
- Do NOT copy the provision word for word. Rephrase it into the shape above.
- If the provision names no actor, use the actor the text implies ONLY if it is
  stated in the provision; otherwise write the rule impersonally.
- Never state whether anyone complies with it.

Return a JSON object:
- "requirement_text": the normalised rule
- "title": a short label, at most 80 characters
- "applicability": the party bound, EXACTLY as the provision names them
  (e.g. "data controller", "the Authority"). "" if the provision does not say.
- "topics": 1-3 short lowercase subject tags

JSON:"""


def find_spans(segment_text: str, article_ref: str = '', *, context: str = '',
               chat=None) -> tuple[list[dict], list[str]]:
    """Stage 1 — locate obligation-bearing spans. No rewriting happens here.

    `context` is the enclosing stem ("The Guardian is responsible for the
    following:"). It is shown so the model knows who is bound, but quotes must
    still come from the passage, so a quote can never span the two.
    """
    body = (segment_text or '').strip()
    if not body:
        return [], []
    chat = chat or _chat_json
    prefix = (f'Context (for meaning only — do NOT quote from this):\n{context}\n\n'
              if context else '')
    data = chat(prefix + _STAGE1_PROMPT.replace('{body}', body)
                .replace('{ref}', f' ({article_ref})' if article_ref else ''), MODEL)
    if not isinstance(data, dict):
        return [], ['stage1: non-object reply']
    spans = data.get('spans')
    if isinstance(spans, dict):
        spans = [spans]
    if not isinstance(spans, list):
        return [], ['stage1: no "spans" array']

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
    # Actor last: it is the most specific diagnosis, and running it earlier made
    # a copied quote report "names no actor" instead of "is a copy".
    ok_actor, why = has_grounded_actor(text, chunk_text, stem)
    if not ok_actor:
        return False, why
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
