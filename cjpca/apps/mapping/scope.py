"""Whole-corpus scope service for results-first policy coverage.

The old flow asked the analyst to hand-pick regulations, then checked the
policy against everything in them. This derives scope instead: a policy
section only needs checking against a provision that legislates on the SAME
taxonomy topic. Everything else is noise and is never queued.

`compute_scope(policy_doc, jurisdictions=None)` returns a `Scope` with:
  - `pairs`   — the (policy_section, provision, topic) triples worth mapping
  - `summary` — the headline numbers the coverage page leads with

`skipped` is first-class. A policy topic that no in-scope regulation
legislates on is reported as *skipped*, never as a gap. Conflating "no law
addresses this" with "the policy fails to address a law" is the single most
damaging error this tool can make, so the two are kept structurally apart:
skipped topics come from `policy_topics - corpus_topics` and are excluded
from every gap tally downstream.

This module is pure metadata arithmetic over the chunk_tags side-table — it
runs no model and issues no retrieval, so it is safe to call inside a page
request to render the pre-run scope preview.
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_BASE = Path(__file__).resolve().parents[3]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from retrieval.bm25_store import BM25_DB_PATH, tagged_chunks_for_docs  # noqa: E402
from reasoning.taxonomy import TAXONOMY_VERSION, topic_label            # noqa: E402


@dataclass
class TopicScope:
    """One taxonomy topic and what the policy / corpus each say about it."""
    topic: str
    label: str
    policy_sections: list[dict] = field(default_factory=list)
    provisions: list[dict] = field(default_factory=list)

    @property
    def pair_count(self) -> int:
        return len(self.policy_sections) * len(self.provisions)


@dataclass
class ScopeSummary:
    policy_title: str
    jurisdictions: list[str]
    taxonomy_version: str
    # counts
    policy_sections_total: int      # every classified policy section
    provisions_total: int           # every classified corpus provision
    instruments: int                # distinct regulation documents in corpus
    topics_in_scope: int            # topics both sides legislate on
    topics_skipped: int             # policy topics no in-scope law addresses
    scoped_pairs: int               # pairs actually queued
    bruteforce_pairs: int           # naive sections x provisions
    classified: bool                # False if the policy has no tags yet

    @property
    def reduction_pct(self) -> float:
        if not self.bruteforce_pairs:
            return 0.0
        return round(100.0 * (1 - self.scoped_pairs / self.bruteforce_pairs), 1)


@dataclass
class Scope:
    summary: ScopeSummary
    topic_scopes: list[TopicScope]          # shared topics, most pairs first
    skipped_topics: list[tuple[str, str]]   # (topic, label) policy-only topics
    pairs: list[tuple[dict, dict, str]]     # (policy_section, provision, topic)


def _doc_chunk_counts(doc_titles: list[str]) -> dict[str, int]:
    """Raw bm25 chunk count per doc_title (tagged or not) — brute-force base."""
    if not BM25_DB_PATH.exists() or not doc_titles:
        return {}
    try:
        with sqlite3.connect(str(BM25_DB_PATH)) as conn:
            ph = ",".join("?" * len(doc_titles))
            rows = conn.execute(
                f"SELECT doc_title, COUNT(*) FROM bm25_index "
                f"WHERE doc_title IN ({ph}) GROUP BY doc_title", doc_titles,
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r[0]: r[1] for r in rows}


def _regulation_titles(jurisdictions: list[str] | None) -> list[str]:
    """Regulation doc_titles from the Django corpus (indexed regulations).

    Scoping by doc_title — not bm25's doc_type — is what the rest of the
    codebase does: bm25 stores doc_type as 'Regulatory'/'Internal Policy' and
    jurisdiction in title-case, so filtering bm25 on Django's 'regulation' /
    'bahrain' values silently matches nothing. Deriving titles from Django
    sidesteps both mismatches."""
    from apps.library.models import Document
    qs = Document.objects.filter(doc_type=Document.REGULATION, status=Document.INDEXED)
    if jurisdictions:
        qs = qs.filter(jurisdiction__in=[j.lower() for j in jurisdictions])
    return [d.chunk_doc_title for d in qs if d.chunk_doc_title]


def compute_scope(policy_doc, jurisdictions: list[str] | None = None) -> Scope:
    """Derive the mapping scope for one policy against the regulation corpus.

    `policy_doc` is a library.Document (doc_type='policy'); `jurisdictions`
    optionally restricts the corpus (defaults to all regulation jurisdictions).
    """
    policy_title = policy_doc.chunk_doc_title
    jl = [j for j in (jurisdictions or []) if j] or None

    reg_titles = _regulation_titles(jl)

    policy_rows = tagged_chunks_for_docs(doc_titles=[policy_title])
    corpus_rows = tagged_chunks_for_docs(doc_titles=reg_titles) if reg_titles else []

    pol_by_topic: dict[str, list[dict]] = defaultdict(list)
    reg_by_topic: dict[str, list[dict]] = defaultdict(list)
    for r in policy_rows:
        pol_by_topic[r["topic"]].append(r)
    for r in corpus_rows:
        reg_by_topic[r["topic"]].append(r)

    policy_topics = set(pol_by_topic)
    corpus_topics = set(reg_by_topic)
    shared = policy_topics & corpus_topics
    skipped = policy_topics - corpus_topics   # policy speaks, no law here → skipped

    topic_scopes: list[TopicScope] = []
    pairs: list[tuple[dict, dict, str]] = []
    for topic in shared:
        ts = TopicScope(
            topic=topic,
            label=topic_label(topic),
            policy_sections=pol_by_topic[topic],
            provisions=reg_by_topic[topic],
        )
        topic_scopes.append(ts)
        for pc in ts.policy_sections:
            for pr in ts.provisions:
                pairs.append((pc, pr, topic))
    topic_scopes.sort(key=lambda t: t.pair_count, reverse=True)

    skipped_topics = sorted(((t, topic_label(t)) for t in skipped), key=lambda x: x[1])

    reg_counts = _doc_chunk_counts(reg_titles)
    instruments = len([t for t in reg_titles if reg_counts.get(t)])
    policy_sections_total = _doc_chunk_counts([policy_title]).get(policy_title, 0)
    provisions_total = sum(reg_counts.values())

    summary = ScopeSummary(
        policy_title=policy_doc.name,
        jurisdictions=jl or [],
        taxonomy_version=TAXONOMY_VERSION,
        policy_sections_total=policy_sections_total,
        provisions_total=provisions_total,
        instruments=instruments,
        topics_in_scope=len(shared),
        topics_skipped=len(skipped),
        scoped_pairs=len(pairs),
        bruteforce_pairs=policy_sections_total * provisions_total,
        classified=bool(policy_rows),
    )

    return Scope(
        summary=summary,
        topic_scopes=topic_scopes,
        skipped_topics=skipped_topics,
        pairs=pairs,
    )
