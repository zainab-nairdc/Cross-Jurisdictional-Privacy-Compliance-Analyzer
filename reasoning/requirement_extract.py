"""Native requirement extraction — regulation text in, canonical requirements out.

This module reads ONE regulation's provisions and states what they require. It
is deliberately blind to everything else: it never receives internal policy
text, retrieval results, coverage verdicts, gaps or ObligationMappings, and it
produces no verdict of its own. That isolation is the point — a requirement is a
property of the regulation, so anything a policy might contribute would make it
a property of a comparison instead.

Two texts come out of every candidate, and they are not interchangeable:

    requirement_text — a normalised statement of the obligation
    source_quote     — verbatim regulatory evidence, copied from the chunk

The migrated baseline stored the verbatim quote in both slots because rebuilding
history could not invent a normalised statement. That is a floor, not a model to
imitate: native extraction must produce the statement AND keep the quote.

Nothing reaches the store unverified. `verify_candidate` is the only way in, and
it rejects rather than repairs.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

# The same binding-language signal the chunker already tags with, imported
# rather than re-written so there is ONE definition of "this is a rule".
from ingestion.chunker import _OBLIGATION_RE, _PREAMBLE_RE   # noqa: E402

from reasoning.doc_intel import _chat_json                    # noqa: E402

MODEL = "qwen2.5:7b"

# A quote must be a real span of the provision, not a couple of words that
# happen to appear. Short enough to allow a terse clause, long enough that
# "shall" alone cannot pass.
_MIN_QUOTE_CHARS = 25
_MIN_REQUIREMENT_CHARS = 15
# NLI risk above this means the statement does not follow from its own quote.
# Deliberately permissive: normalisation legitimately rephrases, and the
# structural quote check already guarantees the evidence is real.
#
# NOTE: `nli` is OPT-IN and currently left unwired by the extraction command.
# The available scorer, reasoning.workflow_helpers.score_text_against_chunk,
# is inverted: cross-encoder/nli-deberta-v3-base labels are
# {0: contradiction, 1: entailment, 2: neutral}, but it reads probs[0, 2] —
# neutral — and reports 1 - that as "risk". Measured on this corpus it returns
# 0.99 for a requirement IDENTICAL to its own quote and 0.00 for one the text
# does not support, so using it as a gate would reject exactly the valid
# extractions. The parameter is kept because the check is correct in principle
# and this becomes useful the moment the scorer's polarity is fixed; that fix
# belongs with the comparison pipeline that depends on it, not here.
_MAX_UNSUPPORTED = 0.90

_SEVERITIES = ('critical', 'high', 'medium', 'low')


_EXTRACT_PROMPT = """You are a compliance analyst reading ONE provision of a
regulation. List the distinct obligations it imposes.

An obligation is something a party MUST or MUST NOT do. Definitions, scope
statements, recitals and commentary are NOT obligations — return an empty list
for those rather than inventing one.

Return a JSON object with ONE key, "requirements", an array. Each element:
- "requirement_text": ONE sentence stating the obligation in plain normalised
  form, e.g. "The controller must notify the Authority within 72 hours of
  becoming aware of a breach." Write it as a rule, not as a description of the
  text and not as a judgement about anyone's compliance.
- "source_quote": the EXACT words from the provision below that impose it,
  copied CHARACTER FOR CHARACTER. Do not paraphrase, do not join separated
  fragments, do not correct spelling. If you cannot copy an exact span that
  imposes the obligation, omit the element entirely.
- "applicability": who is bound — e.g. "controller", "processor", "bank",
  "data subject". "" if the provision does not say.
- "inherent_severity": how serious a breach of THIS obligation would be, one of
  "critical", "high", "medium", "low". Judge the obligation itself, not anyone's
  compliance with it. "" if unclear.
- "topics": 1-3 short lowercase subject tags, e.g. ["breach notification"].

If the provision imposes several separate obligations, return several elements.
If it imposes none, return {"requirements": []} — that is a correct answer.

Provision{ref}:
---
{body}
---
JSON:"""


def _norm(s: str) -> str:
    """Whitespace/case-insensitive form for quote matching.

    PDF extraction varies line breaks and spacing inside a sentence, so an
    exact-substring test would reject quotes that ARE verbatim. Normalising
    both sides keeps the check strict about words while tolerant of layout.
    """
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()


def is_obligation_chunk(text: str) -> bool:
    """Does this chunk carry binding language, and is it not preamble?

    Reuses the chunker's existing signal — the same regex that sets the
    `is_obligation` metadata flag at ingest — instead of introducing a second,
    divergent notion of what counts as a rule. Preamble is excluded for the
    same reason the chunker excludes it: 'whereas' clauses recite background.
    """
    body = text or ''
    if not _OBLIGATION_RE.search(body):
        return False
    if _PREAMBLE_RE.search(body):
        return False
    return True


def candidate_chunks(chunks: list[dict]) -> list[dict]:
    """Narrow a regulation's chunks to those that could carry an obligation."""
    return [c for c in chunks if is_obligation_chunk(c.get('content') or '')]


def verify_candidate(cand: dict, chunk_text: str, *, nli=None) -> tuple[bool, str]:
    """Is this model output admissible? Returns (ok, reason_if_not).

    Four gates, cheapest first. The model is never trusted to have copied
    honestly, so the quote is checked against the chunk it was supposedly taken
    from — this is what makes it impossible to persist a requirement the
    regulation does not contain.
    """
    if not isinstance(cand, dict):
        return False, 'not an object'

    text  = (cand.get('requirement_text') or '').strip()
    quote = (cand.get('source_quote') or '').strip()

    # 1. required fields
    if len(text) < _MIN_REQUIREMENT_CHARS:
        return False, 'requirement_text missing or too short'
    if len(quote) < _MIN_QUOTE_CHARS:
        return False, 'source_quote missing or too short'

    # 2. the quote must actually occur in the chunk — the anti-invention gate
    if _norm(quote) not in _norm(chunk_text):
        return False, 'source_quote is not present in the source chunk'

    # 3. the statement must not merely restate the model's opinion of coverage.
    #    Extraction states what the LAW requires; a verdict about anybody's
    #    compliance is a different kind of claim and belongs to a run.
    if re.search(r'\b(?:covered|not covered|complies|compliant|gap|adequate|'
                 r'satisfies|meets the requirement)\b', text, re.IGNORECASE):
        return False, 'reads as a coverage verdict, not a requirement'

    # 4. the statement must follow from its own quote. Reuses the NLI scorer the
    #    comparison pipeline already uses for grounding, rather than a second
    #    unrelated notion of support.
    if nli is not None:
        try:
            risk = float(nli(text, quote))
        except Exception:
            logger.debug('NLI check failed; falling back to structural only',
                         exc_info=True)
            risk = 0.0
        if risk > _MAX_UNSUPPORTED:
            return False, f'not supported by its quote (risk {risk:.2f})'

    return True, ''


def extract_from_chunk(chunk: dict, *, nli=None, chat=None) -> tuple[list[dict], list[str]]:
    """Extract verified requirements from ONE regulatory chunk.

    Returns (accepted, rejections). Rejections are returned rather than logged
    away so a caller can report how much model output was refused — silent
    rejection would make a broken prompt look like a quiet provision.
    """
    body = (chunk.get('content') or '').strip()
    if not body:
        return [], []
    ref = (chunk.get('article_ref') or '').strip()
    chat = chat or _chat_json

    prompt = (_EXTRACT_PROMPT
              .replace('{body}', body)
              .replace('{ref}', f' ({ref})' if ref else ''))
    data = chat(prompt, MODEL)

    if not isinstance(data, dict):
        return [], ['model returned a non-object']
    items = data.get('requirements')
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return [], ['model returned no "requirements" array']

    accepted, rejected = [], []
    seen: set = set()
    for raw in items:
        ok, why = verify_candidate(raw, body, nli=nli)
        if not ok:
            rejected.append(why)
            continue
        text = (raw.get('requirement_text') or '').strip()
        if _norm(text) in seen:            # same obligation twice in one reply
            rejected.append('duplicate within the same chunk')
            continue
        seen.add(_norm(text))
        sev = (raw.get('inherent_severity') or '').strip().lower()
        topics = raw.get('topics') or []
        if isinstance(topics, str):
            topics = [topics]
        accepted.append({
            'text':              text,
            'title':             text[:300],
            'article_ref':       ref,
            'source_chunk_id':   chunk.get('node_id') or '',
            'source_quote':      (raw.get('source_quote') or '').strip(),
            'applicability':     (raw.get('applicability') or '').strip(),
            'inherent_severity': sev if sev in _SEVERITIES else None,
            'topics':            [str(t).strip().lower() for t in topics if str(t).strip()][:3],
            'extraction_model':  MODEL,
        })
    return accepted, rejected
