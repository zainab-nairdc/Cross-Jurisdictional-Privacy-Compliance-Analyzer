"""Resolution and persistence of requirement cross-references.

Detection lives in `reasoning.legal_refs` and is pure. This module is the half
that needs the corpus: it builds an article index from the indexed chunks,
decides what a detected reference actually points at, and writes the outcome.

The governing rule, applied at every branch below:

    NEVER GUESS A TARGET.

A wrong cross-reference is worse than a missing one. A missing link is visibly
missing; a wrong link is invisible false traceability that a reviewer has no
way to audit. So the resolver reaches `resolved` only when exactly one chunk
can be named, and everything else is recorded honestly as `ambiguous` (with
every candidate listed) or `unresolved` (with a reason).

Two conflations this module deliberately refuses to make:

  - one article is NOT one chunk. Clause-chunking splits a single article
    across several chunks, and GDPR "Article (4)" is ten of them in the live
    index. Picking one would be a coin flip, so the reference goes `ambiguous`
    carrying all ten.
  - identifying the target DOCUMENT is NOT resolving the target PROVISION.
    Knowing a reference points into Law No. 30 of 2018 is a weaker claim than
    knowing which article it lands on, and the two are stored separately.
"""

from __future__ import annotations

import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

_BASE = Path(__file__).resolve().parents[3]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from reasoning.legal_refs import (                                # noqa: E402
    KIND_ARTICLE, KIND_LAW, KIND_SECTION, REL_FOLLOWING, REL_PRECEDING,
    REL_SELF, SCOPE_EXTERNAL, SCOPE_INTERNAL, SCOPE_UNKNOWN,
    article_number_of, detect_references,
)

logger = logging.getLogger(__name__)


# Kinds that can be looked up in the article index. A bare "paragraph 4" or
# "Schedule 2" is deliberately absent: the index is built from article/section
# headings, and a paragraph reference with no article attached does not name a
# provision anyone could follow deterministically. Detected, never resolved —
# see _resolve_one.
_INDEXABLE_KINDS = (KIND_ARTICLE, KIND_SECTION)


class ArticleIndex:
    """article number -> the chunks filed under it, for one document.

    Built from `bm25_index.article_ref`, the same stored metadata the coverage
    UI cites, so a resolved reference points at a chunk the rest of the system
    already knows how to render and deep-link.

    Chunks whose heading carries no number ("Preamble", "First Article",
    "CHAPTER XIII - MISCELLANEOUS") are simply absent. That is correct: nothing
    can cite them by number, so they must never become a resolution target.
    """

    def __init__(self, doc_title: str = "", rows: list[dict] | None = None):
        self.doc_title = doc_title
        self._by_number: dict[str, list[str]] = defaultdict(list)
        self._content: dict[str, str] = {}
        self._article_of_chunk: dict[str, str] = {}
        for row in rows or []:
            node_id = row.get("node_id") or ""
            if not node_id:
                continue
            self._content[node_id] = row.get("content") or ""
            number = article_number_of(row.get("article_ref") or "")
            if number:
                self._by_number[number].append(node_id)
                self._article_of_chunk[node_id] = number

    @classmethod
    def for_document(cls, doc_title: str) -> "ArticleIndex":
        from retrieval.bm25_store import chunks_for_doc
        if not doc_title:
            return cls("")
        return cls(doc_title, chunks_for_doc(doc_title))

    def chunks_for(self, number: str) -> list[str]:
        return list(self._by_number.get(number, []))

    def content_of(self, node_id: str) -> str:
        return self._content.get(node_id, "")

    def article_of(self, node_id: str) -> str:
        """The article number a chunk sits under, or ''."""
        return self._article_of_chunk.get(node_id, "")

    def numbers(self) -> list[str]:
        return list(self._by_number)

    def __bool__(self) -> bool:
        return bool(self._by_number)


def _subsection_marker(sub: str) -> re.Pattern:
    """Anchored matcher for an enumerated sub-clause marker.

    Anchored to a line start or sentence boundary, the same idiom the v2
    extractor uses to segment clauses, so a numeral inside a sentence ("within
    2 working days") cannot masquerade as clause (2). Narrowing has to be
    deterministic to be allowed at all — a loose substring search here would
    reintroduce exactly the guessing this module exists to prevent.
    """
    esc = re.escape(sub)
    return re.compile(
        r"(?:(?<=^)|(?<=[.;:])|(?<=\n))\s*\(?\s*" + esc + r"\s*\)?\s*[.)\-]\s",
        re.MULTILINE)


def _narrow_by_subsection(candidates: list[str], sub: str,
                          index: ArticleIndex) -> list[str]:
    """Candidates whose text actually carries the cited sub-clause marker.

    Returns the input unchanged when narrowing finds nothing or stays
    ambiguous — a failed narrowing must not silently shrink the candidate set,
    because that would drop real targets to manufacture a clean answer.
    """
    if not sub or len(candidates) < 2:
        return candidates
    marker = _subsection_marker(sub)
    hits = [c for c in candidates if marker.search(index.content_of(c) or "")]
    return hits if len(hits) == 1 else candidates


def find_document_for_citation(ref) -> object | None:
    """The Document a detected instrument citation names, or None.

    Two matching routes, both requiring an UNAMBIGUOUS hit:
      - `Document.document_id` equality (GDPR really is stored as "2016/679",
        so "Regulation (EU) 2016/679" lands on it directly)
      - law number AND year both present in the document's name

    Returns None whenever two or more documents match. A citation matching
    several documents is not a resolution, and picking one would be exactly
    the kind of plausible-looking error that is unauditable later.
    """
    from apps.library.models import Document

    code = (ref.law_number or "").strip()
    year = (ref.law_year or "").strip()
    if not code:
        return None

    hits = list(Document.objects.filter(document_id__iexact=code)[:3])
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return None

    if not year:
        return None
    # Both the number and the year must appear in the name. Either alone
    # matches far too much ("2018" hits every 2018 instrument).
    hits = list(Document.objects.filter(name__contains=code)
                .filter(name__contains=year)[:3])
    return hits[0] if len(hits) == 1 else None


def _target_numbers(ref, source_article: str) -> tuple[list[str], str]:
    """The article number(s) a reference designates, plus a note when it can't.

    Relative references are resolved ONLY by deterministic arithmetic on the
    source article's own number. When the requirement's own article is unknown
    — an unnumbered heading, a policy section — there is nothing to count from
    and the reference stays unresolved rather than being pointed at a plausible
    neighbour.
    """
    rel = ref.relative_kind
    if rel:
        if not source_article:
            return [], 'relative reference but the source article is unnumbered'
        if rel == REL_SELF:
            return [source_article], ''
        if not source_article.isdigit():
            return [], (f'relative reference from non-numeric article '
                        f'{source_article!r}')
        n = int(source_article)
        if rel == REL_PRECEDING:
            if n <= 1:
                return [], 'no preceding article before article 1'
            return [str(n - 1)], ''
        return [str(n + 1)], ''

    if ref.is_range:
        bounds = ref.range_bounds()
        if not bounds:
            return [], 'range bounds could not be parsed'
        lo, hi = bounds
        return [str(n) for n in range(lo, hi + 1)], ''

    base = ref.base_number
    return ([base], '') if base else ([], 'reference carries no number')


def _resolve_one(ref, *, regulation, home_index: ArticleIndex,
                 source_article: str) -> dict:
    """Decide what one detected reference points at.

    Returns the resolution fields as a dict. Never raises: a resolver that
    threw would take down the detection pass for a whole regulation, and the
    reference record is more valuable than any single resolution.
    """
    from apps.library.models import RequirementReference as RR

    out = {
        'status':          RR.UNRESOLVED,
        'scope':           ref.scope,
        'target_chunk_id': '',
        'target_document': None,
        'target_doc_code': '',
        'candidates':      [],
        'resolution_note': '',
    }

    # ── which document does this land in? ──
    index = home_index
    if ref.scope == SCOPE_EXTERNAL:
        doc = find_document_for_citation(ref)
        if doc is None:
            out['resolution_note'] = 'external instrument not matched to a known document'
            return out
        out['target_document'] = doc
        out['target_doc_code'] = doc.document_id or ''
        index = ArticleIndex.for_document(doc.chunk_doc_title)
        if not index:
            # The document is known but not indexed, so no provision inside it
            # can be named. Document-level identification is NOT provision-level
            # resolution, and this is where the two are kept apart.
            out['resolution_note'] = (
                f'target document {doc.name!r} identified but has no indexed '
                f'provisions')
            return out
    else:
        out['target_document'] = regulation
        out['target_doc_code'] = getattr(regulation, 'document_id', '') or ''

    # ── a bare instrument reference names no provision ──
    if ref.ref_kind == KIND_LAW:
        out['resolution_note'] = (
            'reference names an instrument, not a provision')
        return out

    if ref.ref_kind not in _INDEXABLE_KINDS and not ref.relative_kind:
        # "paragraph 4" / "Schedule 2" with no article attached. The paragraph
        # probably belongs to the enclosing article, but probably is not
        # deterministic, and the index holds articles rather than paragraphs.
        #
        # A RELATIVE paragraph is different and is allowed through: "Paragraph
        # (1) of this Article" states which article it means, so the target
        # follows from position rather than from inference.
        out['resolution_note'] = (
            f'{ref.ref_kind} references are not resolvable from the article index')
        return out

    numbers, why = _target_numbers(ref, source_article)
    if not numbers:
        out['resolution_note'] = why or 'no target number'
        return out

    # ── look the target(s) up ──
    found: list[str] = []
    missing: list[str] = []
    for number in numbers:
        hits = index.chunks_for(number)
        if hits:
            found.extend(hits)
        else:
            missing.append(number)

    if not found:
        out['resolution_note'] = (
            f'no indexed provision for {", ".join(numbers)} in '
            f'{index.doc_title or "the target document"}')
        return out

    if missing:
        # A range where only part of the span exists. Reporting this resolved
        # would assert coverage of provisions that are not in the corpus.
        out['status']     = RR.UNRESOLVED
        out['candidates'] = found
        out['resolution_note'] = (
            f'{len(missing)} of {len(numbers)} referenced provisions are not '
            f'indexed ({", ".join(missing[:5])})')
        if ref.scope == SCOPE_UNKNOWN:
            out['scope'] = SCOPE_INTERNAL
        return out

    if ref.subsection:
        found = _narrow_by_subsection(found, ref.subsection, index)

    if ref.scope == SCOPE_UNKNOWN:
        # It resolved inside this document, so "unknown" can be upgraded to a
        # fact rather than remaining an assumption.
        out['scope'] = SCOPE_INTERNAL

    if len(found) == 1:
        out['status']          = RR.RESOLVED
        out['target_chunk_id'] = found[0]
        out['candidates']      = []
        out['resolution_note'] = f'resolved to a single provision chunk'
        return out

    out['status']     = RR.AMBIGUOUS
    out['candidates'] = found
    out['resolution_note'] = (
        f'{len(found)} candidate chunks; the reference does not designate '
        f'exactly one')
    return out


def detect_for_requirement(requirement, *, home_index: ArticleIndex,
                           regulation=None) -> list[dict]:
    """Detect + resolve every reference carried by one requirement.

    Reads `source_quote` — the verbatim provision text — rather than `text`,
    the model's restatement. The restatement is a paraphrase and may have
    dropped or reworded the citation; the quote is what the law actually says,
    and a cross-reference must come from the law.
    """
    reg = regulation if regulation is not None else requirement.regulation
    quote = (requirement.source_quote or '').strip()
    if not quote:
        return []

    source_article = article_number_of(requirement.article_ref or '')
    if not source_article and requirement.source_chunk_id:
        # Fall back to the chunk's own heading — a requirement may carry no
        # article_ref of its own while its source chunk does.
        source_article = home_index.article_of(requirement.source_chunk_id)

    rows: list[dict] = []
    # A quote may cite the same provision twice ("...under Article 5 ... as
    # Article 5 provides"), and "this Law" appears repeatedly in nearly every
    # Bahrain provision. Those are ONE reference each. Collapsed here rather
    # than left to the uniqueness constraint, so a dry run reports the number
    # of rows that would actually be written instead of the number of textual
    # occurrences — otherwise --dry-run and --apply disagree on the count.
    # Case-insensitive, because "this Law" and "this law" are the same
    # reference; the FIRST occurrence's verbatim wording is what is kept.
    seen: set = set()
    for ref in detect_references(quote):
        dedupe_key = (ref.ref_kind, ref.ref_number, ref.ref_text.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        try:
            resolution = _resolve_one(
                ref, regulation=reg, home_index=home_index,
                source_article=source_article)
        except Exception:
            logger.exception('resolution failed for %r on requirement %s',
                             ref.ref_text, requirement.pk)
            resolution = {'status': 'unresolved', 'scope': ref.scope,
                          'target_chunk_id': '', 'target_document': None,
                          'target_doc_code': '', 'candidates': [],
                          'resolution_note': 'resolver error'}
        rows.append({
            'ref_text':    ref.ref_text[:300],
            'ref_kind':    ref.ref_kind,
            'ref_number':  ref.ref_number,
            'confidence':  ref.confidence,
            'detected_by': ref.detected_by,
            **resolution,
        })
    return rows


def detect_references_for_regulation(regulation, *, dry_run: bool = True,
                                     prune: bool = False) -> dict:
    """Detect + resolve references for every requirement of one regulation.

    Dry run by DEFAULT, matching `extract_requirements`: this is derived data
    built by a heuristic, and writing it should be a decision rather than a
    side effect of looking.

    Idempotent. Rows are keyed on (requirement, ref_kind, ref_number, ref_text)
    — all fixed at detection — so a re-run refreshes the resolution of an
    existing reference instead of filing a duplicate. `prune` additionally
    drops regex-detected rows that the current detector no longer produces;
    off by default, and it never touches rows recorded by any other means.
    """
    from apps.library.models import Requirement, RequirementReference as RR

    requirements = list(Requirement.objects.filter(regulation=regulation))
    report = {
        'regulation':   regulation.name,
        'requirements': len(requirements),
        'detected': 0, 'resolved': 0, 'ambiguous': 0, 'unresolved': 0,
        'created': 0, 'updated': 0, 'pruned': 0,
        'by_kind': defaultdict(int), 'by_scope': defaultdict(int),
        'samples': [], 'dry_run': dry_run,
        'indexed_articles': 0,
    }
    if not requirements:
        return report

    home_index = ArticleIndex.for_document(regulation.chunk_doc_title)
    report['indexed_articles'] = len(home_index.numbers())

    for req in requirements:
        rows = detect_for_requirement(req, home_index=home_index,
                                      regulation=regulation)
        seen_keys = []
        for row in rows:
            report['detected'] += 1
            report[row['status']] = report.get(row['status'], 0) + 1
            report['by_kind'][row['ref_kind']] += 1
            report['by_scope'][row['scope']] += 1
            if len(report['samples']) < 15:
                report['samples'].append({
                    'requirement': req.pk,
                    'article_ref': req.article_ref,
                    'ref_text':    row['ref_text'],
                    'ref_number':  row['ref_number'],
                    'status':      row['status'],
                    'scope':       row['scope'],
                    'note':        row['resolution_note'],
                    'candidates':  len(row['candidates']),
                })
            key = (row['ref_kind'], row['ref_number'], row['ref_text'])
            seen_keys.append(key)

            if dry_run:
                continue
            _, created = RR.objects.update_or_create(
                requirement = req,
                ref_kind    = row['ref_kind'],
                ref_number  = row['ref_number'],
                ref_text    = row['ref_text'],
                defaults = {
                    'scope':           row['scope'],
                    'status':          row['status'],
                    'target_chunk_id': row['target_chunk_id'],
                    'target_document': row['target_document'],
                    'target_doc_code': row['target_doc_code'],
                    'candidates':      row['candidates'],
                    'confidence':      row['confidence'],
                    'detected_by':     row['detected_by'],
                    'resolution_note': row['resolution_note'][:300],
                },
            )
            report['created' if created else 'updated'] += 1

        if not dry_run and prune:
            stale = RR.objects.filter(requirement=req, detected_by=RR.REGEX)
            for existing in stale:
                if (existing.ref_kind, existing.ref_number,
                        existing.ref_text) not in seen_keys:
                    existing.delete()
                    report['pruned'] += 1

    report['by_kind']  = dict(report['by_kind'])
    report['by_scope'] = dict(report['by_scope'])
    return report
