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


# Signals carrying this marker in `before` are retained for audit but are
# EXCLUDED from retrieval scoring (see purge_document_learning(mode='keep')).
RETIRED_KEY = '_retired'


def chunk_feedback_scores(topic=None, version_scope=True):
    """Net feedback per chunk_id: approve -> +1 on the row's chunks, reject -> -1.
    This is the retrieval lever's memory — which chunks reviewers blessed or rejected.

    Scoping (all three matter for regulatory defensibility):

    `topic`   — when the retrieval path is EXPLICITLY topic-scoped, only feedback
                recorded under that same taxonomy topic counts. Without this, an
                approval given for 'cross_border' also re-ranks that clause for an
                unrelated 'data_subject_rights' query. Signals with a blank topic
                are excluded from a topic-scoped call: relevance can't be
                established, so they are not assumed relevant. When `topic` is None
                the caller is not scoped and the historical global behaviour is
                preserved.

    `version_scope` — feedback is only actionable under the taxonomy + model it was
                gathered on. Stale rows are IGNORED for retrieval but never deleted;
                they remain queryable for audit and history.

    Retired signals (see RETIRED_KEY) are skipped: retained for audit, inert for
    retrieval.

    NOTE (known limitation): only 'approve' and 'reject' carry weight. A 'modify'
    signal is stored with full before/after detail but contributes 0 here — a
    reviewer CORRECTING an answer currently teaches the retrieval layer nothing.
    Left unchanged deliberately; weighting it needs a product/evaluation decision.
    """
    from .models import FeedbackSignal
    qs = FeedbackSignal.objects.all()
    if version_scope:
        tax, model = _versions()
        qs = qs.filter(taxonomy_version=tax, model_version=model)
    if topic:
        qs = qs.filter(topic__iexact=topic)
    scores: dict[str, int] = {}
    for s in qs.only('kind', 'before'):
        w = 1 if s.kind == 'approve' else (-1 if s.kind == 'reject' else 0)
        if not w:
            continue
        b = s.before or {}
        if b.get(RETIRED_KEY):
            continue
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


def feedback_rerank(nodes, alpha=0.5, scores=None, topic=None):
    """Re-order retrieved nodes by (normalised base score) + alpha * bounded-feedback.

    Base scores are min-max normalised to 0..1 within the candidate set so the
    feedback term is meaningful regardless of the reranker's score scale.

    The feedback term is CLAMPED to [-1, +1] before scaling, so a chunk's total
    feedback advantage can never exceed `alpha` (0.5) — half the base range. One
    approval and fifty approvals move a chunk by exactly the same amount. Without
    the clamp, three approvals (0.5 * 3 = 1.5) exceeded the entire base score range
    and pinned a chunk at rank 1 permanently, regardless of relevance to the query.

    `topic` is forwarded to chunk_feedback_scores() so an explicitly topic-scoped
    retrieval only sees feedback from that topic. Deterministic: a reviewer-approved
    chunk moves up, a rejected one moves down. Exact no-op on a cold start.
    """
    scores = chunk_feedback_scores(topic=topic) if scores is None else scores
    if not scores or not nodes:
        return nodes
    bases = [float(getattr(n, 'score', 0) or 0) for n in nodes]
    lo, hi = min(bases), max(bases)
    rng = (hi - lo) or 1.0

    def adjusted(n):
        base = (float(getattr(n, 'score', 0) or 0) - lo) / rng
        net = scores.get(_node_chunk_id(n), 0)
        return base + alpha * max(-1, min(1, net))

    return sorted(nodes, key=adjusted, reverse=True)


# ── Document deletion ↔ the learning loop ────────────────────────────────────
# ComparisonRun.reg_a/reg_b are FKs with on_delete=CASCADE, so deleting a
# document already takes its runs and results with it. Feedback rows are linked
# LOOSELY (source_app + source_id -> ComparisonResult.pk), so they survive that
# cascade and would be left pointing at pks that no longer exist. The delete flow
# therefore asks the user what to do with them, and these two helpers implement
# both answers. Both must run BEFORE doc.delete(), while the runs still resolve.

def _result_ids_for_document(doc):
    """pks of every ComparisonResult produced from a run involving this document."""
    from apps.comparison.models import ComparisonResult
    from django.db.models import Q
    return list(
        ComparisonResult.objects
        .filter(Q(run__reg_a=doc) | Q(run__reg_b=doc))
        .values_list('pk', flat=True)
    )


def document_learning_footprint(doc):
    """What the loop has learned from this document: {'signals': n, 'gold': n}.
    Shown in the delete dialog so the choice is made with the numbers visible."""
    from django.db.models import Q
    from .models import FeedbackSignal, GoldExemplar
    try:
        ids = _result_ids_for_document(doc)
        signals = FeedbackSignal.objects.filter(source_app='comparison', source_id__in=ids).count()
        gold = GoldExemplar.objects.filter(
            Q(source_id__in=ids) | Q(reg_a=doc.name) | Q(reg_b=doc.name)).count()
        return {'signals': signals, 'gold': gold}
    except Exception:
        return {'signals': 0, 'gold': 0}


def purge_document_learning(doc, mode='keep'):
    """Apply the reviewer's choice for a document about to be deleted.

    mode='keep':  RETAIN the reviewer decisions and approved exemplars for audit,
                   but make them INERT for retrieval and generation:
                     - each signal is tombstoned in `note` with the document name,
                       and flagged RETIRED_KEY in `before` so chunk_feedback_scores()
                       skips it while the original chunk ids stay readable for audit;
                     - each exemplar is deactivated (active=False), which the
                       existing gold_for_topic() filter already respects.
                   Retiring is REQUIRED, not cosmetic: chunk ids are a deterministic
                   hash of (doc_title, chunk_id, index) — see ingestion.chunker._node_id
                   — so re-ingesting the same document title regenerates byte-identical
                   chunk ids. Without retiring, deleted-document feedback would silently
                   reattach on re-ingest, possibly to different text under the same id.
                   The dangling source_id is also why the tombstone matters: pks are
                   reused after deletion on SQLite.
    mode='purge': delete the signals and exemplars too, so nothing this document
                  taught the system survives it.

    Returns {'mode', 'signals', 'gold'} with the counts actually affected.
    """
    from django.db.models import Q
    from .models import FeedbackSignal, GoldExemplar
    out = {'mode': mode, 'signals': 0, 'gold': 0}
    try:
        ids = _result_ids_for_document(doc)
        signals = FeedbackSignal.objects.filter(source_app='comparison', source_id__in=ids)
        gold = GoldExemplar.objects.filter(
            Q(source_id__in=ids) | Q(reg_a=doc.name) | Q(reg_b=doc.name))
        if mode == 'purge':
            out['signals'] = signals.count()
            out['gold'] = gold.count()
            signals.delete()
            gold.delete()
        else:
            marker = f'[source document deleted: {doc.name}]'
            out['signals'] = signals.count()
            out['gold'] = gold.count()
            for s in signals.only('pk', 'note', 'before'):
                if marker not in (s.note or ''):
                    s.note = f'{s.note}\n{marker}'.strip()
                b = s.before or {}
                b[RETIRED_KEY] = True
                s.before = b
                s.save(update_fields=['note', 'before'])
            gold.update(active=False)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('purge_document_learning failed')
    return out


def capture_comparison_transition(result, new_lifecycle, actor=None):
    """Called from the reviewer transition view. Records the decision and, on
    approval, promotes the row to a gold exemplar. Best-effort: never raises into
    the review flow."""
    try:
        kind = {'approved': 'approve', 'rejected': 'reject'}.get(new_lifecycle, 'modify')
        # Topic key — MUST match the topic the retrieval was scoped by, because
        # chunk_feedback_scores(topic=...) filters on equality with it.
        # ComparisonRun.topics holds the analyst-selected taxonomy tags that were
        # pushed down into _scoped_retrieve, so it is authoritative. principle_ids
        # is only a fuzzy text probe (_detect_principles) that can match several
        # unrelated tags and return them in TAXONOMY dict order — using it first
        # would file feedback under a topic the run never retrieved against.
        # Falls back to it for full-scope runs, which carry no selected topic.
        topic = ''
        if result.run_id and getattr(result.run, 'topics', None):
            topic = str(result.run.topics[0])
        elif getattr(result, 'principle_ids', None):
            topic = str(result.principle_ids[0])
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
