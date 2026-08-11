"""Drive v2 extraction for one regulation version.

Mirrors apps.library.extraction (v1) but runs the two-stage pipeline and stamps
`extraction_model = "qwen2.5:7b/v2"`. v1 rows are never touched: a v2 rule is
worded differently, so make_key(chunk, text) yields a different key and the two
coexist. Overlaps are reported, never resolved silently.

Regulation side only — no policy text, no coverage, no gaps reach this code.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def extract_for_regulation(regulation, *, chat=None, chunks=None,
                           dry_run=True, on_chunk=None) -> dict:
    """Run v2 over a regulation. Dry run by DEFAULT — the opposite of v1's
    signature, because v2 is an evaluation tool until it is shown to be better.
    """
    from apps.library.models import Requirement
    from apps.library.requirements import ensure_requirements, make_key
    from apps.library.extraction import regulation_chunks
    from reasoning.requirement_extract_v2 import (
        extract_from_chunk, is_obligation_text, EXTRACTOR_VERSION,
    )

    source = chunks if chunks is not None else regulation_chunks(regulation)
    candidates = [c for c in source if is_obligation_text(c.get('content') or '')]

    produced: list[dict] = []
    rejections: list[str] = []
    per_chunk: dict = {}
    for i, ch in enumerate(candidates, 1):
        acc, rej = extract_from_chunk(ch, chat=chat)
        produced.extend(acc)
        rejections.extend(rej)
        per_chunk[ch.get('node_id')] = {'accepted': len(acc), 'rejected': len(rej),
                                        'article_ref': ch.get('article_ref', '')}
        if on_chunk:
            on_chunk(i, len(candidates), ch, acc, rej)

    # Duplicate keys within this run (same rule from the same chunk twice).
    keys = [make_key(p['source_chunk_id'], p['text']) for p in produced]
    duplicates = len(keys) - len(set(keys))

    existing = {
        r.key: r for r in Requirement.objects.filter(regulation=regulation)
    }
    by_chunk: dict = {}
    for r in Requirement.objects.filter(regulation=regulation):
        by_chunk.setdefault(r.source_chunk_id, []).append(r)

    new_keys = [k for k in set(keys) if k not in existing]
    overlap = [
        {'chunk': p['source_chunk_id'],
         'v2_text': p['text'][:120],
         'existing': [{'id': r.pk, 'source': r.extraction_source,
                       'text': r.text[:90]}
                      for r in by_chunk.get(p['source_chunk_id'], [])]}
        for p in produced if by_chunk.get(p['source_chunk_id'])
    ]

    created = 0
    if not dry_run:
        # Persist via the SAME store entry point v1 uses; nothing about the
        # schema or the key mechanism changes for v2.
        res = ensure_requirements(
            regulation, extractor=lambda _r: produced)
        created = res['created']

    return {
        'extractor':           EXTRACTOR_VERSION,
        'total_chunks':        len(source),
        'candidate_chunks':    len(candidates),
        'produced':            len(produced),
        'unique_keys':         len(set(keys)),
        'duplicates':          duplicates,
        'would_create':        len(new_keys),
        'created':             created,
        'rejected':            len(rejections),
        'rejection_reasons':   rejections,
        'overlap':             overlap,
        'per_chunk':           per_chunk,
        'requirements':        produced,
    }
