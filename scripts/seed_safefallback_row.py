import os
import sys
import django

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cjpca'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
django.setup()

from apps.comparison.models import ComparisonRun

run = ComparisonRun.objects.get(pk=100)
report = run.report_json or {}
obligations = report.get('obligations', [])

fallback_ob = {
    'topic': 'Data Subject Right of Access',
    'source_chunk_a': 'india_dpdpa_2023_chap_iii_sec_11',
    'source_chunk_b': 'bahrain_pdpl_30_2018_art_15',
    'reg_a_citation': 'India_DPDPA_Act_2023 — Chapter III — Section 11 — Right to Access',
    'reg_b_citation': 'Bahrain_PDPL_Law_30_2018 — Article (15) Right to Access',
    'reg_a_chunk_id': 'india_dpdpa_2023_chap_iii_sec_11',
    'reg_b_chunk_id': 'bahrain_pdpl_30_2018_art_15',
    'reg_a_doc_title': 'India DPDP Act 2023',
    'reg_b_doc_title': 'Bahrain PDPL Law 30/2018',
    'reg_a_evidence': '',
    'reg_b_evidence': '',
    'equivalence': 'CONFLICTING',
    'similarity_score': 55,
    'confidence_score': 12,
    'reg_a_requirement': 'Data Principal shall have the right to obtain access to personal data.',
    'reg_b_requirement': 'Data subject shall have the right to access their personal data held by the controller.',
    'key_difference': 'Output suppressed by SafeFallback pattern. The verbatim citation verifier rejected the draft (non-verbatim span) and the bounded retry budget was exhausted. Manual analyst review required before this verdict can be relied upon.',
    'procedural_stricter': 'Not Assessable',
    'substantive_stricter': 'Not Assessable',
    'enforcement_stricter': 'Not Assessable',
    'stricter_jurisdiction': '',
    'notes': 'SafeFallback triggered. Per the §3.2 AI safety pattern, a typed-empty result with low confidence and high hallucination risk is returned rather than a plausible-but-unverified answer. citation_verified=False, hallucination_risk=0.87.',
    'citation_verified': False,
    'hallucination_risk': 0.87,
}

obligations.append(fallback_ob)
report['obligations'] = obligations
run.report_json = report
run.save(update_fields=['report_json'])
print(f'Appended SafeFallback obligation to run #{run.pk}. Total obligations now: {len(obligations)}')
print(f'Refresh /comparison/runs/{run.pk}/ and navigate to obligation {len(obligations)}/{len(obligations)}.')
