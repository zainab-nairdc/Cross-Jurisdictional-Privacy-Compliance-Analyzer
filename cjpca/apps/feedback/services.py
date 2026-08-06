"""RAG feedback loop — services (feasibility).

The loop, in three steps:
  1. record_feedback()  — capture every reviewer decision as a FeedbackSignal.
  2. promote_to_gold()  — on approval, store the row as a reusable GoldExemplar.
  3. build_fewshot()    — retrieve gold for a topic and format it as prompt context
                          so future generations are steered by approved examples.

`capture_comparison_transition()` is the one call the reviewer view makes; it does
steps 1 and (on approve) 2 from a ComparisonResult.
"""

from __future__ import annotations


def _versions():
    try:
        from reasoning.taxonomy import TAXONOMY_VERSION
    except Exception:
        TAXONOMY_VERSION = ''
    try:
        from config import OLLAMA_MODEL
    except Exception:
        OLLAMA_MODEL = ''
    return TAXONOMY_VERSION, OLLAMA_MODEL


def record_feedback(*, kind, source_id, topic='', query='', before=None, after=None,
                    note='', actor=None, source_app='comparison'):
    from .models import FeedbackSignal
    tax, model = _versions()
    return FeedbackSignal.objects.create(
        kind=kind, source_app=source_app, source_id=source_id,
        topic=(topic or ''), query=(query or ''),
        before=(before or {}), after=(after or {}), note=(note or ''),
        actor=actor, taxonomy_version=tax, model_version=model,
    )


def promote_to_gold(*, topic, query='', reg_a='', reg_b='', payload,
                    approved_by=None, source_id=None):
    """Store an approved result as a gold exemplar. Idempotent per source row:
    re-approving the same result won't create duplicate exemplars."""
    from .models import GoldExemplar
    if source_id and GoldExemplar.objects.filter(source_id=source_id, active=True).exists():
        return None
    tax, _ = _versions()
    return GoldExemplar.objects.create(
        topic=topic, query=(query or ''), reg_a=(reg_a or ''), reg_b=(reg_b or ''),
        payload=(payload or {}), approved_by=approved_by, source_id=source_id,
        taxonomy_version=tax,
    )


def gold_for_topic(topic, k=3):
    from .models import GoldExemplar
    if not topic:
        return []
    return list(GoldExemplar.objects.filter(topic__iexact=topic, active=True)[:k])


def _label_to_tag(label):
    """Generation passes the human topic LABEL ('Lawful basis & consent') as the
    query, but gold is stored under the taxonomy TAG ('lawful_basis'). Resolve so
    the loop matches either way."""
    try:
        from reasoning.taxonomy import all_topics
        for tag, lab in all_topics():
            if lab.strip().lower() == str(label).strip().lower():
                return tag
    except Exception:
        pass
    return None


def build_fewshot(topic, k=3) -> str:
    """Format approved exemplars for a topic as a prompt block. Empty string when
    there is no approved feedback yet (so the prompt is unchanged on a cold start)."""
    ex = gold_for_topic(topic, k)
    if not ex:
        tag = _label_to_tag(topic)          # query may be the label, gold keyed by tag
        if tag and tag != topic:
            ex = gold_for_topic(tag, k)
    if not ex:
        return ''
    lines = []
    for e in ex:
        p = e.payload or {}
        verdict = p.get('equivalence') or p.get('relationship') or ''
        concl   = p.get('practical_conclusion') or ''
        pair    = f'{e.reg_a} vs {e.reg_b}'.strip(' vs')
        line = f'- [{e.topic}] {pair}: verdict "{verdict}"'
        if concl:
            line += f'; approved conclusion: "{concl}"'
        lines.append(line)
    return '\n'.join(lines)


def chunk_feedback_scores():
    """Net feedback per chunk_id, aggregated from all signals:
    approve -> +1 on the row's chunks, reject -> -1. This is the retrieval lever's
    memory — which chunks reviewers have blessed or rejected."""
    from .models import FeedbackSignal
    scores: dict[str, int] = {}
    for s in FeedbackSignal.objects.all().only('kind', 'before'):
        w = 1 if s.kind == 'approve' else (-1 if s.kind == 'reject' else 0)
        if not w:
            continue
        b = s.before or {}
        for key in ('chunk_id_a', 'chunk_id_b'):
            cid = b.get(key)
            if cid:
                scores[cid] = scores.get(cid, 0) + w
    return scores


def _node_chunk_id(n):
    node = getattr(n, 'node', n)
    meta = getattr(node, 'metadata', {}) or {}
    return (meta.get('node_id') or meta.get('chunk_id')
            or getattr(node, 'node_id', None) or getattr(node, 'id_', None))


def feedback_rerank(nodes, alpha=0.5, scores=None):
    """Re-order retrieved nodes by (normalised base score) + alpha * net-feedback.
    Base scores are min-max normalised to 0..1 within the candidate set so the
    feedback boost is meaningful regardless of the reranker's score scale, and
    bounded so it can't run away. Deterministic: a reviewer-approved chunk moves
    up, a rejected one moves down. Unchanged when there's no feedback (cold start)."""
    scores = chunk_feedback_scores() if scores is None else scores
    if not scores or not nodes:
        return nodes
    bases = [float(getattr(n, 'score', 0) or 0) for n in nodes]
    lo, hi = min(bases), max(bases)
    rng = (hi - lo) or 1.0

    def adjusted(n):
        base = (float(getattr(n, 'score', 0) or 0) - lo) / rng
        return base + alpha * scores.get(_node_chunk_id(n), 0)

    return sorted(nodes, key=adjusted, reverse=True)


def capture_comparison_transition(result, new_lifecycle, actor=None):
    """Called from the reviewer transition view. Records the decision and, on
    approval, promotes the row to a gold exemplar. Best-effort: never raises into
    the review flow."""
    try:
        kind = {'approved': 'approve', 'rejected': 'reject'}.get(new_lifecycle, 'modify')
        # Topic key: prefer a taxonomy tag if present, else the run's topic, else blank.
        topic = ''
        if getattr(result, 'principle_ids', None):
            topic = str(result.principle_ids[0])
        elif result.run_id and getattr(result.run, 'topics', None):
            topic = str(result.run.topics[0])
        reg_a = result.run.reg_a.name if result.run_id else ''
        reg_b = result.run.reg_b.name if result.run_id else ''
        query = f'{result.citation_a} vs {result.citation_b or "—"}'
        snapshot = {
            'equivalence':          result.relationship,
            'relationship':         result.relationship,
            'practical_conclusion': getattr(result, 'practical_conclusion', '') or '',
            'compliance_impact':    getattr(result, 'compliance_impact', '') or '',
            'shared_controls':      getattr(result, 'shared_controls', []) or [],
            'citation_a':           result.citation_a,
            'citation_b':           result.citation_b,
            'key_difference':       result.key_difference,
            # chunk ids drive the RETRIEVAL lever: approved chunks get boosted on
            # future retrievals, rejected chunks demoted.
            'chunk_id_a':           getattr(result, 'chunk_id_a', '') or '',
            'chunk_id_b':           getattr(result, 'chunk_id_b', '') or '',
        }
        sig = record_feedback(kind=kind, source_id=result.pk, topic=topic,
                              query=query, before=snapshot, actor=actor)
        if new_lifecycle == 'approved':
            promote_to_gold(topic=topic, query=query, reg_a=reg_a, reg_b=reg_b,
                            payload=snapshot, approved_by=actor, source_id=result.pk)
        return sig
    except Exception:
        import logging
        logging.getLogger(__name__).exception('capture_comparison_transition failed')
        return None
