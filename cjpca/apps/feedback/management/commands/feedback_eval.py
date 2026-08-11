"""Evaluate whether reviewer feedback changes comparison output — MULTI-TOPIC A/B.

For each topic, a controlled experiment (everything identical except the feedback):
  COLD : run the comparison with NO approved feedback.
  (a reviewer approves a distinctive exemplar for this topic)
  WARM : run the SAME comparison — the approved exemplar is now injected.

Metric: embedding similarity of each run's operational conclusion to the approved
conclusion. If WARM > COLD, the feedback steered the output. We report per-topic
and the AVERAGE across topics, so the judgement is statistical, not anecdotal.

Temperature is 0, so the ONLY variable between cold and warm is the feedback.

!! KNOWN METHODOLOGICAL FLAW — THIS EVAL IS CIRCULAR.
   The WARM run has the approved conclusion injected into its prompt, and the
   metric is similarity TO THAT SAME CONCLUSION. A model that merely echoes its
   context scores well without reasoning any better. A positive delta therefore
   does NOT establish that few-shot feedback improves output quality, and a
   negative one does not disprove it. Recorded results: avg -0.027 (early run),
   avg +0.070 (2026-08-11 re-run) — neither is trustworthy evidence.
   FEEDBACK_FEWSHOT_ENABLED stays False in production on this basis.
   A trustworthy replacement would score against a HELD-OUT conclusion the prompt
   never saw, or use blind reviewer preference between cold/warm outputs.

Run:  python manage.py feedback_eval
"""

import sys
from pathlib import Path

from django.core.management.base import BaseCommand

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

# topic tag -> a plausible reviewer-approved operational conclusion for that topic
APPROVED = {
    'lawful_basis':
        'Equivalent obligation — a single lawful-basis register plus the privacy '
        'governance policy satisfies both regimes; no new control required.',
    'data_subject_rights':
        'Equivalent with minor differences — one data-subject-request procedure '
        '(access, rectification, erasure, objection) satisfies both; align response '
        'deadlines to the stricter timeline.',
    'cross_border':
        'Same objective, different mechanism — a transfer impact assessment plus '
        'standard contractual clauses covers both; add the local authority '
        'authorisation step for the Gulf regime.',
}


class Command(BaseCommand):
    help = 'Multi-topic A/B evaluation of the feedback loop (cold vs approved-feedback).'

    def add_arguments(self, parser):
        parser.add_argument('--topics', default=','.join(APPROVED.keys()))

    def handle(self, *args, **opts):
        import numpy as np
        from reasoning.workflows import compare_regulations
        from reasoning.taxonomy import topic_label
        from ingestion.embedder import get_model
        from apps.feedback.models import GoldExemplar
        from apps.feedback.services import promote_to_gold

        w   = self.stdout.write
        emb = get_model()
        topics = [t.strip() for t in opts['topics'].split(',') if t.strip()]

        def cos(x, y):
            if not x or not y:
                return 0.0
            vx, vy = emb.encode(x), emb.encode(y)
            return float(vx @ vy / (np.linalg.norm(vx) * np.linalg.norm(vy) + 1e-9))

        REGS = dict(reg_a='eu', reg_b='bahrain',
                    doc_title_a='gdpr', doc_title_b='Bahrain_PDPL_Law_30_2018')

        def run_once(tag, label):
            rep = compare_regulations(query=label, top_k=8, rerank=True,
                                      scope_mode='strict', topic=tag, **REGS)
            if not rep.obligations:
                return None
            o = rep.obligations[0]
            return (o.practical_conclusion or o.notes or o.key_difference or '').strip()

        rows, deltas, improved = [], [], 0
        for tag in topics:
            label = topic_label(tag) or tag.replace('_', ' ')
            approved = APPROVED.get(tag, '')
            if not approved:
                continue

            # The cold run must see no gold for this topic, but REAL analyst-approved
            # exemplars live in the same table. Deactivate them for the duration and
            # restore in `finally` — never delete: an earlier version of this command
            # ran `.filter(topic__iexact=tag).delete()` and destroyed a production
            # GoldExemplar whose topic happened to match an eval topic.
            pre = list(GoldExemplar.objects.filter(topic__iexact=tag, active=True)
                       .values_list('pk', flat=True))
            GoldExemplar.objects.filter(pk__in=pre).update(active=False)
            mine = None
            try:
                cold = run_once(tag, label)
                mine = promote_to_gold(
                    topic=tag, reg_a='GDPR', reg_b='Bahrain PDPL',
                    payload={'equivalence': 'Equivalent', 'practical_conclusion': approved},
                    source_id=None)
                warm = run_once(tag, label)
            finally:
                if mine is not None:
                    GoldExemplar.objects.filter(pk=mine.pk).delete()   # only our own row
                GoldExemplar.objects.filter(pk__in=pre).update(active=True)

            if not cold or not warm:
                w(f'  {label:34s}  (skipped — no obligations)')
                continue
            c_cold, c_warm = cos(cold, approved), cos(warm, approved)
            d = c_warm - c_cold
            deltas.append(d)
            improved += 1 if d > 0.01 else 0
            rows.append((label, c_cold, c_warm, d, cold, warm))
            w(f'  {label:34s}  cold {c_cold:.2f} -> warm {c_warm:.2f}   (Δ {d:+.2f})')

        w(self.style.MIGRATE_HEADING('\n=== JUDGEMENT ==='))
        if deltas:
            mean = sum(deltas) / len(deltas)
            w(f'  topics evaluated       : {len(deltas)}')
            w(f'  moved toward approved  : {improved}/{len(deltas)}')
            w(f'  average similarity Δ   : {mean:+.3f}   (>0 means feedback steered the output)')
            verdict = ('feedback measurably steers output (but a gentle, in-context steer)'
                       if mean > 0.01 else 'no reliable steer from a single exemplar')
            w(f'  verdict                : {verdict}')
            # show the sharpest single example
            best = max(rows, key=lambda r: r[3])
            w(self.style.MIGRATE_HEADING('\n  sharpest shift — ' + best[0]))
            w(f'   COLD: {best[4][:200]}')
            w(f'   WARM: {best[5][:200]}')
        else:
            w('  no topics produced obligations to evaluate.')
