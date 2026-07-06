"""LLM-driven per-document topic classification.

Sets ``Document.cached_topics`` to a short list of taxonomy topics that best
describe each document. The result is what the UI renders as "sticker"
badges on doc cards across the library / comparison / mapping pages, so
users can see at a glance what subject matter a regulation covers rather
than parsing opaque file stems like ``Bahrain_PDPA_Order_43_2022``.

Method: for each Document, pull a chunk-ordered sample from BM25, send it
to Claude Haiku 4.5 with the controlled taxonomy vocabulary, and ask for
the top three topics. The LLM may only pick existing taxonomy tags — any
invented tag is rejected. Topics are stored as
``[{"id": "<tag>", "label": "<human label>"}, ...]`` to match the
``cached_topics`` shape the regulations/policies templates already consume.

Usage:
    python manage.py classify_doc_topics                   # all docs
    python manage.py classify_doc_topics --limit 5         # first 5
    python manage.py classify_doc_topics --jurisdiction bahrain
    python manage.py classify_doc_topics --force           # re-classify even if cached

Cost: ~$0.01 per doc at Haiku pricing. ~31 regulation docs => ~$0.30.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand

_BASE = Path(__file__).resolve().parents[5]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from retrieval.bm25_store import search_bm25                # noqa: E402
from reasoning            import taxonomy                   # noqa: E402
from reasoning.generator  import _get_llm                   # noqa: E402


PROMPT = """You are tagging a legal/regulatory document with the topics it covers.

DOCUMENT: {doc_title}
JURISDICTION: {jurisdiction}

Below are excerpts from this document, in document order:

{chunks}

Pick the THREE top-level topics that most accurately describe what this
document is about overall. You may ONLY choose from this controlled list
of top-level topic tags (lowercase, snake_case):

{topic_listing}

Output ONE JSON object — no prose, no markdown fences:

{{
  "topics": ["<topic_tag>", "<topic_tag>", "<topic_tag>"]
}}

Rules:
- Use ONLY the exact top-level tags above. Do NOT include a `/subcategory`
  suffix. e.g. write `security` not `security/technical_measures`.
- Pick topics that describe the document's PRIMARY subject matter, not
  every topic that gets a passing mention.
- If the document is narrowly scoped (e.g. a breach-notification order),
  it is fine to return fewer than three topics. Do not pad.
- Never invent a tag that is not in the list above.
"""


def _top_level_topic_listing() -> str:
    return '\n'.join(f'  - {tag} — {label}' for tag, label in taxonomy.all_topics())


def _gather_chunks(doc_title: str, jurisdiction: str, max_chunks: int = 60) -> list[dict]:
    rows = search_bm25(
        'the', top_k=max_chunks * 2,
        jurisdiction=jurisdiction, doc_title=doc_title,
    )
    rows.sort(key=lambda c: int(c.get('metadata', {}).get('chunk_index') or 0))
    return rows[:max_chunks]


def _format_chunks(chunks: list[dict], budget_chars: int = 30_000) -> str:
    parts: list[str] = []
    total = 0
    for i, c in enumerate(chunks, 1):
        body = (c.get('content') or '').strip()[:800]
        block = f'[Chunk {i}] {body}'
        if total + len(block) > budget_chars:
            parts.append('... [more chunks truncated]')
            break
        parts.append(block)
        total += len(block)
    return '\n\n'.join(parts)


def _parse_topics(text: str) -> list[str]:
    if not text:
        return []
    cleaned = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    s = cleaned.find('{')
    e = cleaned.rfind('}')
    if s == -1 or e <= s:
        return []
    try:
        payload = json.loads(cleaned[s:e + 1])
    except json.JSONDecodeError:
        return []
    raw = payload.get('topics') or []
    out: list[str] = []
    for t in raw:
        if not isinstance(t, str):
            continue
        tag = t.strip().lower().split('/', 1)[0]   # tolerate "topic/sub"
        if tag:
            out.append(tag)
    return out


def _validate(tags: list[str]) -> list[dict]:
    """Drop unknown tags (anti-hallucination); render to UI-ready dicts."""
    out: list[dict] = []
    seen: set[str] = set()
    for tag in tags:
        if tag in seen or not taxonomy.is_valid(tag):
            continue
        seen.add(tag)
        out.append({'id': tag, 'label': taxonomy.topic_label(tag)})
    return out[:3]


async def _classify_one(doc, debug: bool = False) -> list[dict]:
    title = getattr(doc, 'chunk_doc_title', '') or doc.name
    jurisdiction = doc.get_jurisdiction_display() if doc.jurisdiction else ''
    chunks = _gather_chunks(title, jurisdiction)
    if debug:
        print(f'    [debug] title={title!r}  jur={jurisdiction!r}  chunks={len(chunks)}')
    if not chunks:
        return []

    prompt = PROMPT.format(
        doc_title=doc.full_name or doc.name,
        jurisdiction=jurisdiction or '—',
        chunks=_format_chunks(chunks),
        topic_listing=_top_level_topic_listing(),
    )

    llm = _get_llm()
    try:
        resp = await llm.ainvoke(prompt)
        text = resp.content if hasattr(resp, 'content') else str(resp)
    except Exception as e:
        print(f'    LLM error: {type(e).__name__}: {str(e)[:120]}')
        return []

    if debug:
        print(f'    [debug] LLM response: {text[:200]!r}')
    return _validate(_parse_topics(text))


class Command(BaseCommand):
    help = 'LLM-driven topic stickers for documents (writes Document.cached_topics).'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None,
                            help='Only process the first N documents.')
        parser.add_argument('--jurisdiction', default=None,
                            help='Restrict to one jurisdiction (e.g. bahrain).')
        parser.add_argument('--force', action='store_true',
                            help='Re-classify even if cached_topics already set.')
        parser.add_argument('--doc-type', default=None,
                            choices=['regulation', 'policy'],
                            help='Restrict to regulations or policies.')
        parser.add_argument('--debug', action='store_true',
                            help='Print chunk count and raw LLM response per doc.')

    def handle(self, *args, **opts):
        from apps.library.models import Document

        qs = Document.objects.all().order_by('jurisdiction', 'name')
        if opts['jurisdiction']:
            qs = qs.filter(jurisdiction=opts['jurisdiction'])
        if opts['doc_type']:
            qs = qs.filter(doc_type=opts['doc_type'])
        if not opts['force']:
            qs = qs.exclude(cached_topics__contains=[{'id': 'security'}])  # cheap heuristic: skip if already structured
        docs = list(qs)
        if opts['limit']:
            docs = docs[:opts['limit']]

        self.stdout.write(f'Classifying {len(docs)} document(s)...\n')

        per_jur: dict[str, int] = {}
        t0 = time.time()
        for i, doc in enumerate(docs, 1):
            existing = doc.cached_topics or []
            is_structured = bool(existing) and isinstance(existing[0], dict)
            if is_structured and not opts['force']:
                self.stdout.write(f'  [{i:2d}/{len(docs)}] {doc.name[:60]:60s}  SKIP (cached)')
                continue

            self.stdout.write(f'  [{i:2d}/{len(docs)}] {doc.name[:60]:60s}', ending=' ')
            self.stdout.flush()

            topics = asyncio.run(_classify_one(doc, debug=opts['debug']))

            doc.cached_topics = topics
            doc.save(update_fields=['cached_topics'])

            labels = ', '.join(t['label'] for t in topics) or '(none)'
            self.stdout.write(f'-> {labels}')
            per_jur[doc.jurisdiction or 'unknown'] = per_jur.get(doc.jurisdiction or 'unknown', 0) + 1

        dt = time.time() - t0
        self.stdout.write(self.style.SUCCESS(
            f'\nDone in {dt:.1f}s. Processed: {sum(per_jur.values())} '
            f'({", ".join(f"{j}={n}" for j, n in per_jur.items())})'
        ))
