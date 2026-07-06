"""topic_scan.py — Per-regulation taxonomy coverage for the Scope picker.

Replaces the previous CONCEPT_SEEDS regex-based scan with one that reads
the chunk_tags side-table — the exact same data the reasoning layer's
auto-routing uses (``reasoning.workflows.compare_regulations`` → topic
filter pushes down to retrieval). Two consequences:

  1. The topic chips on the picker are real taxonomy topics
     (``lawful_basis``, ``breach_management``, …). When the user ticks one
     and hits Run, the reasoning layer's ``topic`` filter actually fires
     and restricts retrieval to taxonomy-tagged chunks.

  2. The coverage counts shown ("12 articles in A, 4 in B") reflect the
     LLM classifier's verdict (``manage.py classify_chunks``), not a
     hand-crafted regex. Better signal, accurate to what the workflow
     will see.
"""
from __future__ import annotations

from reasoning import taxonomy as _tx


def scan_topic_coverage(reg_a_pk: int, reg_b_pk: int) -> dict:
    """Return per-taxonomy-topic coverage for two regulations.

    Returns:
        {
          both_covered: [{principle_id, label, articles_a, articles_b,
                          bar_width_a, bar_width_b, estimated_pairs}],
          only_in_a:    [{principle_id, label, articles}],
          only_in_b:    [{principle_id, label, articles}],
          total_estimated_pairs_full: int,
          total_estimated_seconds_full: int,
        }

    The values returned in ``principle_id`` are TAXONOMY topic tags
    (e.g. ``lawful_basis``) so the form's hidden ``topics`` field carries
    exactly what ``compare_regulations(topic=...)`` accepts.
    """
    from apps.library.models import Document
    from retrieval.bm25_store import topics_for_docs

    doc_a = Document.objects.get(pk=reg_a_pk)
    doc_b = Document.objects.get(pk=reg_b_pk)

    title_a = doc_a.chunk_doc_title or doc_a.name
    title_b = doc_b.chunk_doc_title or doc_b.name

    # topics_for_docs → [(topic_tag, chunk_count), ...] sorted desc by count,
    # unclassified filtered out. Same call the auto-routing in workflows.py uses.
    counts_a = dict(topics_for_docs([title_a]))
    counts_b = dict(topics_for_docs([title_b]))

    # Use the canonical taxonomy ordering so the chips render in a stable order.
    taxonomy_topics = [t for t, _ in _tx.all_topics()]
    max_a = max(counts_a.values(), default=1)
    max_b = max(counts_b.values(), default=1)

    both_covered: list[dict] = []
    only_in_a:    list[dict] = []
    only_in_b:    list[dict] = []

    for topic_tag in taxonomy_topics:
        hits_a = counts_a.get(topic_tag, 0)
        hits_b = counts_b.get(topic_tag, 0)
        if hits_a == 0 and hits_b == 0:
            continue

        entry = {
            'principle_id': topic_tag,
            'label':        _tx.topic_label(topic_tag),
        }

        if hits_a > 0 and hits_b > 0:
            both_covered.append({
                **entry,
                'articles_a':     hits_a,
                'articles_b':     hits_b,
                'estimated_pairs': max(hits_a, hits_b),
                'bar_width_a':    round(hits_a / max_a * 100),
                'bar_width_b':    round(hits_b / max_b * 100),
            })
        elif hits_a > 0:
            only_in_a.append({**entry, 'articles': hits_a})
        else:
            only_in_b.append({**entry, 'articles': hits_b})

    both_covered.sort(key=lambda x: x['articles_a'] + x['articles_b'], reverse=True)

    total_pairs   = sum(e['estimated_pairs'] for e in both_covered)
    total_seconds = max(total_pairs * 10, 30)

    return {
        'both_covered':                 both_covered,
        'only_in_a':                    only_in_a,
        'only_in_b':                    only_in_b,
        'total_estimated_pairs_full':   total_pairs,
        'total_estimated_seconds_full': total_seconds,
    }
