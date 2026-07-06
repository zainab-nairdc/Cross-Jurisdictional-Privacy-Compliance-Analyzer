"""Generate §4 Discussion and Conclusion as one docx.

Output: thesis_docs/4_discussion.docx

Rubric coverage (mark scheme target: 5/5 with no deductions):
  4.1 System Functionality
  4.2 Summary of Achieved Objectives
  4.3 Project Issues (with Proposed Solutions/Actions)
  4.4 Legal, Ethical, Social, and Professional Issues
  4.5 Future Work (Upgrades and Modifications)
  4.6 Synopsis of Experience
  4.7 Conclusion

Main body word target: 3000 words including tables. Style follows
§3.4: plain Word table with grey header (#D9D9D9), black text,
horizontal borders only, generic short captions for Word auto-numbering.
Prose avoids em-dashes and semicolons by convention.
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BLACK = RGBColor(0x00, 0x00, 0x00)
NAVY = BLACK
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK_GRAY = BLACK
MUTED = BLACK
HEADER_FILL = 'D9D9D9'
ROW_BORDER = 'BFBFBF'


def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def _set_cell_borders(cell, top=None, bottom=None, left=None,
                       right=None):
    tc_pr = cell._tc.get_or_add_tcPr()
    tcBorders = tc_pr.find(qn('w:tcBorders'))
    if tcBorders is None:
        tcBorders = OxmlElement('w:tcBorders')
        tc_pr.append(tcBorders)
    for side, spec in (('top', top), ('bottom', bottom),
                       ('left', left), ('right', right)):
        existing = tcBorders.find(qn(f'w:{side}'))
        if existing is not None:
            tcBorders.remove(existing)
        if spec is None:
            border = OxmlElement(f'w:{side}')
            border.set(qn('w:val'), 'nil')
            tcBorders.append(border)
            continue
        border = OxmlElement(f'w:{side}')
        border.set(qn('w:val'), spec.get('val', 'single'))
        border.set(qn('w:sz'), str(spec.get('sz', 4)))
        border.set(qn('w:space'), '0')
        border.set(qn('w:color'), spec.get('color', '000000'))
        tcBorders.append(border)


def _apply_plain_row_borders(cell, *, is_header=False):
    _set_cell_borders(
        cell,
        top={'val': 'single', 'sz': 4, 'color': ROW_BORDER}
            if is_header else None,
        bottom={'val': 'single', 'sz': 4, 'color': ROW_BORDER},
        left=None, right=None,
    )


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


def add_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_table(doc, headers, rows, widths_cm, body_size=9):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)
    header_row = table.rows[0]
    for i, h in enumerate(headers):
        cell = header_row.cells[i]
        cell.text = h
        shade_cell(cell, HEADER_FILL)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            set_run_style(run, bold=True, color=BLACK, size=10)
        _apply_plain_row_borders(cell, is_header=True)
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
                        color=BLACK,
                        size=body_size,
                    )
            _apply_plain_row_borders(cell)


# -------------------------------------------------------------------------
# DATA
# -------------------------------------------------------------------------

OBJECTIVES = [
    ('T1',
     'Hybrid retrieval combining keyword and semantic search '
     'with rerank, returning citation-preserving results.',
     'Achieved',
     'BM25/FTS5 plus ChromaDB vector lane fused via RRF k=60 '
     'then reranked by ms-marco MiniLM. §3.4.5 evaluation '
     'shows hybrid+rerank hit-rate@1 of 0.84 vs 0.71 BM25 and '
     '0.68 vector single-lane baselines.'),
    ('T2',
     'AI-driven reasoning workflows for regulation comparison, '
     'policy-coverage mapping, and gap analysis.',
     'Achieved',
     'LangGraph state machine with Pydantic schema-validated '
     'outputs, citation verifier rejecting ungrounded clauses '
     '(96% first-pass, 3% retry, 1% SafeFallback per §3.4.5).'),
    ('T3',
     'AI-powered Copilot providing reviewers with '
     'citation-backed guidance grounded in retrieved legal text.',
     'Achieved',
     'Scoped copilot dock with warm-cache response under 5 s '
     'and 100% scope respect across the 10-query usability '
     'sample in §3.4.3.'),
    ('T4',
     'Web reviewer platform with role-based workflows '
     'implementing a Draft, Reviewed, Approved lifecycle.',
     'Achieved',
     'Three operational roles, TOTP MFA enforced on every '
     'account, full lifecycle transitions captured in AuditLog '
     'with role-at-time snapshot.'),
    ('T5',
     'Security-by-design covering authentication, access '
     'control, audit logging, and AI safety.',
     'Achieved',
     'Seven-tier defence-in-depth, 16-layer middleware chain, '
     'mapped to OWASP Top 10 and OWASP Top 10 for LLM '
     'Applications in §3.2.8.'),
    ('G1',
     'Reduce manual cross-jurisdictional review time compared '
     'to legacy workflows.',
     'Achieved',
     'Mapping completed in under 12 minutes during §3.4.3 user '
     'testing versus a prior half-day manual baseline, an '
     'order-of-magnitude reduction.'),
    ('G2',
     'Identify compliance gaps across Bahrain, India, and '
     'Kuwait privacy regimes.',
     'Achieved',
     '100% citation traceability via the verbatim verifier on '
     'every reasoning output, confirmed by §3.4.5 citation '
     'grounding evaluation.'),
    ('G3',
     'Support BBK digital transformation through AI-assisted '
     'compliance.',
     'Achieved',
     'Functional reviewer platform delivered for internal '
     'demonstration during BBK consultation review.'),
    ('G4',
     'Scale to a growing regulatory and policy corpus without '
     'code changes.',
     'Achieved',
     'New documents added through the standard /library/upload/ '
     'path during testing without source-code modification.'),
    ('G5',
     'Maintain regulatory transparency and audit readiness '
     'through tamper-evident audit logs.',
     'Achieved',
     'Append-only AuditLog enforced by application guard, '
     'SHA-256 hash chain stamped on every report export.'),
]


ISSUES = [
    ('I1 Chunking strategy on nested regulations',
     'Fixed-size chunking split articles mid-sentence, and naive '
     'section-aware chunking failed on deeply nested clauses '
     '(PDPL Article 5(2)(c)) where the legal context spanned '
     'multiple ancestor sections, hurting retrieval precision.',
     'Implemented hierarchical section-aware chunking with '
     'ancestor-context preservation, plus a maximum-size guard '
     'so a long article does not produce one mega-chunk. Final '
     'design retains article boundaries while keeping chunks '
     'within the embedding model context window.'),
    ('I2 Citation verifier rejecting valid paraphrases',
     'The reasoning agent would correctly capture the spirit of '
     'a clause but in paraphrased form, which the verbatim '
     'verifier rejected. The retry rate during early testing '
     'was unacceptably high.',
     'Re-engineered the prompt to demand verbatim quoted spans '
     'in the JSON schema, paired with an automatic "correct" '
     'node in the LangGraph workflow. First-pass rate rose to '
     '96% per the §3.4.5 evaluation.'),
    ('I3 NLI hallucination gate calibration',
     'Selecting the cross-encoder NLI threshold required '
     'empirical tuning. Too low and the SafeFallback rate '
     'killed utility, too high and plausible-but-wrong outputs '
     'reached analysts.',
     'Ran the 100-query test set across thresholds 0.2 to 0.8 '
     'and picked 0.4, which gives 87% high-faithfulness output, '
     '11% medium (gate passed), and 2% gated. Documented in '
     '§3.4.5 hallucination evaluation.'),
    ('I4 Topic-cluster equivalence across jurisdictions',
     'Naive bag-of-words clustering grouped clauses that shared '
     'keywords but had different legal meaning. "Consent" in '
     'PDPL carries different procedural weight from "consent" '
     'in DPDPA, but term overlap produced false equivalence '
     'verdicts.',
     'Replaced bag-of-words with BGE embedding clustering plus '
     'term-dictionary lookup and per-jurisdiction labelling. '
     'Comparison output now distinguishes equivalent, similar, '
     'and different verdicts per cluster.'),
    ('I5 Naive cross-jurisdictional comparison risk',
     'Initial retrieval returned chunks from any jurisdiction '
     'for a comparison query, producing misleading equivalence '
     'verdicts when a Bahraini chunk happened to outrank an '
     'Indian one on semantic similarity alone.',
     'Added mandatory jurisdiction-scope filter on every '
     'comparison run, jurisdiction-scoped retrieval queries, '
     'and per-jurisdiction Document fields. Auto-routing '
     'classifier carried into future work.'),
    ('I6 Long-running reasoning under HTTP timeouts',
     'Mapping and comparison workflows can take 30 seconds to '
     'several minutes. Running them synchronously inside a '
     'request handler would exceed standard HTTP timeouts and '
     'block the worker thread.',
     'Moved long-running jobs to background subprocesses with '
     'WebSocket progress streams and HTMX polling fallback. '
     'The analyst sees live progress without holding an HTTP '
     'connection open.'),
    ('I7 Audit-log immutability with no native append-only',
     'SQLite has no native append-only mode, and Django ORM '
     'allows UPDATE and DELETE by default. The audit trail '
     'guarantee depended on enforcement we did not yet have.',
     'Added an application-level guard that rejects every '
     'UPDATE and DELETE against AuditLog, validated by '
     'functionality test 9 and AI evaluation §3.4.5. Verified '
     'the invariant holds against direct ORM access.'),
]


FUTURE_WORK = [
    ('Automatic jurisdiction routing',
     'Classifier infers probable jurisdictions from query '
     'semantics.',
     'Closes the methodology-review gap, removes manual '
     'jurisdiction selection.'),
    ('Agentic Noor',
     'Proactive notifications (new CBB circular, suggest gap '
     'analysis), actions gated by analyst approval.',
     'From reactive Copilot to active agent, mirrors Harvey '
     'and Hebbia direction.'),
    ('Deep multi-hop research',
     'Conversational research over multiple regulations with '
     'full reasoning trace exposed.',
     'Beyond single-turn Q&A, pattern proven by Harvey in '
     'legal-tech.'),
    ('Breach notification orchestration',
     'Per-jurisdiction notification drafts with deadline '
     'countdowns (PDPL/GDPR 72 h, CBB immediate, DPDPA ASAP).',
     'Unsolved operational problem across the GCC.'),
    ('Cross-framework control mapping',
     'Corpus extended to NIST CSF 2.0, ISO 27001:2022, CBB CSM, '
     'SAMA CSF, NCA ECC, PCI DSS 4.0, SWIFT CSP.',
     'Positions CJPCA in the OneTrust/Drata/Vanta category for '
     'the GCC.'),
    ('Threat intelligence × compliance',
     'Connect MITRE ATT&CK, CISA KEV, sector advisories to '
     'regulatory obligations.',
     'Turns compliance into operational defence.'),
    ('Third-party risk analyser',
     'Upload vendor SOC 2, ISO cert, DPA. Output: '
     'per-jurisdiction risk score and contract amendments.',
     'Own product category (Panorays, SecurityScorecard).'),
    ('Synthetic compliance red-teaming',
     'Generate scenarios (KW customer deletion of data in IN) '
     'and test whether policies handle them.',
     'Unit tests for compliance posture.'),
    ('DPIA and transfer wizard',
     'Guided DPIA and cross-border transfer assessment.',
     'High BBK relevance (BH/IN/KW transfers).'),
    ('Compliance simulation sandbox',
     'What-if engine: adopt this policy, simulate gap deltas, '
     'risk change, downstream impact.',
     'Staging environment for compliance decisions.'),
    ('Risk scoring and prioritisation',
     'Score gaps by penalty severity, enforcement likelihood, '
     'business impact, remediation effort.',
     'Flat gap register becomes prioritised queue.'),
    ('Voice-first meeting mode',
     'Noor joins Zoom/Teams, surfaces citations live, generates '
     'minutes mapped to obligations.',
     'Granola/Fireflies pattern specialised for compliance.'),
    ('Infrastructure hardening',
     'Encrypted backups with hash-chain verification, zero-trust '
     'segmentation around Tier-B, CI penetration testing.',
     'Closes residual cyber risks (zero-day, lateral movement, '
     'backup tampering).'),
    ('Live regulatory monitoring',
     'Scheduled crawl of gazette feeds, alerts on new circulars.',
     'Keeps corpus current, feeds the agentic flow above.'),
    ('Interactive graph analytics',
     'AI-driven graphs over obligation network, topic clusters, '
     'cross-jurisdiction overlaps.',
     'Better discoverability for visual analysts.'),
    ('Onboarding and metadata autofill',
     'Mascot for first-time users, automatic document-metadata '
     'extraction.',
     'Closes the §3.4.4 learnability gap.'),
]


REFERENCES = [
    'Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., '
    '& Fritz, M. (2023). Not what you\'ve signed up for: '
    'Compromising real-world LLM-integrated applications with '
    'indirect prompt injection. In Proceedings of the 16th ACM '
    'Workshop on Artificial Intelligence and Security (pp. 79-90). '
    'Association for Computing Machinery. '
    'https://doi.org/10.1145/3605764.3623985',

    'Huang, L., Yu, W., Ma, W., Zhong, W., Feng, Z., Wang, H., Chen, '
    'Q., Peng, W., Feng, X., Qin, B., & Liu, T. (2025). A survey on '
    'hallucination in large language models: Principles, taxonomy, '
    'challenges, and open questions. ACM Transactions on Information '
    'Systems, 43(2), Article 42. https://doi.org/10.1145/3703155',

    'Liu, Y., Jia, Y., Geng, R., Jia, J., & Gong, N. Z. (2024). '
    'Formalizing and benchmarking prompt injection attacks and '
    'defenses. In Proceedings of the 33rd USENIX Security Symposium '
    '(pp. 1831-1847). USENIX Association.',

    'McKay, K. A., & Cooper, D. A. (2019). Guidelines for the '
    'selection, configuration, and use of Transport Layer Security '
    '(TLS) implementations (NIST Special Publication 800-52 Rev. 2). '
    'National Institute of Standards and Technology. '
    'https://doi.org/10.6028/NIST.SP.800-52r2',

    'National Institute of Standards and Technology. (2024). The NIST '
    'Cybersecurity Framework (CSF) 2.0 (NIST Cybersecurity White '
    'Paper, NIST CSWP 29). https://doi.org/10.6028/NIST.CSWP.29',

    'OWASP Foundation. (2021). OWASP Top 10:2021. '
    'https://owasp.org/Top10/2021/',

    'OWASP Foundation. (2025). OWASP Top 10 for Large Language Model '
    'applications 2025. '
    'https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/',

    'Tarandach, I., & Coles, M. J. (2020). Threat modeling: A '
    'practical guide for development teams. O\'Reilly Media.',

    'Temoshok, D., Proud-Madruga, D., Choong, Y.-Y., Galluzzo, R., '
    'Gupta, S., LaSalle, C., Lefkovitz, N., & Regenscheid, A. '
    '(2025). Digital identity guidelines (NIST Special Publication '
    '800-63-4). National Institute of Standards and Technology. '
    'https://doi.org/10.6028/NIST.SP.800-63-4',
]


# -------------------------------------------------------------------------
# WRITERS
# -------------------------------------------------------------------------

def write_4_1(doc):
    add_heading(doc, '4. Discussion and Conclusion', level=1)
    add_heading(doc, '4.1 System Functionality', level=2)
    add_paragraph(
        doc,
        'The final CJPCA platform delivers every functional '
        'pillar of the §3.2 design without material compromise. '
        'The ingestion pipeline parses PDF, DOCX, and HTML '
        'through Docling, chunks with section awareness, embeds '
        'with BGE-small-en-v1.5, scans every chunk through the '
        'two-tier injection defence, and writes cleared chunks '
        'into both ChromaDB and SQLite FTS5. The hybrid '
        'retriever fuses BM25 and vector similarity via RRF at '
        'k=60, then reranks a 20-candidate pool with an '
        'ms-marco MiniLM cross-encoder. The reasoning agent '
        'runs as a LangGraph state machine with draft, verify, '
        'correct, finalise, and fallback nodes. Every clause '
        'passes the verbatim citation verifier, and the '
        'cross-encoder NLI score gates each output before an '
        'analyst sees it.',
    )
    add_paragraph(
        doc,
        'The web layer wraps this pipeline in 10 Django apps, 96 '
        'URL routes, and 75 HTMX-and-Alpine templates behind a '
        '16-layer middleware chain delivering TLS 1.3, HSTS '
        'preload, CSP 4.x, BH/IN/KW GeoFence, django-axes '
        'lockout, TOTP MFA, three-role RBAC, and an append-only '
        'AuditLog with 28 action constants. Every export carries '
        'a SHA-256 hash chain footer for external tamper '
        'detection. This functionality maps one-to-one onto the '
        'seven-tier defence-in-depth architecture of Figure 17. '
        'The cross-encoder NLI score, verbatim citation verifier, '
        'and SafeFallback typed-empty report together provide '
        'audit-defensible AI output, addressing the hallucination '
        'risks catalogued by Huang et al. (2025) and the '
        'prompt-injection attack surface documented by Greshake '
        'et al. (2023) and Liu et al. (2024). Every design '
        'element survived implementation, nothing was silently '
        'dropped.',
    )


def write_4_2(doc):
    add_heading(doc, '4.2 Summary of Achieved Objectives', level=2)
    add_paragraph(
        doc,
        'Chapter 1 defined ten objectives scoped to Bahrain, '
        'India, and Kuwait. Five technical (T1-T5) cover hybrid '
        'retrieval, the reasoning workflows, the Copilot, the '
        'reviewer platform, and security-by-design. Five general '
        '(G1-G5) cover the operational outcomes: reduced review '
        'time, gap identification across the three regimes, BBK '
        'digital-transformation support, corpus scalability '
        'without code changes, and tamper-evident audit '
        'readiness. The table records achievement status against '
        'each measurable success criterion.',
    )
    add_caption(doc, 'Table.',
                'Objectives, achievement status, and evidence.')
    add_table(
        doc,
        headers=['Objective', 'Description', 'Status', 'Evidence'],
        rows=OBJECTIVES,
        widths_cm=[3.5, 5.5, 1.7, 5.3],
        body_size=8,
    )
    add_paragraph(
        doc,
        'All ten objectives are evidenced by the §3.4 results. '
        'T1 through T5 are demonstrated by the hybrid retriever '
        'beating single-lane baselines on hit-rate@1, the '
        'LangGraph agent emitting schema-valid Pydantic outputs '
        'with verbatim citations 96% first-pass, the Copilot '
        'respecting scope, the three roles transitioning through '
        'the Draft-Reviewed-Approved lifecycle with role-at-time '
        'evidence, and the seven-tier defence-in-depth model '
        'mapped onto the OWASP Top 10.',
    )
    add_paragraph(
        doc,
        'G1 through G5 are evidenced by operational outcomes: '
        'mapping completed in under 12 minutes against a '
        'multi-hour baseline, every gap carries a verbatim '
        'citation, the reviewer platform was delivered for BBK '
        'demonstration, documents are added through the standard '
        'upload path without code changes, and the append-only '
        'AuditLog with SHA-256 export chain provides the '
        'evidence trail regulators expect.',
    )
    add_paragraph(
        doc,
        'Two caveats deserve honest reflection. T3 Copilot scope '
        'adherence reached 95%, with the residual 5% in queries '
        'spanning two documents where scope resolution is '
        'conservative, a calibration item rather than a safety '
        'failure. T2 first-pass citation rate of 96% relies on '
        'the retry node, and where retry misfires the typed-empty '
        'SafeFallback absorbs the failure quietly, the right '
        'safety posture but an opportunity cost a stronger retry '
        'could reduce.',
    )


def write_4_3(doc):
    add_heading(doc,
                '4.3 Project Issues with Proposed Solutions and Actions',
                level=2)
    add_paragraph(
        doc,
        'Seven system-engineering challenges arose during '
        'implementation, spanning the retrieval pipeline, the '
        'reasoning agent, the comparison logic, the request '
        'lifecycle, and the audit subsystem. Each was tracked, '
        'root-caused, and resolved before §3.4 testing.',
    )
    add_caption(doc, 'Table.', 'Project issues, root cause, and action.')
    add_table(
        doc,
        headers=['Issue', 'Root cause', 'Action taken or proposed'],
        rows=ISSUES,
        widths_cm=[3.8, 6.0, 6.2],
        body_size=8,
    )
    add_paragraph(
        doc,
        'The chunking and citation-verifier issues were the most '
        'instructive because each forced a redesign rather than '
        'a tweak. Naive section-aware chunking lost legal '
        'context when a clause sat several levels deep in an '
        'article hierarchy. The fix preserved ancestor headings '
        'inside the chunk text, invisible to readers but '
        'anchoring the embedding. The citation verifier '
        'rejecting valid paraphrases only surfaced once the '
        'system was running, since the reasoning agent had no '
        'incentive to quote verbatim until the verifier demanded '
        'it. Prompt engineering plus an explicit retry node '
        'lifted the first-pass rate into production territory.',
    )
    add_paragraph(
        doc,
        'The topic-cluster and cross-jurisdictional issues were '
        'expressions of the same mistake: treating regulation '
        'chunks as fungible text-similarity inputs when privacy '
        'regulation is jurisdiction-aware by nature. The '
        'resolution (BGE clustering, term dictionary, mandatory '
        'jurisdiction filter) closed the methodology gap raised '
        'during BBK consultation review, with the auto-routing '
        'classifier carried into future work. If the project '
        'were restarted today, jurisdiction-awareness would be a '
        'first-class concept in the data model from day one, '
        'not retrofitted, and the chunking strategy would be '
        'validated against a held-out evaluation set before any '
        'downstream pipeline was wired in.',
    )


def write_4_4(doc):
    add_heading(doc,
                '4.4 Legal, Ethical, Social, and Professional Issues',
                level=2)
    add_paragraph(
        doc,
        'Compliance technology built for a regulated bank '
        'operates inside a dense web of legal, ethical, social, '
        'and professional considerations. The four subsections '
        'below identify the most salient items for CJPCA and the '
        'corresponding mitigations woven into the design.',
    )

    add_heading(doc, '4.4.1 Legal Issues', level=3)
    add_paragraph(
        doc,
        'The platform processes regulatory documents from three '
        'jurisdictions with distinct data-protection regimes: '
        'Bahrain PDPL 2018, Indian DPDPA 2023, and Kuwait Law 20 '
        'of 2014 with supporting decrees. CJPCA itself does not '
        'process personal data in the regulator-defined sense, '
        'but analyst accounts and AuditLog records do qualify '
        'and are stored on the on-premises host within Bahrain '
        'per NIST digital identity guidance (Temoshok et al., '
        '2025) and TLS guidance from McKay and Cooper (2019). '
        'The Tier-B injection judge call constitutes a '
        'cross-border data flow, mitigated by sending only the '
        'suspect chunk in spotlight delimiters with no analyst '
        'identifier. Every dependency carries a permissive '
        'license (MIT, Apache 2.0, BSD) compatible with BBK '
        'internal deployment.',
    )

    add_heading(doc, '4.4.2 Ethical Issues', level=3)
    add_paragraph(
        doc,
        'The most acute ethical risk in AI-assisted compliance '
        'is false confidence. An analyst who trusts an '
        'AI-generated clause without verifying its source can '
        'produce an audit-failing mapping. CJPCA closes this '
        'through three design choices. First, every clause is a '
        'verbatim span, enforced by the citation verifier. '
        'Second, the NLI score gates outputs below threshold, '
        'falling back to a typed-empty SafeFallback report '
        'rather than a plausible-but-unverified answer, '
        'consistent with the hallucination mitigation literature '
        '(Huang et al., 2025). Third, the role-at-time AuditLog '
        'snapshot records who made every decision so '
        'responsibility cannot be displaced onto the AI. The '
        'platform is positioned as an analyst tool, not a '
        'replacement, and the workflow makes this explicit.',
    )

    add_heading(doc, '4.4.3 Social Impact', level=3)
    add_paragraph(
        doc,
        'Cross-jurisdictional compliance review is currently a '
        'manual practice concentrated in large international '
        'banks with in-house legal teams. Smaller regional '
        'institutions either accept slow manual review or pay '
        'external consultancies. CJPCA reduces per-mapping time '
        'by an order of magnitude while preserving the audit '
        'trail regulators expect, making that capability '
        'accessible to mid-size institutions. A corresponding '
        'risk of role displacement among entry-level analysts '
        'exists, mitigated by positioning the platform as an '
        'augmentation tool with the analyst as decision-maker '
        'rather than an autonomous ruling engine.',
    )

    add_heading(doc, '4.4.4 Professional Issues', level=3)
    add_paragraph(
        doc,
        'As an ICT professional designing for a regulated '
        'environment, responsibility extends beyond functional '
        'correctness to defensible engineering. Three threats '
        'were considered. AI overclaim that the verifier or NLI '
        'score gives certainty would damage trust, so the thesis '
        'frames these as guards that reduce but do not eliminate '
        'hallucination risk. A rushed deployment without the §3.4 '
        'test plan would put the engineer on the hook for any '
        'post-launch failure, so participant coverage and '
        'rubric-mapped tests are recorded as protection. Security '
        'misconfiguration in a financial deployment carries '
        'reputational risk, addressed by the defence-in-depth '
        'threat model (Tarandach and Coles, 2020), OWASP Top 10 '
        'coverage in §3.2.8 (OWASP Foundation, 2021, 2025), and '
        'the residual-risk register.',
    )


def write_4_5(doc):
    add_heading(doc, '4.5 Future Work', level=2)
    add_paragraph(
        doc,
        'The following extensions are recommended. Each fits '
        'inside the existing architecture without redesigning '
        'the security model or reasoning core. They group into '
        'four categories: AI capability (agentic Noor, multi-hop '
        'research, red-teaming, simulation), product surface '
        '(GRC control mapping, breach orchestration, DPIA, '
        'third-party risk), cyber infrastructure (encrypted '
        'backups, zero-trust segmentation, pen-testing, '
        'regulatory monitoring), and analyst experience '
        '(auto-routing, onboarding mascot, graph analytics).',
    )
    add_caption(doc, 'Table.', 'Recommended future-work items.')
    add_table(
        doc,
        headers=['Item', 'Scope', 'Rationale and category'],
        rows=FUTURE_WORK,
        widths_cm=[3.8, 6.0, 6.2],
        body_size=8,
    )
    add_paragraph(
        doc,
        'The highest-value addition is automatic jurisdiction '
        'routing, the natural next reduction in analyst manual '
        'effort. The next tier sits in agentic Noor and breach '
        'notification orchestration. Harvey and Hebbia have '
        'proven appetite for deep conversational research, and '
        'breach orchestration addresses an unsolved operational '
        'problem across the GCC. Cyber-aware items (encrypted '
        'backups, zero-trust segmentation, CI pen-testing) close '
        'residual risks rather than fix current defects but are '
        'equally important.',
    )


def write_4_6(doc):
    add_heading(doc, '4.6 Synopsis of Experience', level=2)
    add_paragraph(
        doc,
        'CJPCA has been the most technically demanding and '
        'professionally formative project I have undertaken. '
        'The breadth (16-layer security middleware, LangGraph '
        'state machine, Django Channels WebSocket, SHA-256 hash '
        'chain) required learning a stack at a depth beyond '
        'coursework. Four lessons stand out.',
    )
    add_paragraph(
        doc,
        'First, security cannot be added at the end. Every '
        'architectural choice ripples into the threat model, and '
        'changes made late either compromise the design or '
        'require extensive rework. Even with the seven-tier '
        'model specified before implementation began, several '
        'details (idle timeout, GeoFence allowlist, MFA '
        'enrolment order) required late adjustment.',
    )
    add_paragraph(
        doc,
        'Second, AI safety is engineering, not marketing. The '
        'citation verifier, NLI gate, and SafeFallback together '
        'absorb several hundred lines of code that would not '
        'exist in a naive RAG implementation. The NLI threshold '
        'calibration was the moment I genuinely understood this '
        'distinction. Watching a 0.1 shift in threshold flip '
        'analyst-visible outputs from "useful but slightly '
        'wrong" to "honestly empty" made it clear that safety '
        'parameters are empirical not aspirational. Documenting '
        'the threat model alongside the architecture, rather '
        'than treating safety as a README claim, was the most '
        'valuable habit acquired.',
    )
    add_paragraph(
        doc,
        'Third, infrastructure documentation pays back fast. '
        'Pinning dependencies, capturing environment variables, '
        'and recording middleware order with justification turned '
        'a complex system into something reproducible on a fresh '
        'machine. Fourth, working with a real stakeholder '
        'sharpened every decision under the question "how would '
        'an analyst explain this to an auditor". The combined '
        'skill set (Django, LangGraph, bounded-hallucination RAG, '
        'two-tier injection defence, threat modelling, '
        'regulated-industry UX) maps onto financial-sector and '
        'government ICT roles where compliance literacy plus AI '
        'engineering remains rare.',
    )


def write_4_7(doc):
    add_heading(doc, '4.7 Conclusion', level=2)
    add_paragraph(
        doc,
        'This project set out to determine whether a compliance '
        'analyst at a regional bank could be given an AI-assisted '
        'workspace that compresses cross-jurisdictional analysis '
        'from days to minutes while preserving audit '
        'defensibility. CJPCA answers affirmatively, evidenced '
        'by 100% functionality pass rate across 56 cases, six '
        'acceptance scenarios passing across analyst, reviewer, '
        'admin, and external-observer perspectives, and a 4.6 '
        'of 5 usability rating. The platform demonstrates that '
        'RAG can be operated inside a regulated financial '
        'environment with verbatim grounding, two-tier injection '
        'defence, append-only audit, and on-premises hosting, '
        'none individually novel but together composing a '
        'deployable system rather than a research prototype.',
    )
    add_paragraph(
        doc,
        'The new knowledge contributed is a reproducible '
        'deployment pattern. The combination of a hybrid '
        'retriever, a LangGraph agent governed by a verbatim '
        'citation verifier, a cross-encoder NLI gate, and a '
        'typed-empty SafeFallback behind a seven-tier '
        'defence-in-depth shell is not a research result, but '
        'a recipe that did not previously exist as a published '
        'pattern for regulated-domain RAG. Each component '
        'appears separately in the literature, the contribution '
        'is that the integration is engineerable, measurable, '
        'and survived BBK consultation review. The seven-tier '
        'model mapped onto the OWASP Top 10 (OWASP Foundation, '
        '2021), OWASP Top 10 for LLM Applications (OWASP '
        'Foundation, 2025), and NIST Cybersecurity Framework '
        '(National Institute of Standards and Technology, 2024) '
        'shows AI safety and web-application controls can '
        'coexist without compromise.',
    )
    add_paragraph(
        doc,
        'Several open questions remain. How does the citation '
        'verifier behave on regulations whose normative weight '
        'comes from numbered article references rather than '
        'quotable spans? Can the NLI gate be calibrated per '
        'jurisdiction so legal-interpretation norms are '
        'respected? Could the auto-routing classifier generalise '
        'to a multi-domain compliance tool spanning AML, KYC, '
        'and operational risk alongside privacy?',
    )
    add_paragraph(
        doc,
        'For BBK, CJPCA reduces per-mapping burden by an order '
        'of magnitude, the role-at-time audit trail provides the '
        'evidence regulators expect, and on-premises hosting '
        'satisfies CBB data-residency. For the wider sector, '
        'smaller institutions can operate compliance review at '
        'the speed of larger ones, with implications for '
        'competitive parity in regional banking. CJPCA is not '
        'the final form of cross-jurisdictional compliance '
        'analysis, but a working starting point an analyst can '
        'use tomorrow and a thesis a follow-on researcher can '
        'build from.',
    )


def write_references(doc):
    add_heading(doc, 'References cited in this chapter', level=2)
    for ref in REFERENCES:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(1.0)
        p.paragraph_format.first_line_indent = Cm(-1.0)
        p.paragraph_format.space_after = Pt(8)
        run = p.add_run(ref)
        set_run_style(run, color=DARK_GRAY, size=10.5)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '4_discussion.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'4_discussion_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    write_4_1(doc)
    write_4_2(doc)
    write_4_3(doc)
    write_4_4(doc)
    write_4_5(doc)
    write_4_6(doc)
    write_4_7(doc)
    write_references(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
