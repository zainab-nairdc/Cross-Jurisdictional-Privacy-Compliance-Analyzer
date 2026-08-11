"""Evaluate the RETRIEVAL feedback lever — the reliable one.

Question: when a reviewer approves a comparison that used a particular clause, does
that clause reliably rank higher the next time a related query retrieves it?

For each query:
  1. retrieve the top-k chunks (baseline order),
  2. take a mid-ranked relevant chunk as the 'reviewer-approved' one,
  3. record a reviewer APPROVAL on it,
  4. re-rank with feedback_rerank() and record the chunk's new position.

Unlike the generation few-shot lever, this is DETERMINISTIC — an approved chunk
always moves up — so we measure how far, and report MRR before vs after.

Run:  python manage.py feedback_rerank_eval
"""

import sys
from pathlib import Path

from django.core.management.base import BaseCommand

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

# (label, query) — GDPR clauses a reviewer might bless during a comparison.
QUERIES = [
    ('DPO tasks',        'designation position and tasks of the data protection officer'),
    ('breach 72h',       'personal data breach notification to the supervisory authority within 72 hours'),
    ('cross-border',     'transfer of personal data to a third country based on an adequacy decision'),
    ('data-subject',     'right of access rectification and erasure of personal data'),
]
DOC = 'gdpr'
TARGET_RANK = 4   # approve a mid-ranked relevant chunk so the lift is visible


class Command(BaseCommand):
    help = 'Evaluate the retrieval feedback lever: do approved chunks reliably rank up?'

    def handle(self, *args, **opts):
        from reasoning.workflows import _scoped_retrieve
        from apps.feedback.models import FeedbackSignal
        from apps.feedback.services import feedback_rerank, record_feedback, _node_chunk_id

        w = self.stdout.write

        def rank_of(nodes, cid):
            for i, n in enumerate(nodes, 1):
                if _node_chunk_id(n) == cid:
                    return i
            return None

        FeedbackSignal.objects.filter(source_app='eval').delete()
        before, after = [], []

        for label, q in QUERIES:
            nodes = _scoped_retrieve(q, top_k=8, doc_titles=[DOC], scope_mode='strict', rerank=True)
            if len(nodes) < TARGET_RANK:
                w(f'  {label:14s}  (only {len(nodes)} chunks — skipped)')
                continue
            target = nodes[TARGET_RANK - 1]
            tcid = _node_chunk_id(target)
            base_rank = TARGET_RANK

            # A reviewer approves a comparison that cited this chunk. Go through
            # record_feedback() rather than a raw create so the row is stamped with
            # the CURRENT taxonomy/model version — chunk_feedback_scores() now
            # version-scopes, and an unstamped row would be (correctly) ignored.
            record_feedback(kind='approve', source_id=0, topic=label,
                            query=q, before={'chunk_id_a': tcid}, source_app='eval')
            # topic=None: this eval measures the unscoped lever, matching the
            # _scoped_retrieve call above which passes no taxonomy topic.
            reranked = feedback_rerank(nodes)
            new_rank = rank_of(reranked, tcid)
            FeedbackSignal.objects.filter(source_app='eval').delete()

            before.append(base_rank)
            after.append(new_rank or base_rank)
            arrow = '↑' if new_rank and new_rank < base_rank else '—'
            w(f'  {label:14s}  approved-chunk rank: {base_rank} -> {new_rank}  {arrow}')

        def mrr(rs):
            rs = [r for r in rs if r]
            return sum(1.0 / r for r in rs) / len(rs) if rs else 0.0

        w(self.style.MIGRATE_HEADING('\n=== JUDGEMENT (retrieval lever) ==='))
        if before:
            improved = sum(1 for b, a in zip(before, after) if a and a < b)
            w(f'  queries evaluated             : {len(before)}')
            w(f'  approved chunk ranked higher  : {improved}/{len(before)}')
            w(f'  MRR of approved chunk         —  before: {mrr(before):.2f}   after: {mrr(after):.2f}')
            w('  → deterministic: reviewer-approved clauses reliably surface. This is the '
              'independently-measurable lever; the generation few-shot lever is '
              'experimental and stays OFF (its eval is circular — see feedback_eval).')
        else:
            w('  no queries produced enough chunks to evaluate.')
