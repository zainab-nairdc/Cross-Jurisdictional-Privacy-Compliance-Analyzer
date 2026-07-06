"""Generate Appendix 2.7 — Algorithm reference (lookup tables only).

Output: thesis_docs/appendix_2_7_lookups.docx

Contents: 8 lookup tables that the algorithms in §3.2.3 read from:
  A.7.1 — chunk_tags taxonomy (12 topics x subcategories)
  A.7.2 — Per-jurisdiction risk weights (penalty + enforcement)
  A.7.3 — Per-topic impact weights (RiskScore input)
  A.7.4 — Coverage factor by status (RiskScore input)
  A.7.5 — Severity-to-due-date buckets (gap analysis)
  A.7.6 — Algorithm configuration constants
  A.7.7 — DivergenceRanking weights and relationship map
  A.7.8 — Retrieval evaluation benchmarks

Pseudocode files (algorithm_*.py, appendix_a_7_1_*.py, appendix_a_7_2_*.py)
are NOT regenerated here; they live in thesis_docs/pseudocode/ and are
embedded as CodeSnap PNGs separately.
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


NAVY = RGBColor(0x00, 0x25, 0x83)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK_GRAY = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x6B, 0x72, 0x80)


# ── Table A.7.1 — chunk_tags taxonomy ─────────────────────────────────────
# 12 topics, each with subcategories. Source: reasoning/taxonomy.py
TAXONOMY_ROWS = [
    ('lawful_basis',           'Lawful basis & consent',
     'consent; legitimate_interests; legal_obligation; vital_or_public_task'),
    ('data_subject_rights',    'Data subject rights',
     'access; rectification; erasure; objection_and_automated'),
    ('notice_and_transparency','Notice & transparency',
     'privacy_notice; secondary_use_notice; language_accessibility'),
    ('cross_border',           'Cross-border transfers & data residency',
     'adequacy_assessment; transfer_mechanisms; data_localisation; transfer_exemptions'),
    ('sensitive_data',         'Sensitive & special-category data',
     'sensitive_processing; children_and_minors'),
    ('security',               'Security controls',
     'technical_measures; organisational_measures; access_control; logging_and_monitoring'),
    ('breach_management',      'Breach management',
     'incident_detection; regulator_notification; data_subject_notification; incident_response_plan'),
    ('retention',              'Retention & disposal',
     'retention_periods; secure_disposal; archive_and_backup'),
    ('governance',             'Governance & accountability',
     'dpo_appointment; records_of_processing; dpia_and_risk; policies_and_procedures'),
    ('third_party',            'Third-party & outsourcing',
     'processor_obligations; vendor_due_diligence; cloud_and_offshoring; data_sharing'),
    ('sector_specific',        'Sector-specific (banking & financial)',
     'kyc_and_cdd; aml_and_sanctions; customer_protection; operational_resilience'),
    ('enforcement',            'Enforcement & remedies',
     'regulator_powers; penalties; complaints_and_grievance; individual_redress'),
]

# ── Table A.7.2 — Per-jurisdiction risk weights ──────────────────────────
# Source: cjpca/apps/mapping/risk.py
RISK_JURISDICTION_ROWS = [
    ('Bahrain (PDPL + Orders)',   '0.95', '0.80',
     'Highest statutory penalties and active enforcement regime'),
    ('India (DPDPA 2023 + Rules)','0.90', '0.65',
     'High fines; enforcement still ramping under DPB'),
    ('Kuwait (DPPR 26/2024)',     '0.75', '0.70',
     'Moderate penalties; CITRA enforcement active but lower fines'),
]

# ── Table A.7.3 — Per-topic impact weights (RiskScore) ───────────────────
RISK_TOPIC_ROWS = [
    ('consent',         '0.95'),
    ('breach',          '0.95'),
    ('cross_border',    '0.90'),
    ('security',        '0.85'),
    ('retention',       '0.75'),
    ('governance',      '0.55'),
    ('training',        '0.50'),
]

# ── Table A.7.4 — Coverage factor by status ──────────────────────────────
RISK_COVERAGE_ROWS = [
    ('not_covered', '1.00', 'No policy clause addresses the obligation'),
    ('partial',     '0.55', 'Policy partially addresses the obligation'),
    ('review',      '0.65', 'Policy unclear; reviewer must read'),
    ('covered',     '0.05', 'Policy fully addresses the obligation'),
]

# ── Table A.7.5 — Severity-to-due-date buckets ───────────────────────────
SEVERITY_DUE_ROWS = [
    ('Critical', '14 days',
     'Score >= 0.65; legal exposure or active enforcement risk'),
    ('High',     '30 days',
     'Score 0.45-0.65; significant gap requiring near-term remediation'),
    ('Medium',   '90 days',
     'Score 0.25-0.45; remediation needed within the quarter'),
    ('Low',      '180 days',
     'Score < 0.25; track but no immediate exposure'),
]

# ── Table A.7.6 — Algorithm configuration constants ──────────────────────
CONFIG_ROWS = [
    ('HALLUCINATION_THRESHOLD', '0.10',
     'Algorithm 1a: max NLI risk before a draft is rejected'),
    ('RRF k',                   '60',
     'Algorithm 2: Reciprocal Rank Fusion constant'),
    ('TOP_K (vector + BM25)',   '20',
     'Algorithm 2: candidates from each retriever before fusion'),
    ('FINAL_TOP_K',             '5',
     'Algorithm 2: chunks returned to the agent'),
    ('max_retries',             '2',
     'Algorithm 1: bounded retry budget before fallback'),
    ('MIN_QUOTE_LENGTH',        '10 chars',
     'Algorithm 1a: shortest accepted exact_quote'),
    ('CONFIDENCE_FLOOR',        '0.30',
     'A.7.1.g: minimum classifier confidence to accept a tag'),
    ('MERGE_THRESHOLD',         '0.85',
     'Algorithm 5: semantic similarity for chunk merging'),
    ('IDLE_TIMEOUT',            '1800 s (30 min)',
     'A.7.2.c: inactivity before forced logout'),
    ('GRACE_PERIOD',            '90 s',
     'A.7.2.b: minimum age of a RUNNING row before reset'),
    ('NAV_CACHE_TIMEOUT',       '30 s',
     'A.7.2.g: sidebar badge cache TTL'),
    ('Audit hash length',       '16 hex chars (64 bits)',
     'Algorithm 6: SHA-256 prefix on every export'),
]

# ── Table A.7.7 — DivergenceRanking weights + relationship map ───────────
DIVERGENCE_WEIGHT_ROWS = [
    ('rel (relationship strength)',  '0.40'),
    ('conf (model confidence)',      '0.30'),
    ('1 - sim (lexical distance)',   '0.20'),
    ('principle (criticality of topic)', '0.10'),
]

DIVERGENCE_REL_ROWS = [
    ('conflicting',      '1.00', 'Clauses contradict each other'),
    ('stricter_in_a',    '0.70', 'Side A is stricter than B'),
    ('stricter_in_b',    '0.70', 'Side B is stricter than A'),
    ('additional_in_a',  '0.50', 'Only in A; no counterpart in B'),
    ('additional_in_b',  '0.50', 'Only in B; no counterpart in A'),
    ('equivalent',       '0.00', 'Clauses align'),
]

# ── Table A.7.8 — Retrieval evaluation benchmarks ────────────────────────
RETRIEVAL_EVAL_ROWS = [
    ('Hybrid retrieval (this system)', 'hit_rate@5', '0.950',
     '40-pair benchmark; BM25 (SQLite FTS5, persistent) + ChromaDB + RRF + cross-encoder rerank'),
    ('LlamaIndex baseline (in-memory)','hit_rate@5', '0.875',
     'Same 40-pair benchmark; rebuilt per process, no filter pushdown'),
    ('Hybrid retrieval', 'NLI faithfulness (RAGAS)', '> 0.85',
     '8-question test set with Claude Haiku 4.5 as judge'),
    ('Single-shot LLM call (no retrieval)', 'hit_rate@5', '<= 0.10',
     'Baseline: model relies on training data only; included to motivate retrieval'),
]


# ── Style helpers ─────────────────────────────────────────────────────────

def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def set_run_style(run, *, bold=False, italic=False, color=NAVY, size=11):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)


def add_paragraph(doc, text, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    set_run_style(run, bold=bold, italic=italic, color=color, size=size)
    return p


def add_heading(doc, text, *, level=1):
    style_map = {1: 'Heading 2', 2: 'Heading 3', 3: 'Heading 4'}
    size_map = {1: 14, 2: 12, 3: 11}
    h = doc.add_paragraph(style=style_map[level])
    run = h.add_run(text)
    run.font.color.rgb = NAVY
    run.font.bold = True
    run.font.size = Pt(size_map[level])
    return h


def add_table_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_lookup_table(doc, headers, rows, widths_cm):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)

    # Header row
    header_row = table.rows[0]
    for i, h in enumerate(headers):
        cell = header_row.cells[i]
        cell.text = h
        shade_cell(cell, '002583')
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            set_run_style(run, bold=True, color=WHITE, size=10)

    # Body rows
    for r_idx, row_values in enumerate(rows, start=1):
        row = table.rows[r_idx]
        for c_idx, value in enumerate(row_values):
            cell = row.cells[c_idx]
            cell.text = str(value)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            for para in cell.paragraphs:
                for run in para.runs:
                    set_run_style(
                        run,
                        bold=(c_idx == 0),
                        color=DARK_GRAY,
                        size=9,
                    )


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'appendix_2_7_lookups.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'appendix_2_7_lookups_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, 'Appendix 2.7 — Algorithm reference', level=1)

    add_paragraph(
        doc,
        'This appendix carries the lookup tables, weights, and configuration '
        'constants that the algorithms in §3.2.3 read from. Eight tables are '
        'provided. Pseudocode for auxiliary procedures (A.7.1) and Django '
        'integration patterns (A.7.2) is embedded as figures (CodeSnap '
        'screenshots) in the surrounding appendix; this document carries the '
        'tables only.',
    )

    # ── Table A.7.1 — Taxonomy ────────────────────────────────────────────
    add_heading(doc, 'A.7.1 — chunk_tags taxonomy', level=2)
    add_paragraph(
        doc,
        'Twelve top-level topics with their subcategories. Every chunk in the '
        'corpus is tagged with exactly one (topic, subcategory) pair from this '
        'controlled vocabulary by ChunkClassify (A.7.1.g). Out-of-vocabulary '
        'tags coerce to UNCLASSIFIED.',
    )
    add_table_caption(doc, 'Table A.7.1.',
                      'chunk_tags taxonomy used by ChunkClassify and AutoRouteScope.')
    add_lookup_table(
        doc,
        ['Topic tag', 'Label', 'Subcategories'],
        TAXONOMY_ROWS,
        widths_cm=[3.5, 4.5, 8.5],
    )

    # ── Table A.7.2 — Jurisdiction risk weights ──────────────────────────
    add_heading(doc, 'A.7.2 — Per-jurisdiction risk weights', level=2)
    add_paragraph(
        doc,
        'Penalty and enforcement weights used by RiskScore (A.7.1.c). Penalty '
        'reflects maximum statutory fines and imprisonment provisions; '
        'enforcement reflects the regulator\'s observed activity level.',
    )
    add_table_caption(doc, 'Table A.7.2.',
                      'Penalty and enforcement weights per jurisdiction.')
    add_lookup_table(
        doc,
        ['Jurisdiction', 'Penalty weight', 'Enforcement weight', 'Rationale'],
        RISK_JURISDICTION_ROWS,
        widths_cm=[4.0, 2.5, 2.5, 7.5],
    )

    # ── Table A.7.3 — Per-topic impact weights ───────────────────────────
    add_heading(doc, 'A.7.3 — Per-topic impact weights', level=2)
    add_paragraph(
        doc,
        'Impact weight per topic used by RiskScore. A non-coverage gap on a '
        'high-impact topic (consent, breach, cross-border) carries more risk '
        'than the same gap on training or governance.',
    )
    add_table_caption(doc, 'Table A.7.3.',
                      'Impact weight per topic.')
    add_lookup_table(
        doc,
        ['Topic', 'Impact weight'],
        RISK_TOPIC_ROWS,
        widths_cm=[6.0, 4.0],
    )

    # ── Table A.7.4 — Coverage factor ────────────────────────────────────
    add_heading(doc, 'A.7.4 — Coverage factor by status', level=2)
    add_paragraph(
        doc,
        'Coverage factor used by RiskScore. A covered obligation contributes '
        'almost zero risk (0.05) while a not-covered obligation contributes '
        'the full multiplier (1.0).',
    )
    add_table_caption(doc, 'Table A.7.4.',
                      'Coverage factor per ObligationMapping status.')
    add_lookup_table(
        doc,
        ['Coverage status', 'Factor', 'Meaning'],
        RISK_COVERAGE_ROWS,
        widths_cm=[3.0, 2.0, 11.5],
    )

    # ── Table A.7.5 — Severity-to-due-date ───────────────────────────────
    add_heading(doc, 'A.7.5 — Severity-to-due-date buckets', level=2)
    add_paragraph(
        doc,
        'Default due-date offset used by gap analysis and the export pipeline '
        '(Algorithm 6). A reviewer can set an explicit Gap.due_date which '
        'overrides this default.',
    )
    add_table_caption(doc, 'Table A.7.5.',
                      'Severity bucket to default due-date offset.')
    add_lookup_table(
        doc,
        ['Severity bucket', 'Default due offset', 'Trigger condition'],
        SEVERITY_DUE_ROWS,
        widths_cm=[3.0, 3.0, 10.5],
    )

    # ── Table A.7.6 — Configuration constants ────────────────────────────
    add_heading(doc, 'A.7.6 — Algorithm configuration constants', level=2)
    add_paragraph(
        doc,
        'Tunable constants referenced across the algorithms in §3.2.3 and '
        'Appendix 2.7. Values are loaded from cfg at process start; the '
        'thresholds shown are the defaults used in the BBK deployment.',
    )
    add_table_caption(doc, 'Table A.7.6.',
                      'Algorithm configuration constants.')
    add_lookup_table(
        doc,
        ['Constant', 'Value', 'Used by'],
        CONFIG_ROWS,
        widths_cm=[4.5, 4.0, 8.0],
    )

    # ── Table A.7.7 — DivergenceRanking weights ──────────────────────────
    add_heading(doc, 'A.7.7 — DivergenceRanking weights', level=2)
    add_paragraph(
        doc,
        'Importance formula weights used by DivergenceRanking (A.7.1.b) and '
        'the relationship-to-strength mapping that feeds the rel term.',
    )
    add_table_caption(doc, 'Table A.7.7 (a).',
                      'Importance-formula component weights.')
    add_lookup_table(
        doc,
        ['Component', 'Weight'],
        DIVERGENCE_WEIGHT_ROWS,
        widths_cm=[8.0, 4.0],
    )
    add_table_caption(doc, 'Table A.7.7 (b).',
                      'Relationship-to-rel-weight mapping.')
    add_lookup_table(
        doc,
        ['Relationship', 'rel weight', 'Meaning'],
        DIVERGENCE_REL_ROWS,
        widths_cm=[3.5, 2.5, 10.5],
    )

    # ── Table A.7.8 — Retrieval evaluation ───────────────────────────────
    add_heading(doc, 'A.7.8 — Retrieval evaluation benchmarks', level=2)
    add_paragraph(
        doc,
        'Hit-rate and faithfulness benchmarks on the 40-pair retrieval set '
        'and 8-question reasoning set. The custom hybrid retriever was '
        'selected over the in-memory llamaindex baseline on the strength of '
        'these numbers (and the persistence + filter-pushdown advantages).',
    )
    add_table_caption(doc, 'Table A.7.8.',
                      'Retrieval and reasoning evaluation benchmarks.')
    add_lookup_table(
        doc,
        ['System', 'Metric', 'Score', 'Conditions'],
        RETRIEVAL_EVAL_ROWS,
        widths_cm=[4.5, 3.5, 2.0, 6.5],
    )

    doc.save(out_path)
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
