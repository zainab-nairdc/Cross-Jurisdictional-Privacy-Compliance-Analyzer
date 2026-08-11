"""Canonical requirement identity and extraction.

Requirements are persistent knowledge about a regulation; analysis runs are
observations about a policy. This module owns the first half — deriving stable
identities for requirements and making sure a regulation has its set, once.

Nothing here participates in comparison. It does not see policies, does not
produce verdicts, and is never called from the draft/verify/correct loop.
"""

from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)


def _normalise(text: str) -> str:
    """Collapse a quote to its comparable core.

    Whitespace and case vary between extractions of the same provision without
    changing what it says, so they must not change the identity either.
    """
    return re.sub(r'\s+', ' ', (text or '')).strip().lower()


def make_key(source_chunk_id: str, text: str = '') -> str:
    """Deterministic identity for a requirement within one regulation.

    Two modes, both repeatable:

    - `text` omitted — the key identifies the SOURCE CHUNK. This is what the
      backfill uses: rebuilding history, one canonical requirement per chunk a
      past run cited, which asserts only what the chunk grounds and invents no
      semantic split.
    - `text` given — the key identifies this particular obligation within the
      chunk, so a provision that genuinely imposes several can record several.

    The regulation is not mixed in: uniqueness is (regulation, key), so the same
    provision in two versions of a law keeps the same key under two owners,
    which is what makes cross-version comparison possible later.
    """
    basis = (f'chunk:{source_chunk_id}' if not text
             else f'chunk:{source_chunk_id}|{_normalise(text)}')
    return hashlib.sha1(basis.encode('utf-8')).hexdigest()[:40]


def ensure_requirements(regulation, *, extractor=None) -> dict:
    """Make sure `regulation` has its canonical requirement set. Idempotent.

    Called before a run needs them. The FIRST call for a regulation extracts and
    persists; every later call is a no-op that returns the existing set, which
    is what makes two analyses of the same regulation share one requirement set
    instead of minting unrelated obligations each time.

    Extraction is deliberately a separate pass, not part of comparison: it looks
    only at the regulation, so its result is a property of the document rather
    than of whatever policy happened to be analysed alongside it.

    `extractor` is an optional callable(regulation) -> list of dicts with keys
    text / title / article_ref / source_chunk_id / source_quote / topics. It is
    injectable so this can be driven by the obligation-bearing chunks, by the
    local model, or by a test, without this function knowing which.

    Returns {'created': n, 'existing': n, 'skipped': n}.
    """
    from apps.library.models import Requirement

    existing = {r.key: r for r in
                Requirement.objects.filter(regulation=regulation)}
    if extractor is None:
        # No extractor: report what is already stored rather than guessing.
        return {'created': 0, 'existing': len(existing), 'skipped': 0}

    created = skipped = 0
    for item in extractor(regulation) or []:
        text  = (item.get('text') or '').strip()
        chunk = (item.get('source_chunk_id') or '').strip()
        # A requirement with no text says nothing, and one with no source chunk
        # cannot be traced back to the regulation that produced it. Either way
        # it is not admissible — skipped and counted, never invented.
        if not text or not chunk:
            skipped += 1
            continue
        key = make_key(chunk, text)
        if key in existing:
            continue
        Requirement.objects.create(
            regulation        = regulation,
            key               = key,
            text              = text,
            title             = (item.get('title') or text)[:300],
            article_ref       = (item.get('article_ref') or '')[:100],
            source_chunk_id   = chunk[:64],
            source_quote      = item.get('source_quote') or '',
            topics            = item.get('topics') or [],
            applicability     = (item.get('applicability') or '')[:200],
            scope_note        = item.get('scope_note') or '',
            inherent_severity = item.get('inherent_severity') or None,
            extraction_source = Requirement.LLM,
            extraction_model  = item.get('extraction_model') or '',
        )
        existing[key] = None
        created += 1

    return {'created': created,
            'existing': len(existing) - created,
            'skipped': skipped}
