"""Drive native requirement extraction for one regulation version.

Sits between the indexed chunks and the requirement store:

    regulation version
          ↓  chunks_for_doc            (indexed provisions, with text)
    candidate chunks                   (the chunker's own is_obligation signal)
          ↓  extract_from_chunk        (local model, regulation text only)
    verified candidates                (quote must occur in its chunk)
          ↓  ensure_requirements       (Build 1, unchanged)
    canonical Requirement rows

Nothing here touches the comparison pipeline. It reads a regulation and writes
requirements; no policy, no coverage, no gaps are visible to it, by construction
— the only input it ever assembles is one regulation's own chunk text.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def regulation_chunks(regulation) -> list[dict]:
    """The indexed chunks of this regulation, with their text.

    Keyed on `chunk_doc_title` — the FILE STEM the ingestion pipeline writes —
    not on the display `name`. They differ ("Bahrain PDPL Law 30 2018" vs
    "Bahrain_PDPL_Law_30_2018"), and filtering on `name` matches nothing, which
    surfaces as a run that completes having quietly extracted nothing. The
    Document property carries the same warning from a previous occurrence.
    """
    from retrieval.bm25_store import chunks_for_doc
    title = regulation.chunk_doc_title
    if not title:
        logger.warning('regulation %s has no file, so no indexed chunks', regulation.pk)
        return []
    rows = chunks_for_doc(title)
    if not rows:
        # Loud, because "no chunks" and "no obligations" look identical in the
        # output otherwise — an unindexed regulation must not read as a clean run.
        logger.warning('regulation %s (%r) has no indexed chunks — is it ingested?',
                       regulation.pk, title)
    return rows


def build_extractor(*, nli=None, chat=None, chunks=None, on_chunk=None):
    """Make an extractor callable for ensure_requirements.

    Everything the model-facing layer needs is injected, so a test can drive the
    whole path deterministically without Ollama, and so this module never
    reaches for anything policy-shaped.
    """
    from reasoning.requirement_extract import candidate_chunks, extract_from_chunk

    def extractor(regulation):
        source = chunks if chunks is not None else regulation_chunks(regulation)
        items: list[dict] = []
        for i, chunk in enumerate(candidate_chunks(source), 1):
            accepted, rejected = extract_from_chunk(chunk, nli=nli, chat=chat)
            if on_chunk:
                on_chunk(i, chunk, accepted, rejected)
            items.extend(accepted)
        return items

    return extractor


def extract_for_regulation(regulation, *, nli=None, chat=None,
                           chunks=None, dry_run=False) -> dict:
    """Extract and persist this regulation's canonical requirements. Idempotent.

    Returns a report. `migrated_overlap` lists chunks where a native requirement
    was produced from a chunk that already carries a migrated one: the migrated
    row is NEVER rewritten or deleted — the two coexist under different keys and
    the relationship is reported for a human to resolve. Silently replacing a
    grounded historical baseline with fresh model output is exactly the kind of
    quiet overwrite the store exists to prevent.
    """
    from apps.library.models import Requirement
    from apps.library.requirements import ensure_requirements

    source = chunks if chunks is not None else regulation_chunks(regulation)
    from reasoning.requirement_extract import candidate_chunks
    candidates = candidate_chunks(source)

    stats = {'rejected': 0, 'reasons': [], 'chunks_with_output': 0}

    def on_chunk(i, chunk, accepted, rejected):
        stats['rejected'] += len(rejected)
        stats['reasons'].extend(rejected)
        if accepted:
            stats['chunks_with_output'] += 1

    extractor = build_extractor(nli=nli, chat=chat, chunks=source, on_chunk=on_chunk)

    if dry_run:
        produced = extractor(regulation)
        existing_keys = set(
            Requirement.objects.filter(regulation=regulation)
            .values_list('key', flat=True))
        from apps.library.requirements import make_key
        would_create = [p for p in produced
                        if make_key(p['source_chunk_id'], p['text']) not in existing_keys]
        result = {'created': 0, 'existing': len(existing_keys), 'skipped': 0,
                  'would_create': len(would_create)}
    else:
        result = ensure_requirements(regulation, extractor=extractor)

    migrated_by_chunk = {
        r.source_chunk_id: r for r in
        Requirement.objects.filter(regulation=regulation,
                                   extraction_source=Requirement.MIGRATED)
    }
    native = Requirement.objects.filter(regulation=regulation,
                                        extraction_source=Requirement.LLM)
    overlap = [
        {'chunk': r.source_chunk_id,
         'migrated_requirement_id': migrated_by_chunk[r.source_chunk_id].pk,
         'native_requirement_id': r.pk,
         'native_text': r.text[:160]}
        for r in native if r.source_chunk_id in migrated_by_chunk
    ]

    return {
        **result,
        'total_chunks':        len(source),
        'candidate_chunks':    len(candidates),
        'chunks_with_output':  stats['chunks_with_output'],
        'rejected_candidates': stats['rejected'],
        'rejection_reasons':   stats['reasons'],
        'migrated_overlap':    overlap,
    }
