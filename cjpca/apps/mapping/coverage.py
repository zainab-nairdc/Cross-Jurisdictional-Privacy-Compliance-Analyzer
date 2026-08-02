"""Coverage rollup for the results-first policy-coverage page.

Turns a completed MappingAnalysis into the shape the coverage page renders:
a per-topic rollup, a gaps-first findings list, and — kept structurally
separate — the topics that were *skipped* because no in-scope regulation
legislates on them. Skipped topics are never folded into the gap count.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from apps.mapping.models import MappingAnalysis, ObligationMapping
from reasoning.taxonomy import topic_label


@dataclass
class TopicRollup:
    topic: str
    label: str
    covered: int = 0
    partial: int = 0
    review: int = 0
    none: int = 0

    @property
    def total(self) -> int:
        return self.covered + self.partial + self.review + self.none

    @property
    def gap_count(self) -> int:
        return self.partial + self.review + self.none

    @property
    def state(self) -> str:
        """Worst-case rollup: any not-covered → gap; any partial/review →
        partial; otherwise covered."""
        if self.none:
            return 'gap'
        if self.partial or self.review:
            return 'partial'
        return 'covered'


@dataclass
class CoverageResult:
    analysis: MappingAnalysis
    topic_rollups: list = field(default_factory=list)   # list[TopicRollup]
    skipped: list = field(default_factory=list)         # [{topic,label,policy_chunks}]
    gaps: list = field(default_factory=list)            # ObligationMapping, gaps-first
    counts: dict = field(default_factory=dict)
    total: int = 0
    covered_equiv: float = 0.0

    @property
    def coverage_pct(self) -> int:
        if not self.total:
            return 0
        return round(self.covered_equiv / self.total * 100)


def build_coverage(analysis: MappingAnalysis) -> CoverageResult:
    """Roll a completed analysis up by topic + collect gaps and skipped topics."""
    mappings = list(
        analysis.obligation_mappings.select_related('regulation').all()
    )

    rollups: dict[str, TopicRollup] = {}

    def _bucket(topic_tag: str) -> TopicRollup:
        if topic_tag not in rollups:
            rollups[topic_tag] = TopicRollup(topic=topic_tag, label=topic_label(topic_tag))
        return rollups[topic_tag]

    counts = {'covered': 0, 'partial': 0, 'review': 0, 'none': 0}
    for m in mappings:
        counts[m.coverage] = counts.get(m.coverage, 0) + 1
        # A row may carry 0..n topics (auto-route stamps exactly one). Fall
        # back to a synthetic 'untagged' bucket so nothing is silently dropped.
        topics = m.topics or ['(untopiced)']
        for t in topics:
            b = _bucket(t)
            setattr(b, m.coverage, getattr(b, m.coverage) + 1)

    # Gaps first: everything not fully covered, most severe first.
    sev_order = {ObligationMapping.NONE: 0, ObligationMapping.PARTIAL: 1,
                 ObligationMapping.REVIEW: 2}
    gaps = sorted(
        [m for m in mappings if m.coverage != ObligationMapping.COVERED],
        key=lambda m: (sev_order.get(m.coverage, 3), -(m.confidence or 0)),
    )

    total = len(mappings)
    covered_equiv = counts['covered'] + 0.5 * counts['partial']

    # Topic rollups ordered: gaps first, then partial, then covered; within a
    # band, more obligations first.
    state_order = {'gap': 0, 'partial': 1, 'covered': 2}
    topic_rollups = sorted(
        rollups.values(),
        key=lambda r: (state_order.get(r.state, 3), -r.total),
    )

    return CoverageResult(
        analysis=analysis,
        topic_rollups=topic_rollups,
        skipped=list(analysis.skipped_topics or []),
        gaps=gaps,
        counts=counts,
        total=total,
        covered_equiv=covered_equiv,
    )
