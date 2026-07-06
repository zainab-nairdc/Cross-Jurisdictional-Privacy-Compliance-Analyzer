"""Seed dummy analytics data so the /analytics/ dashboard renders fully populated
for the poster screenshot.

Creates fresh ComparisonRun + ComparisonResult rows using the new pair_key
format (bh_in / bh_kw / in_kw) that the analytics view filters by.

Run from project root with:
    .venv/Scripts/python.exe scripts/seed_analytics_demo.py
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'cjpca'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')

import django
django.setup()

from django.utils import timezone
from apps.library.models import Document
from apps.comparison.models import ComparisonRun, ComparisonResult


PRINCIPLES = [
    'consent', 'data_subject_rights', 'cross_border', 'sensitive_data',
    'data_controller', 'lawful_basis', 'third_party', 'data_subject',
    'breach_notification', 'retention', 'processing_basis', 'processor',
    'data_rights', 'transfers', 'controller', 'breach',
]

RELATIONSHIPS = [
    ('equivalent',      0.92, 0.30),
    ('stricter_in_a',   0.86, 0.20),
    ('stricter_in_b',   0.84, 0.18),
    ('additional_in_a', 0.80, 0.15),
    ('additional_in_b', 0.78, 0.12),
    ('conflicting',     0.75, 0.05),
]


def _pick_regulation(jurisdiction: str) -> Document:
    return (Document.objects
            .filter(doc_type='regulation', jurisdiction=jurisdiction)
            .first())


def _make_result(run, rel, principles_sample, idx):
    confidence = round(random.uniform(0.55, 0.99), 2)
    similarity = round(random.uniform(0.30, 0.95), 2)
    return ComparisonResult.objects.create(
        run=run,
        citation_a=f'Article ({idx + 1}) — clause {idx + 1}.{random.randint(1, 4)}',
        citation_b=f'Section {idx + 5} — sub-clause ({chr(97 + (idx % 6))})',
        preview_a=f'Demo preview for clause {idx + 1} in regulation A.',
        preview_b=f'Demo preview for clause {idx + 1} in regulation B.',
        relationship=rel,
        confidence=confidence,
        similarity_score=similarity,
        rationale='Demo rationale for analytics seed.',
        key_difference='Demo key difference text for analytics seed.',
        lifecycle=ComparisonResult.APPROVED,
        principle_ids=principles_sample,
        citation_verified=True,
        hallucination_risk=round(random.uniform(0.00, 0.25), 2),
    )


def seed_pair(pair_key: str, reg_a: Document, reg_b: Document, n_runs: int = 3):
    if not (reg_a and reg_b):
        print(f'  skip {pair_key} — missing regulations')
        return 0
    total = 0
    for r in range(n_runs):
        run = ComparisonRun.objects.create(
            pair_key=pair_key,
            reg_a=reg_a,
            reg_b=reg_b,
            topics=['enforcement', 'governance', 'lawful_basis'],
            status=ComparisonRun.COMPLETE,
            completed_pairs=8,
            total_pairs=8,
        )
        weights = [w for _, _, w in RELATIONSHIPS] + [random.uniform(0.05, 0.30)]
        weights = weights[:6]
        n_results = random.randint(6, 10)
        for i in range(n_results):
            rel, _, _ = random.choices(
                RELATIONSHIPS,
                weights=[1.6, 1.3, 1.2, 1.0, 0.9, 0.7],
                k=1,
            )[0]
            principles_sample = random.sample(
                PRINCIPLES, k=random.randint(1, 4),
            )
            _make_result(run, rel, principles_sample, i)
            total += 1
    return total


def main():
    random.seed(42)

    bh = _pick_regulation('bahrain')
    iN = _pick_regulation('india')
    kw = _pick_regulation('kuwait')

    print(f'Bahrain reg : {bh.name if bh else "MISSING"}')
    print(f'India reg   : {iN.name if iN else "MISSING"}')
    print(f'Kuwait reg  : {kw.name if kw else "MISSING"}')
    print()

    pairs = [
        ('bh_in', bh, iN, 4),
        ('bh_kw', bh, kw, 4),
        ('in_kw', iN, kw, 3),
    ]
    grand = 0
    for pk, a, b, n_runs in pairs:
        added = seed_pair(pk, a, b, n_runs)
        grand += added
        print(f'  {pk}: added {added} results across {n_runs} runs')
    print()
    print(f'Done. Created {grand} new comparison results.')


if __name__ == '__main__':
    main()
