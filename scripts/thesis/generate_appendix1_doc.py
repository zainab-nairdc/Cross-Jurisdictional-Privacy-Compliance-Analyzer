"""Generate Appendix 1 — Requirements Elicitation Evidence.

Format matches the Grant Thornton / SolarMap thesis sample:
  - Project header (Title, Manager, Date Created/Updated)
  - Multiple interview tables organised by theme, each with Question/Answer/Requirement columns
  - Research table with Topic / Findings & APA Reference / Requirement
  - Document analysis table with Reference / Notes / Requirement
  - Feasibility study table with Topic / Findings / Requirement
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt, RGBColor


NAVY = RGBColor(0x00, 0x25, 0x83)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def _set_run_style(run, *, bold=False, color=NAVY, size=10):
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.size = Pt(size)


def add_para(doc, text, *, size=11, bold=False, italic=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = NAVY
    run.font.size = Pt(size)


def add_heading(doc, text, level=1, size=14):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.size = Pt(size)


def add_subheading(doc, text, *, size=12):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.size = Pt(size)


def add_project_header(doc, title, manager, created, updated):
    """Two-column project header table at the top of each interview."""
    t = doc.add_table(rows=2, cols=2)
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.autofit = False
    for col_idx in (0, 1):
        for cell in t.columns[col_idx].cells:
            cell.width = Cm(8.5)
    # Row 1
    t.rows[0].cells[0].text = f'PROJECT Title: {title}'
    t.rows[0].cells[1].text = f'PROJECT MANAGER: {manager}'
    # Row 2
    t.rows[1].cells[0].text = f'DATE CREATED: {created}'
    t.rows[1].cells[1].text = f'DATE LAST UPDATED: {updated}'
    for row in t.rows:
        for cell in row.cells:
            shade_cell(cell, 'E5E8EF')
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in paragraph.runs:
                    _set_run_style(run, bold=True, color=NAVY, size=10)


def add_interview_header(doc, date_time, interviewee):
    """Single-row interview metadata table."""
    t = doc.add_table(rows=1, cols=2)
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.autofit = False
    for col_idx in (0, 1):
        for cell in t.columns[col_idx].cells:
            cell.width = Cm(8.5)
    t.rows[0].cells[0].text = f'Interview Date and Time: {date_time}'
    t.rows[0].cells[1].text = f'Interviewee: {interviewee}'
    for cell in t.rows[0].cells:
        shade_cell(cell, 'FFF7E6')
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            for run in paragraph.runs:
                _set_run_style(run, bold=True, color=NAVY, size=10)


def add_full_width_banner(doc, text, *, fill='FFB800', text_color=NAVY,
                          size=11, total_width_cm=17.0):
    """Single-row, single-cell full-width banner (like 'Interview Gatherings')."""
    t = doc.add_table(rows=1, cols=1)
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.autofit = False
    for cell in t.columns[0].cells:
        cell.width = Cm(total_width_cm)
    cell = t.rows[0].cells[0]
    cell.text = text
    shade_cell(cell, fill)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    para = cell.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in para.runs:
        _set_run_style(run, bold=True, color=text_color, size=size)


def add_theme_banner(doc, text, *, total_width_cm=17.0):
    """Theme-section banner (light navy fill, centered bold)."""
    add_full_width_banner(doc, text, fill='E5E8EF', text_color=NAVY,
                          size=11, total_width_cm=total_width_cm)


def add_qa_table(doc, rows, col1='Question', col2='Answer', col3='Requirement',
                 widths=(5.5, 7.5, 4.0)):
    """Three-column Q&A table."""
    t = doc.add_table(rows=1 + len(rows), cols=3)
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.autofit = False
    for col_idx, w in enumerate(widths):
        for cell in t.columns[col_idx].cells:
            cell.width = Cm(w)
    # Header
    header = t.rows[0]
    for i, h in enumerate([col1, col2, col3]):
        header.cells[i].text = h
        shade_cell(header.cells[i], '002583')
        header.cells[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = header.cells[i].paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            _set_run_style(run, bold=True, color=WHITE, size=10)
    # Data rows
    for r_idx, vals in enumerate(rows, 1):
        row = t.rows[r_idx]
        for c_idx, val in enumerate(vals):
            cell = row.cells[c_idx]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            # Split on double newlines so APA references render as separate paragraphs.
            parts = val.split('\n\n')
            cell.text = parts[0]
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in paragraph.runs:
                    _set_run_style(run, color=NAVY, size=10)
            for extra in parts[1:]:
                p = cell.add_paragraph(extra)
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in p.runs:
                    _set_run_style(run, color=NAVY, size=10)


def main():
    base = Path(__file__).resolve().parent.parent
    out_path = base / 'thesis_appendix_1_elicitation_evidence.docx'
    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = base / f'thesis_appendix_1_elicitation_evidence_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()

    for section in doc.sections:
        section.top_margin    = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin   = Cm(2.0)
        section.right_margin  = Cm(2.0)

    # ── Title ──
    title = doc.add_heading('Appendix 1 — Requirements Elicitation Evidence', level=0)
    for run in title.runs:
        run.font.color.rgb = NAVY

    add_para(
        doc,
        "This appendix records the underlying evidence gathered during the "
        "requirements-elicitation phase referenced in Section 3.1.1, organised by "
        "elicitation technique: stakeholder interviews, research, document analysis, "
        "and the technical feasibility study."
    )

    PROJECT_TITLE = 'Cross-Jurisdictional Privacy Compliance Analyzer (CJPCA)'
    PROJECT_MGR   = 'Researcher (Bahrain Polytechnic)'

    # ────────────────────────────────────────────────────────────
    # 1. INTERVIEW RESULTS
    # ────────────────────────────────────────────────────────────
    add_heading(doc, '1. Interview Results', level=1, size=14)
    add_para(doc, 'Three interviews were conducted with project stakeholders. Each interview is recorded below with its metadata, themes covered, and the requirements derived from each question.')

    # ── 1.1 BBK Interview ──
    add_subheading(doc, '1.1 BBK Stakeholder Interview — Project Scope and Compliance Conventions')
    add_project_header(doc, PROJECT_TITLE, PROJECT_MGR, '15 Sep 2025', '5 Apr 2026')
    add_interview_header(doc, '15 September 2025, 10:00 AM', 'BBK Compliance Lead (via NAIRDC PM proxy)')
    add_full_width_banner(doc, 'Interview Gatherings')

    add_theme_banner(doc, 'Theme: Project Scope and Workflow Coverage')
    add_qa_table(doc, [
        ('What is the primary compliance workflow that the system should automate?',
         'Comparing requirements across our three jurisdictional regimes (Bahrain, India, Kuwait) when assessing whether a single internal policy is compliant. Currently this is done manually by reviewing each regulation separately, which takes weeks per topic.',
         'Two-regulation comparison workflow with cross-jurisdictional support'),
        ('What document types should the system ingest?',
         'Both external regulations (Bahrain PDPL, India DPDP, Kuwait CBK rules) and our own internal policies, governance documents, and operational SOPs. The system should treat them as one searchable corpus.',
         'Ingest regulatory corpus and internal BBK policy artefacts'),
        ('How granular should the comparison be?',
         'Each regulation has multiple obligations; we need them compared one by one, not as a whole document. Otherwise the output is too vague to be useful.',
         'Per-obligation comparison rather than document-level'),
        ('Should comparisons treat all regimes equally?',
         'No — some regimes are thinner than others. If a topic is absent from one jurisdiction, that is still useful information for us. We need that flagged, not hidden.',
         "Asymmetric equivalence categories including 'absent' as a valid finding"),
    ])

    add_theme_banner(doc, 'Theme: Compliance Vocabulary and Coverage Classification')
    add_qa_table(doc, [
        ('What vocabulary do you currently use for coverage?',
         'We use four states: Fully Covered, Partially Covered, Requires Review, and Not Covered. These align with how our auditors expect to see findings.',
         'Four-state coverage classification (Fully / Partially / Requires Review / Not Covered)'),
        ('How do you triage compliance gaps?',
         'High, Medium, and Low severity — same as our existing risk register, so the output integrates with our current workflow.',
         'Three-tier severity vocabulary (High / Medium / Low)'),
        ('Who should be allowed to do what in the system?',
         'Three roles: an analyst who does the initial mapping, a reviewer who validates findings, and an administrator for system management. Each must only see what their role permits.',
         'Three-role RBAC: Analyst, Reviewer, Administrator'),
    ])

    add_theme_banner(doc, 'Theme: Reviewer Workflow and Export')
    add_qa_table(doc, [
        ('Should AI-generated findings be auto-approved?',
         'Absolutely not. Every AI finding must go through a reviewer queue before being treated as authoritative. We need full human oversight before anything goes to a compliance committee.',
         'Reviewer validation queue with explicit approval workflow'),
        ('What actions should the reviewer be able to take on each finding?',
         'Approve, reject, or modify the finding, with a note explaining the decision. The note becomes part of the audit record.',
         'Approve / reject / modify actions per finding, with reviewer notes'),
        ('What export formats are needed for downstream audit?',
         'XLSX for spreadsheet handover to risk teams, DOCX for narrative reports, and PDF for archival. All three are required.',
         'Multi-format export: XLSX, DOCX, and PDF'),
    ])

    doc.add_paragraph()

    # ── 1.2 NAIRDC Interview ──
    add_subheading(doc, '1.2 NAIRDC Interview — Workflow Coordination and Reporting')
    add_project_header(doc, PROJECT_TITLE, PROJECT_MGR, '15 Sep 2025', '5 Apr 2026')
    add_interview_header(doc, '12 February 2026, 14:00 PM', 'NAIRDC Project Manager')
    add_full_width_banner(doc, 'Interview Gatherings')

    add_theme_banner(doc, 'Theme: Workflow Coordination Between Analysts and Reviewers')
    add_qa_table(doc, [
        ('How should the system handle the handoff between analysts and reviewers?',
         "Once an analyst completes a mapping or comparison, the work should be queued for the reviewer's attention. Reviewers need to see what's pending, who created it, and when.",
         'Workflow handoff with a reviewer validation queue'),
        ('How should completed analyses be tracked?',
         'We need a clear status for each item — pending, under review, approved, rejected — and a way to see the history of who changed what.',
         'Status lifecycle tracking with auditable transitions'),
    ])

    add_theme_banner(doc, 'Theme: Reporting and Auditability')
    add_qa_table(doc, [
        ('What outputs do compliance teams expect from analyses?',
         'Reports they can share with auditors and management, in standard formats they already use.',
         'Multi-format export (XLSX, DOCX, PDF)'),
        ('How important is traceability in the final output?',
         'Very — every finding must be traceable back to its source. Examiners and auditors will ask where a particular conclusion came from.',
         'Citation-traceable outputs linked to source documents'),
    ])

    add_theme_banner(doc, 'Theme: Access and Role Management')
    add_qa_table(doc, [
        ('Who should have access to the system?',
         'Analysts and reviewers as day-to-day users. An administrator should manage accounts. Self-registration should not be allowed.',
         'Role-based access with administrator-managed user lifecycle'),
        ('Should AI findings be released without human review?',
         "No — the system should support the analyst's work, not replace the human review. Every finding goes through a reviewer before being treated as final.",
         'Mandatory human review before AI findings are treated as authoritative'),
    ])

    doc.add_paragraph()

    doc.add_paragraph()

    # ────────────────────────────────────────────────────────────
    # 2. RESEARCH RESULTS
    # ────────────────────────────────────────────────────────────
    add_heading(doc, '2. Research Results', level=1, size=14)
    add_para(doc, 'The following research areas and references informed the technical requirements that no stakeholder would have articulated directly.')
    add_qa_table(doc, [
        ('Hybrid retrieval for RAG (semantic + keyword)',
         'Hybrid retrieval — combining dense (semantic) search with sparse (BM25) search and fusing the ranked lists via reciprocal rank fusion (RRF) — outperforms either component alone, especially for legal and technical text where exact terms and identifiers matter. Recent benchmarks report substantial improvement over dense-only retrieval (Rackauckas, 2024; Gao et al., 2024).',
         'Hybrid retrieval combining semantic and keyword search with reciprocal rank fusion'),
        ('Prompt-injection defence for RAG systems',
         'Documents in the retrieved context can contain hidden instructions targeting the LLM, such as "ignore previous instructions" payloads. Indirect prompt injection through retrieved content is a documented attack class; current defences include pattern-based detection, instruction-detection classifiers, and isolation of untrusted content within structured prompts (Wen et al., 2025). OWASP lists prompt injection as the highest risk for LLM applications in 2025 (OWASP Foundation, 2025).',
         'Two-tier prompt-injection scanner with quarantine queue'),
        ('Citation faithfulness for RAG outputs',
         "Made-up citations are the most common hallucination mode in retrieval-augmented systems. Verifying that an LLM's quoted text actually appears in a retrieved chunk catches the majority of fabricated citations (Tamber et al., 2025). Recent work further distinguishes citation correctness from citation faithfulness, arguing that an answer can be technically correct yet not genuinely supported by its cited sources (Wallat et al., 2024).",
         'Citation verification of every AI-generated quote against retrieved chunks'),
        ('Grounding evaluation for AI outputs',
         "Beyond binary citation checks, a continuous grounding score quantifies how well an AI's answer is semantically supported by retrieved evidence. Recent benchmarks demonstrate that small specialised models can reach state-of-the-art accuracy on grounding evaluation at a fraction of the cost of large LLM-as-judge approaches (Jacovi et al., 2025; Tang et al., 2024).",
         'Per-output hallucination risk score using a grounding evaluation model'),
        ('Agentic workflow orchestration with verify-correct loops',
         'Iterative agentic orchestration — draft, verify, correct, finalise, and fallback — with bounded retries produces more reliable structured outputs than single-shot prompting. Explicit workflow structures with code-represented nodes and execution feedback outperform single-prompt baselines on benchmark tasks while enabling smaller models to match larger ones (Zhang et al., 2025).',
         'Verify-and-correct state-machine orchestration with bounded retries'),
        ('AI risk governance for regulated industries',
         'Banking systems operating generative AI require risk-management controls specific to LLM behaviour: confabulation (hallucination), data leakage, information-integrity erosion, harmful bias, and value-chain dependencies. The Generative AI Profile of the NIST AI Risk Management Framework catalogues twelve risk areas and over two hundred suggested actions tailored to generative AI, providing a structured baseline for compliance-driven deployment (NIST, 2024).',
         'Confabulation control, data-leakage controls, bias monitoring, and audit logging consistent with NIST AI 600-1 guidance'),
    ], col1='Research Topic', col2='Findings', col3='Requirement',
       widths=(4.0, 9.0, 4.0))

    doc.add_paragraph()

    # ────────────────────────────────────────────────────────────
    # 3. DOCUMENT ANALYSIS RESULTS
    # ────────────────────────────────────────────────────────────
    add_heading(doc, '3. Document Analysis Results', level=1, size=14)
    add_para(doc, 'The following observations were made during analysis of the project brief, the regulatory corpus, and existing BBK security practice.')
    add_qa_table(doc, [
        ('Bahrain Personal Data Protection Law (PDPL) — Law 30 of 2018, Orders 42–50 of 2022',
         'Bahrain has a comprehensive primary privacy law supported by ten short, numbered subordinate orders covering technical and organisational measures, consent, sensitive data, DPO, notifications, complaints, and criminal proceedings.',
         'Ingest Bahrain primary law plus all ten subordinate orders'),
        ('India Digital Personal Data Protection (DPDP) Act 2023 and DPDP Rules 2025',
         'India combines a primary statute (DPDP Act 2023) with supporting rules (DPDP Rules 2025) and operational-circular-style RBI directives (Cybersecurity Framework, KYC Master Direction, Payment Data Localisation Circular). The format mixes statute and circular.',
         'Ingest DPDP Act, DPDP Rules, and supporting RBI directives'),
        ('Kuwait CBK Data Privacy Protection Regulation and CITRA User Protection Privacy Rules',
         "Kuwait's privacy regime is comparatively thinner. It is delivered through sector-specific regulations (CBK for banking, CITRA for telecoms) rather than a single comprehensive national privacy law. Documents are materially shorter and narrower in scope.",
         'Ingest Kuwait sectoral instruments; flag thinner coverage'),
        ('Terminology variation across regimes',
         "Bahrain uses 'data subject', India's DPDP uses 'data principal', and Kuwait's CBK regulation uses 'customer' or 'natural person'. The same legal concept appears under different terms.",
         'Cross-jurisdictional term dictionary mapping equivalent terms'),
        ("BBK's existing security posture",
         "BBK's current authentication practice uses multi-factor authentication, password rotation, and role-based access. Audit logs are kept for all privileged actions. These conventions should be inherited rather than redesigned.",
         'TOTP MFA, password complexity, RBAC, audit logging consistent with BBK practice'),
    ], col1='Reference', col2='Notes', col3='Requirement',
       widths=(4.5, 8.5, 4.0))

    doc.add_paragraph()

    # ────────────────────────────────────────────────────────────
    # 4. TECHNICAL FEASIBILITY STUDY RESULTS
    # ────────────────────────────────────────────────────────────
    add_heading(doc, '4. Technical Feasibility Study Results', level=1, size=14)
    add_para(doc, 'A short prototyping phase produced the following findings, which became performance targets and architecture requirements.')
    add_qa_table(doc, [
        ('Local LLM inference performance on commodity hardware',
         'Local inference using Ollama (llama3.2:1b) on a laptop without GPU acceleration took several minutes per single-topic comparison, making interactive workflows infeasible. A managed cloud LLM (Claude Haiku 4.5 via OpenRouter) returned answers in under five seconds.',
         'Swappable LLM providers: managed cloud as development default, local as production fallback'),
        ('Hybrid retrieval accuracy',
         'Hybrid retrieval (BGE-small semantic + SQLite FTS5 keyword) achieved hit-rate-at-5 of 0.95 on the evaluation set, versus 0.875 for in-memory BM25 alone. Persistent BM25 store also enabled filter pushdown.',
         'Persistent SQLite FTS5 + BGE-small for hybrid retrieval'),
        ('Chunking strategy for legal documents',
         'Markdown-header-aware splitting at 512 tokens with 60-token overlap preserved section structure across all three corpora without exceeding the embedding model context window. Oversized articles kept as parent records for context expansion.',
         '512-token chunks with overlap, parent-child relationship preservation'),
        ('Cross-encoder reranker selection',
         "ms-marco-MiniLM-L-6-v2 (~80 MB) outperformed bge-reranker-large on the project's corpus while being much smaller, supporting commodity-hardware deployment.",
         'Cross-encoder reranking using ms-marco-MiniLM-L-6-v2'),
        ('End-to-end workflow timing',
         'Single-topic comparison ran end-to-end (retrieval + reasoning + citation verification + structured-output parsing) in under 60 seconds on a typical regulation pair. Single-topic policy mapping completed in under 90 seconds.',
         'Performance targets: 60 s for comparison, 90 s for mapping'),
    ], col1='Topic', col2='Findings', col3='Requirement',
       widths=(4.5, 8.5, 4.0))

    # ────────────────────────────────────────────────────────────
    # REFERENCES (APA 7)
    # ────────────────────────────────────────────────────────────
    doc.add_paragraph()
    add_heading(doc, 'References', level=1, size=14)
    add_para(
        doc,
        'The following references support the in-text citations used in the '
        'Research Results section above. Entries follow APA 7 style.'
    )

    references = [
        "Gao, Y., Xiong, Y., Gao, X., Jia, K., Pan, J., Bi, Y., Dai, Y., Sun, J., & Wang, H. (2024). Retrieval-augmented generation for large language models: A survey. arXiv. https://arxiv.org/abs/2312.10997",
        "Jacovi, A., Wang, A., Alberti, C., Tao, C., Lipovetz, J., Olszewska, K., Haas, L., Liu, M., Keating, N., Bloniarz, A., Saroufim, C., Fry, C., Marcus, D., Kukliansky, D., Tomar, G. S., Swirhun, J., Xing, J., Wang, L., Gurumurthy, M., … Das, D. (2025). The FACTS Grounding leaderboard: Benchmarking LLMs' ability to ground responses to long-form input. arXiv. https://arxiv.org/abs/2501.03200",
        "National Institute of Standards and Technology. (2024). Artificial intelligence risk management framework: Generative artificial intelligence profile (NIST AI 600-1). U.S. Department of Commerce. https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf",
        "OWASP Foundation. (2025). LLM01: Prompt injection — OWASP top 10 for large language model applications 2025. https://genai.owasp.org/llmrisk/llm01-prompt-injection/",
        "Rackauckas, Z. (2024). RAG-Fusion: A new take on retrieval-augmented generation. arXiv. https://arxiv.org/abs/2402.03367",
        "Tamber, M. S., Bao, F. S., Xu, C., Luo, G., Kazi, S., Bae, M., Li, M., Mendelevitch, O., Qu, R., & Lin, J. (2025). Benchmarking LLM faithfulness in RAG with evolving leaderboards. arXiv. https://arxiv.org/abs/2505.04847",
        "Tang, L., Laban, P., & Durrett, G. (2024). MiniCheck: Efficient fact-checking of LLMs on grounding documents. In Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing. Association for Computational Linguistics. https://arxiv.org/abs/2404.10774",
        "Wallat, J., Heuss, M., de Rijke, M., & Anand, A. (2024). Correctness is not faithfulness in RAG attributions. arXiv. https://arxiv.org/abs/2412.18004",
        "Wen, T., Wang, C., Yang, X., Tang, H., Xie, Y., Lyu, L., Dou, Z., & Wu, F. (2025). Defending against indirect prompt injection by instruction detection. arXiv. https://arxiv.org/abs/2505.06311",
        "Zhang, J., Xiang, J., Yu, Z., Teng, F., Chen, X., Chen, J., Zhuge, M., Cheng, X., Hong, S., Wang, J., Zheng, B., Liu, B., Luo, Y., & Wu, C. (2025). AFlow: Automating agentic workflow generation [Paper presentation]. International Conference on Learning Representations (ICLR) 2025. https://arxiv.org/abs/2410.10762",
    ]
    for ref in references:
        p = doc.add_paragraph()
        run = p.add_run(ref)
        run.font.color.rgb = NAVY
        run.font.size = Pt(10)
        # Hanging indent for APA references.
        p.paragraph_format.left_indent = Cm(1.0)
        p.paragraph_format.first_line_indent = Cm(-1.0)
        p.paragraph_format.space_after = Pt(6)

    doc.save(str(out_path))
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
