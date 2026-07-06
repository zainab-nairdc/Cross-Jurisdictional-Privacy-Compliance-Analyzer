"""Generate §3.2 Solution Design (main body) + Appendix 2 in one docx.

Output: thesis_docs/3_2_solution_design_combined.docx

Rubric coverage:
  (1) Design methodologies          §3.2.0 (new)
  (2) Algorithm design & evaluation §3.2.3, §3.2.3.8, §3.2.3.9
  (3) Data structures & selection   §3.2.1, Tables 7 + 8
  (4) UML diagrams                  §3.2.2 + Appendix 2.3, 2.5
  (5) Flowcharts                    §3.2.3 figures + Appendix 2.3
  Requirements traceability         §3.2.6 + Appendix 2.1 (new)

Figures referenced by number are external PNGs that the user
generates separately. Where the PNG is not yet placed in diagrams/,
a [INSERT FIGURE] placeholder appears in the doc.
"""

import importlib.util
import sys
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


def _load_cybersecurity_data():
    """Import the cybersecurity data constants from the existing
    cybersecurity generator so we do not duplicate definitions."""
    base = Path(__file__).resolve().parent
    cyb_path = base / 'generate_cybersecurity_v2.py'
    spec = importlib.util.spec_from_file_location(
        'cyb_data', cyb_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['cyb_data'] = module
    spec.loader.exec_module(module)
    return module


CYB = _load_cybersecurity_data()
OWASP_WEB_ROWS = CYB.OWASP_WEB_ROWS
OWASP_LLM_ROWS = CYB.OWASP_LLM_ROWS
RISK_ROWS = CYB.RISK_ROWS
RISK_COLOR_MAP = CYB.RISK_COLOR_MAP
POLICIES = CYB.POLICIES


def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def set_run_style(run, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11, font_name=None):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)
    if font_name:
        run.font.name = font_name


def add_heading(doc, text, *, level=1):
    style_map = {1: 'Heading 1', 2: 'Heading 2', 3: 'Heading 3',
                 4: 'Heading 4'}
    size_map = {1: 16, 2: 14, 3: 12, 4: 11}
    h = doc.add_paragraph(style=style_map[level])
    run = h.add_run(text)
    run.font.color.rgb = NAVY
    run.font.bold = True
    run.font.size = Pt(size_map[level])
    return h


def add_paragraph(doc, text, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                  space_after=8):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    set_run_style(run, bold=bold, italic=italic, color=color, size=size)
    return p


def add_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_figure_placeholder(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(f'[INSERT FIGURE: {label}]')
    set_run_style(run, bold=True, italic=True, color=MUTED, size=10)
    add_caption(doc, label + '.', caption)


def add_table(doc, headers, rows, widths_cm, body_size=9,
              bold_first=True):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)
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
                        bold=(bold_first and c_idx == 0),
                        color=DARK_GRAY,
                        size=body_size,
                    )


# -------------------------------------------------------------------------
# DATA — main body
# -------------------------------------------------------------------------

DATA_STRUCTURES = [
    ('1', 'BGE-small (384-dim) + ChromaDB HNSW',
     'Open-source, persistent, cosine similarity with metadata '
     'filters; scales to the project corpus without retrieval-time '
     'degradation (NFR4).'),
    ('2', 'SQLite FTS5 BM25 inverted index',
     'Sub-millisecond response and handles the legal acronyms (DPO, '
     'PDPL, GDPR) that vector embeddings struggle with (FR4).'),
    ('3', 'Reciprocal Rank Fusion (RRF)',
     'Combines BM25 and vector ranks without any score-calibration '
     'step; constant k=60 (FR4).'),
    ('4', 'Two-level chunk schema',
     'Splits on article headers and merges on semantic similarity, '
     'preserving citation granularity (FR3, FR6).'),
    ('5', 'Content-hash on chunk id',
     'SHA-256 detects duplicate chunks at ingest time without '
     'scanning the database (NFR8).'),
    ('6', 'LangGraph state TypedDict',
     'Carries the explicit verify, correct, and retry control flow '
     'with bounded iteration (NFR5).'),
    ('7', 'Pydantic v2 schemas',
     'Hard parse boundary at the LLM-Python interface with an '
     'auto-fixing parser for malformed output (FR23, NFR9).'),
    ('8', 'chunk_tags 12-topic taxonomy',
     'Cheap and deterministic intent classification that drives the '
     'topic-aware scoping of policy mappings (FR9).'),
    ('9', 'ObligationMapping lifecycle FSM',
     'Audit trail through controlled state transitions across draft, '
     'reviewed, approved, and rejected states (FR22, FR8).'),
    ('10', 'Audit-hash chain (SHA-256)',
     'Detects silent post-signing edits to exported PDF and XLSX '
     'artefacts (FR15, NFR14).'),
]


ALGORITHM_DECISIONS = [
    ('Hybrid retrieval fusion',
     'Learned re-ranker',
     'Reciprocal Rank Fusion (k=60)',
     'No score calibration needed between BM25 and vector scores, '
     'faster to implement, supports NFR1.'),
    ('NLI aggregation',
     'Mean entailment over top-5 chunks',
     'MAX entailment over top-5',
     'A multi-sentence answer is grounded if any chunk supports it, '
     'reducing false rejections; supports NFR20.'),
    ('Retry policy',
     'Unlimited retry',
     'Bounded retries with deterministic SafeFallback',
     'Prevents multi-minute hangs; supports NFR5 and NFR6.'),
    ('Cross-encoder model',
     'bge-reranker-large',
     'ms-marco-MiniLM-L-6-v2 (~80 MB)',
     'Smaller, faster, comparable accuracy on the project corpus; '
     'supports NFR1 and the commodity-hardware constraint CON-01.'),
    ('Topic-based routing',
     'Pre-filter regulations automatically before mapping',
     'Topic-aware retrieval scoping only',
     'Auto-routing of regulation selection is recorded as future '
     'work; the current design uses detected topics to scope '
     'retrieval and filter the mapping workspace (FR9).'),
    ('Audit fingerprint',
     'Full SHA-256 in QR code on every export',
     '16-character SHA-256 prefix in the export footer',
     'Sufficient collision resistance for audit purposes, printable '
     'in the footer; supports FR15 hash chain.'),
]


ALGORITHM_EVALUATION = [
    ('Hybrid retrieval',
     'hit_rate@5 = 0.95 on the 40-pair design benchmark versus '
     '0.875 for the in-memory LlamaIndex baseline (Table A.8.8)',
     'hit_rate@5 = 0.91 on the 100-query validation set '
     '(§3.4.5 Table 28); hybrid configuration outperformed both '
     'single-lane configurations'),
    ('Cross-encoder rerank',
     'ms-marco MiniLM outperformed bge-reranker-large on the '
     'project corpus while being one tenth the size (Table A.8.8)',
     'Reranker observed to promote at least 2 candidates past the '
     'RRF leader on representative queries (§3.4.5)'),
    ('Reasoning loop',
     'Bounded 2-retry budget chosen via prototyping; deterministic '
     'SafeFallback for unrecoverable failures (Table A.8.6)',
     '96 percent first-attempt pass, 3 percent corrected on retry, '
     '1 percent SafeFallback (§3.4.5 Table 29)'),
    ('NLI hallucination gate',
     'MAX entailment chosen over mean to reduce false rejections; '
     'threshold tuned in prototyping',
     '87 percent high-faithfulness, 11 percent medium, 2 percent '
     'gated (§3.4.5 Table 30)'),
    ('Local LLM',
     'llama3.2:1b chosen for CPU feasibility on commodity hardware '
     '(CON-01); fallback to Claude Haiku 4.5 for the Tier-B '
     'injection judge only',
     'Ollama 12.4 s versus Claude Haiku 2.1 s per query on the '
     'comparison workflow (§3.4.5 Table 31)'),
]


CONFIG_PER_COMPONENT = [
    ('Web browser', 'Client',
     'HTMX 2 + Alpine.js 3 + Chart.js; CSP allowlist'),
    ('Reverse proxy (Caddy)', 'Edge',
     'TLS 1.3 termination; HSTS preload; HTTPS on port 443'),
    ('Django ASGI (Daphne)', 'Application',
     'Python 3.13; port 8000; RBAC + TOTP MFA + CSRF; '
     'SESSION_COOKIE_AGE 28 800 s; IDLE_TIMEOUT 1 800 s'),
    ('Background workers', 'Application',
     'Same Python venv; threading.Thread daemons for ingestion; '
     'subprocess dispatch for mapping and comparison jobs'),
    ('ChromaDB', 'Data',
     'HNSW vector index; BGE-small (384-dim); chroma_data/ on disk; '
     'collection "regulations"'),
    ('SQLite FTS5', 'Data',
     'BM25 keyword index; fts_chunks virtual table; jurisdiction '
     'filter at query time'),
    ('Django SQLite', 'Data',
     'db.sqlite3; WAL journaling; users, models, audit log; '
     'DB-backed sessions'),
    ('Ollama daemon', 'LLM service',
     'localhost:11434; default model llama3.2:1b; HTTP only to '
     'Django'),
    ('File storage', 'Data',
     'media/ (uploads), data/ (corpus), hf_cache/ (BGE model), '
     'chroma_data/ (vectors)'),
]


ARCH_DECISIONS = [
    ('Hosting', 'Cloud or Kubernetes',
     'Single-host on-premises',
     'Analytical content stays on the BBK host; only the Tier-B '
     'injection judge calls an external LLM with a suspect chunk '
     'and no analyst identifier.'),
    ('Async dispatch', 'Celery + Redis',
     'Fire-and-forget subprocess and daemon thread',
     'Avoids extra infrastructure; subprocess carries its own DB '
     'connections.'),
    ('Relational store', 'PostgreSQL',
     'SQLite with WAL journaling',
     'Single-machine deployment; backup is one folder.'),
    ('Keyword index', 'In-memory BM25 (LlamaIndex)',
     'Persistent SQLite FTS5 with filter pushdown',
     'hit_rate@5 0.95 versus 0.875 baseline on the design '
     'benchmark; survives process restarts.'),
    ('LLM provider', 'Cloud-hosted LLM only',
     'Provider abstraction with local default',
     'Same confidentiality boundary; provider switch by '
     'environment variable (NFR11).'),
    ('Retry policy', 'Unlimited retry',
     'Bounded retries with deterministic SafeFallback',
     'Prevents multi-minute hangs; fallback returns a safe summary '
     '(NFR5, NFR6).'),
]


# -------------------------------------------------------------------------
# TRACEABILITY MATRIX
# -------------------------------------------------------------------------

TRACE_FR = [
    ('FR1', 'Ingest BH/IN/KW privacy regulations',
     '§3.2.3.7, Appendix 2.3 Figure A2.3d (ingestion activity)'),
    ('FR2', 'Ingest BBK internal policies and SOPs',
     '§3.2.3.7, Appendix 2.3 Figure A2.3d'),
    ('FR3', 'Split documents into chunks preserving section structure',
     '§3.2.1.2 Two-level chunk schema (#4), §3.2.3.7'),
    ('FR4', 'Hybrid retrieval combining keyword and semantic search',
     '§3.2.1.2 RRF (#3), §3.2.3.4, Appendix 2.3 Figure A2.3e'),
    ('FR5', 'Cross-jurisdictional terminology expansion',
     '§3.2.3.4, Appendix 2.7 Algorithm 12'),
    ('FR6', 'Citation-preserving search results',
     '§3.2.1.2 Two-level chunk schema (#4), §3.2.3.3 VerifyAndScore'),
    ('FR7', 'Compare obligations between two regulations',
     '§3.2.3.6 Algorithm 4, Appendix 2.3 Figure A2.3a'),
    ('FR8', 'Map internal policy with coverage classification',
     '§3.2.3.5 Algorithm 3, §3.2.1.2 lifecycle FSM (#9)'),
    ('FR9', 'Detect compliance topics and scope retrieval',
     '§3.2.1.2 chunk_tags taxonomy (#8), §3.2.3.4, '
     'Appendix 2.7 Algorithm 14, Appendix 2.8 Table A.8.1'),
    ('FR10', 'Aggregate gaps into unified report',
     '§3.2.3.5 (Gap reconciliation), §3.2.4.2 Web component'),
    ('FR11', 'Compliance dashboard',
     '§3.2.4.2 Web component, §3.2.2.4 Use case (View dashboard)'),
    ('FR12', 'Library workspace',
     '§3.2.4.2 Web component, §3.2.2.4 Use case (Browse library)'),
    ('FR13', 'Comparison and mapping workspaces with override and '
             'remediation',
     '§3.2.4.2 Web component, §3.2.3.5, §3.2.3.6'),
    ('FR14', 'Reviewer queue workspace',
     '§3.2.4.2 Web component, Appendix 2.3 Figure A2.3c (cascade)'),
    ('FR15', 'Export reports in XLSX and PDF with citation '
             'traceability',
     '§3.2.1.2 audit-hash chain (#10), §3.2.3.7 Algorithm 6, '
     'Appendix 2.3 Figure 14'),
    ('FR16', 'Global AI Copilot with citation-backed answers',
     '§3.2.4.2 Copilot component, Appendix 2.3 Figure A2.3b'),
    ('FR17', 'Confidence + hallucination risk score',
     '§3.2.3.3 VerifyAndScore, §3.2.1.2 LangGraph state (#6)'),
    ('FR18', 'Copilot Document mode',
     '§3.2.4.2 Copilot component (scope routing), '
     'Appendix 2.3 Figure A2.3b'),
    ('FR19', 'Copilot Approved Analyses mode',
     '§3.2.4.2 Copilot component (scope routing), '
     'Appendix 2.3 Figure A2.3b'),
    ('FR20', 'TOTP multi-factor authentication',
     '§3.2.5 Cybersecurity Tier 3, §3.2.2.3 Deployment'),
    ('FR21', 'RBAC with three roles',
     '§3.2.5 Cybersecurity Tier 4, §3.2.2.5 Class diagram '
     '(UserProfile.role)'),
    ('FR22', 'Append-only audit log',
     '§3.2.1.2 audit-hash chain (#10), §3.2.5 Cybersecurity Tier 6'),
    ('FR23', 'Two-tier injection scanner + citation verification',
     '§3.2.5 Cybersecurity Tier 5, §3.2.3.7 IngestDocument, '
     '§3.2.3.3 VerifyAndScore'),
]


TRACE_NFR = [
    ('NFR1', 'Interactive retrieval response time',
     '§3.2.1.2 RRF (#3), §3.2.3.4, persistent indexes in §3.2.4.5'),
    ('NFR2', 'Single-topic mapping within ~90 s',
     '§3.2.3.5 Algorithm 3, §3.2.4.5 Quality attributes'),
    ('NFR3', 'Concurrent analyst team support',
     '§3.2.4.1 Layered monolith, §3.2.4.5 Quality attributes'),
    ('NFR4', 'Corpus growth without retrieval-time degradation',
     '§3.2.1.2 HNSW (#1), §3.2.4.5 Quality attributes'),
    ('NFR5', 'Bounded iterative correction',
     '§3.2.1.2 LangGraph state (#6), §3.2.3.3 Algorithm 1'),
    ('NFR6', 'Deterministic typed-empty fallback',
     '§3.2.3.3 SafeFallback, Appendix 2.7 Algorithm 15'),
    ('NFR7', 'Offline reasoning via local LLM',
     '§3.2.2.3 Deployment, §3.2.4.3 Configuration (Ollama)'),
    ('NFR8', 'Idempotent re-ingestion via content hashing',
     '§3.2.1.2 Content-hash (#5), §3.2.3.7 Algorithm 5'),
    ('NFR9', 'Loosely coupled modules',
     '§3.2.0 Design methodologies (layered + DDD), §3.2.4.1'),
    ('NFR10', 'Automated test suite',
     '§3.4 Testing (full coverage), §3.2.4.5 Quality attributes'),
    ('NFR11', 'Swappable LLM providers',
     '§3.2.4.4 Architectural decisions, §3.2.4.3 Configuration'),
    ('NFR12', 'Live progress for long operations',
     '§3.2.4.1 Channels WebSocket cross-cutting, §3.2.4.6'),
    ('NFR13', 'Idle session timeout warning',
     '§3.2.5 Cybersecurity Tier 3, §3.2.4.3 Configuration '
     '(IDLE_TIMEOUT)'),
    ('NFR14', 'Audit-quality export with hash chain',
     '§3.2.1.2 audit-hash chain (#10), §3.2.3.7 Algorithm 6'),
    ('NFR15', 'TLS 1.3 with HSTS preload',
     '§3.2.5 Cybersecurity Tier 1, §3.2.4.3 Configuration (Caddy)'),
    ('NFR16', 'Content Security Policy allowlist',
     '§3.2.5 Cybersecurity Tier 1, §3.2.4.3 Configuration (browser)'),
    ('NFR17', 'Geographic access control with graceful failure',
     '§3.2.5 Cybersecurity Tier 2 GeoFence'),
    ('NFR18', 'Runtime configuration via environment variables',
     '§3.2.4.3 Configuration per component'),
    ('NFR19', 'Administrator monitoring dashboard',
     '§3.2.4.6 Cross-cutting concerns, §3.2.5 Cybersecurity Tier 6'),
    ('NFR20', 'NLI grounding score for AI outputs',
     '§3.2.3.3 VerifyAndScore, Appendix 2.8 Table A.8.6 threshold'),
]


TRACE_CONSTRAINTS = [
    ('CON-01', 'Hardware (no NVIDIA GPU during development)',
     '§3.2.4.4 LLM provider decision, §3.2.4.3 Ollama config, '
     '§3.2.3 algorithm choices'),
    ('CON-02', 'Data access (no real BBK policies)',
     '§3.2.1.2 corpus-agnostic ingestion (#4), '
     '§3.2.4.4 Architectural decisions'),
    ('CON-03', 'Data validation (unvalidated regulatory set)',
     '§3.2.1.2 corpus-agnostic ingestion (#4), §3.2.0 Methodologies '
     '(RAG over re-trained model)'),
    ('CON-04', 'Data quality',
     '§3.2.3.3 VerifyAndScore (citation grounding), §3.2.0 '
     'draft-verify-correct pattern'),
    ('CON-05', 'Regulatory regime asymmetry',
     '§3.2.3.6 RunComparison (asymmetric equivalence categories), '
     '§3.2.3.5 RunPolicyMapping (topic-aware scope)'),
    ('CON-06', 'Linguistic (English-only)',
     '§3.2.4.4 LLM provider decision, §3.2.1.2 corpus-agnostic '
     'ingestion (#4)'),
]


# -------------------------------------------------------------------------
# WRITERS — main body
# -------------------------------------------------------------------------

def write_intro(doc):
    add_heading(doc, '3.2 Solution Design', level=1)
    add_paragraph(
        doc,
        'The design applies the requirements in §3.1 across five '
        'layers (ingestion, retrieval, reasoning, web, copilot). '
        'Security and observability are cross-cutting and discussed '
        'in §3.2.5. The full traceability matrix mapping every '
        'functional, non-functional, and constraint requirement to '
        'its design element appears in Appendix 2.1.',
    )


def write_320_methodologies(doc):
    add_heading(doc, '3.2.0 Design Methodologies', level=2)
    add_paragraph(
        doc,
        'Six methodologies, chosen before implementation began, '
        'translate the §3.1 requirements into design.',
    )
    add_paragraph(
        doc,
        '(1) Layered architecture splits the code into five '
        'domain layers (ingestion, retrieval, reasoning, web, '
        'copilot) with clean interfaces. This supports '
        'maintainability (NFR9) by allowing one layer to change '
        'without affecting the others.',
    )
    add_paragraph(
        doc,
        '(2) Domain-driven design (Özkan et al., 2025) aligns '
        'each layer with one bounded context and its own '
        'ubiquitous language, keeping the language-model, '
        'storage, and user-interface concerns separate.',
    )
    add_paragraph(
        doc,
        '(3) Retrieval-augmented generation in the '
        'regulated-domain configuration of Hindi et al. (2025) '
        'grounds every answer in retrieved evidence rather than '
        'the language model parameters. This is required '
        'because the regulatory corpus changes frequently and '
        'citation traceability is a hard requirement (FR6, '
        'FR23).',
    )
    add_paragraph(
        doc,
        '(4) A reflective draft-verify-correct loop with '
        'bounded retries (Shinn et al., 2023) surfaces verifier '
        'failures back into the next attempt as verbal '
        'feedback. The retry budget is explicit and exhausting '
        'it triggers a deterministic fallback, supporting NFR5 '
        'and NFR6.',
    )
    add_paragraph(
        doc,
        '(5) Contract-first design with Pydantic v2 schemas at '
        'the LLM-Python boundary validates every AI response. '
        'Malformed output is auto-repaired by OutputFixingParser '
        'within the bounded retry budget, reducing interface '
        'drift (FR23, NFR9; Kim & Min, 2024).',
    )
    add_paragraph(
        doc,
        '(6) Event-driven cross-cutting through Django signals '
        'propagates audit events and Gap-table reconciliation '
        'without coupling workflow code to either concern. The '
        'observability and security layers stay independent of '
        'the workflows that emit the events (FR22, NFR19; '
        'Cabane & Farias, 2024).',
    )


def write_321_data_structures(doc):
    add_heading(doc, '3.2.1 Data Structures', level=2)

    add_paragraph(
        doc,
        'Three principles shape the choice of data structures. '
        'First, the five layers stay separate with clean '
        'interfaces, so any one can be changed without '
        'affecting the others (NFR9). Second, the system does '
        'not train a model on the regulatory corpus. Instead, '
        'it retrieves the relevant passages when a question is '
        'asked and uses those passages as the basis for the '
        'answer; every claim must cite a verbatim clause (FR6, '
        'FR23) and the regulations change too often for a '
        'trained model to keep up. Third, every model answer is '
        'treated as a draft and is checked against the '
        'retrieved evidence. If the check fails, the system '
        'returns a deterministic safe answer instead of '
        'retrying indefinitely (NFR5, NFR6).',
    )
    add_paragraph(
        doc,
        'Table 35 lists the ten structures on the core path '
        'with the rationale for each. Three deserve a closer '
        'look in the appendix (A2.2): the LangGraph reasoning '
        'state that carries the verify/correct loop, Reciprocal '
        'Rank Fusion that merges keyword and semantic hits '
        'without score calibration, and the audit-hash chain '
        'that makes silent post-signing tampering detectable. '
        'The Django entity-relationship diagram (Figure 2) and '
        'the non-relational structures (Figure 3) appear below.',
    )
    add_caption(doc, 'Table 35.', 'Data-structure selection rationale.')
    add_table(
        doc,
        headers=['#', 'Structure', 'Rationale'],
        rows=DATA_STRUCTURES,
        widths_cm=[0.8, 5.5, 9.7],
        body_size=9,
    )
    add_figure_placeholder(
        doc, 'Figure 2',
        'Entity-relationship diagram of the relational data layer.')
    add_figure_placeholder(
        doc, 'Figure 3', 'Non-relational data structures.')


def write_322_design_diagrams(doc):
    add_heading(doc, '3.2.2 Design Diagrams', level=2)
    add_paragraph(
        doc,
        'Six UML families are used: use case, class, deployment, '
        'sequence, activity, and state. Figures 4 to 7 carry the '
        'four diagrams central to the design; per-phase '
        'sequence, activity, and state diagrams are in '
        'Appendices A2.3 and A2.5.',
    )

    add_paragraph(
        doc,
        'Figure 4 names the three actors and their use cases. '
        '«include» relationships make citation verification and '
        'audit-hash stamping mandatory on every mapping and '
        'export.',
    )
    add_figure_placeholder(doc, 'Figure 4', 'Use case diagram.')

    add_paragraph(
        doc,
        'Figure 5 shows the deployment as a single on-premises '
        'Linux host behind one trust boundary; the browser is '
        'the only element outside it.',
    )
    add_figure_placeholder(doc, 'Figure 5', 'Deployment view.')

    add_paragraph(
        doc,
        'Figure 6 shows the AI pipeline in two halves: offline '
        '(ingest, chunk, embed, index) and online (retrieve, '
        'reason, verify, finalise).',
    )
    add_figure_placeholder(
        doc, 'Figure 6', 'AI end-to-end pipeline.')

    add_paragraph(
        doc,
        'Figure 7 shows the persistent class model. Document is '
        'the root entity; MappingAnalysis composes '
        'ObligationMapping then Gap; ComparisonRun composes '
        'ComparisonResult.',
    )
    add_figure_placeholder(
        doc, 'Figure 7', 'Class diagram of the persistent layer.')


def write_323_algorithms(doc):
    add_heading(doc, '3.2.3 Algorithms', level=2)

    add_paragraph(
        doc,
        'Seven main-body algorithms cover the runtime path; '
        'twelve auxiliary and integration algorithms (Appendix '
        'A2.7, with constants in A2.8). Figure 8 is the '
        'one-page system flowchart from authentication to one '
        'of five user actions, each writing to the audit log.',
    )
    add_figure_placeholder(
        doc, 'Figure 8', 'CJPCA master system flowchart.')

    add_paragraph(
        doc,
        'Algorithm 1 (ReasoningAgent) is the LangGraph state '
        'machine that drives every reasoning request. '
        'QueryRouter (Algorithm 11) classifies the query into '
        'one of four routes, the local LLM produces a '
        'structured draft using the route-specific prompt, and '
        'VerifyAndScore (Algorithm 2) runs two independent '
        'checks. The first is verbatim citation grounding with '
        'cross-chunk recovery, which confirms every quoted '
        'clause appears as a literal substring in a retrieved '
        'chunk. The second is an NLI hallucination score from a '
        'cross-encoder, taking the MAX entailment across the '
        'top-5 chunks so a multi-sentence answer is judged '
        'grounded if any chunk supports it. A failed '
        'verification re-prompts with the verifier complaint '
        'attached. Once retries exhaust, SafeFallback returns a '
        'deterministic safe answer rather than letting the '
        'model keep guessing (Figure 9).',
    )
    add_figure_placeholder(doc, 'Algorithm 1', 'ReasoningAgent.')
    add_figure_placeholder(doc, 'Algorithm 2', 'VerifyAndScore.')
    add_figure_placeholder(
        doc, 'Figure 9', 'Reasoning agent state machine.')

    add_paragraph(
        doc,
        'Algorithm 3 (HybridRetrieve) is the agent input '
        'pipeline. The query is first expanded against the '
        'cross-jurisdictional term dictionary (Algorithm 12) so '
        'BBK-specific synonyms reach both retrievers. BM25 over '
        'SQLite FTS5 catches the legal acronyms (DPO, PDPL, '
        'GDPR) that vector embeddings struggle with, while '
        'vector search over ChromaDB catches the paraphrases '
        'that BM25 misses. The two ranked lists are merged with '
        'Reciprocal Rank Fusion at k=60 (no score calibration '
        'needed), the top-20 candidates are reranked by the '
        'ms-marco-MiniLM cross-encoder, and the top-5 are '
        'returned (Figure 10).',
    )
    add_figure_placeholder(doc, 'Algorithm 3', 'HybridRetrieve.')
    add_figure_placeholder(
        doc, 'Figure 10', 'Hybrid retrieval pipeline.')

    add_paragraph(
        doc,
        'Algorithm 4 (RunPolicyMapping) traces a policy mapping '
        'from analyst click to populated rows. The view creates '
        'a parent MappingAnalysis row, dispatches a background '
        'subprocess via LaunchSubprocess (Algorithm 18), and '
        'returns immediately. Inside the subprocess, '
        'AutoRouteScope (Algorithm 13) prunes the obligation '
        'set to topics the policy actually covers when '
        'scope_mode = AUTO. The subprocess then iterates each '
        'remaining obligation: hybrid retrieval finds evidence, '
        'the reasoning agent verifies an answer, the confidence '
        'rule caps unverified rows at 0.6, and a post-save '
        'signal (Algorithm 17) reconciles the Gap table '
        '(Figure 11).',
    )
    add_paragraph(
        doc,
        'Algorithm 5 (RunComparison) uses the same dispatch '
        'pattern. StrictnessScore (Algorithm 8) is pre-computed '
        'once per regulation as a four-factor weighted formula. '
        'For each topic, hybrid retrieval pulls chunks from '
        'both regulations in parallel and the reasoning agent '
        'classifies the relationship as equivalent, stricter, '
        'additional, or conflicting. After all topics finish, '
        'DivergenceRanking (Algorithm 9) orders rows for the '
        'executive summary, with conflicting clauses surfaced '
        'before lesser divergences (Figure 12).',
    )
    add_figure_placeholder(doc, 'Algorithm 4', 'RunPolicyMapping.')
    add_figure_placeholder(doc, 'Algorithm 5', 'RunComparison.')
    add_figure_placeholder(
        doc, 'Figure 11', 'Policy mapping workflow.')
    add_figure_placeholder(
        doc, 'Figure 12', 'Cross-jurisdictional comparison workflow.')

    add_paragraph(
        doc,
        'Algorithm 6 (IngestDocument) parses uploaded PDF and '
        'DOCX files with Docling (which handles scanned '
        'documents internally), applies two-level chunking '
        '(parent sections plus leaf chunks), then indexes safe '
        'leaves into ChromaDB and BM25 with parents in the '
        'parent docstore for retrieval-time expansion. '
        'Algorithm 7 (AuditHashAndExport) computes a SHA-256 '
        'fingerprint over the analysis identity tuple bound to '
        'the prior export and stamps the first 16 characters '
        'into the PDF or XLSX footer, so silent post-signing '
        'edits become detectable by anyone who recomputes the '
        'fingerprint (Figures 13 and 14).',
    )
    add_figure_placeholder(doc, 'Algorithm 6', 'IngestDocument.')
    add_figure_placeholder(
        doc, 'Algorithm 7', 'AuditHashAndExport.')
    add_figure_placeholder(doc, 'Figure 13', 'Ingestion pipeline.')
    add_figure_placeholder(
        doc, 'Figure 14', 'Approved-report export with audit hash.')

    add_paragraph(
        doc,
        'Table 36 records algorithm-level design decisions. '
        'Table 37 consolidates design-time benchmarks with '
        'post-implementation validation (full methodology in '
        '§3.4.5 and Appendix 4).',
    )
    add_caption(doc, 'Table 36.', 'Algorithm design decisions.')
    add_table(
        doc,
        headers=['Decision', 'Alternative considered', 'Chosen',
                 'Rationale'],
        rows=ALGORITHM_DECISIONS,
        widths_cm=[3.0, 3.5, 3.5, 6.0],
        body_size=8,
    )
    add_caption(doc, 'Table 37.',
                'Algorithm evaluation: design-time and '
                'post-implementation passes.')
    add_table(
        doc,
        headers=['Algorithm', 'Design-time selection benchmark',
                 'Post-implementation validation'],
        rows=ALGORITHM_EVALUATION,
        widths_cm=[3.0, 6.5, 6.5],
        body_size=8,
    )


def write_324_architecture(doc):
    add_heading(doc, '3.2.4 System Architecture', level=2)

    add_paragraph(
        doc,
        'The system is a layered monolith with event-driven '
        'cross-cutting concerns. Five Python packages own the '
        'pipeline. Ingestion reads documents and writes the '
        'corpus. Retrieval reads from the corpus and returns '
        'ranked chunks. Reasoning takes those chunks and '
        'produces verified answers via the LangGraph agent. The '
        'web layer is a Django project of ten apps that '
        'orchestrates user-facing flows. The copilot wraps the '
        'reasoning agent behind a chat interface that reuses '
        'approved evidence.',
    )
    add_paragraph(
        doc,
        'Communication is mostly synchronous in-process Python '
        'calls. Long-running jobs (mapping, comparison, '
        'ingestion) are dispatched as background subprocesses '
        'that hold their own database connections. Django '
        'signals carry event-driven cascades such as audit '
        'logging and Gap reconciliation, so workflow code does '
        'not need to know about either concern. Live progress '
        'on long ingestion jobs is relayed to the browser '
        'through a WebSocket via Django Channels (NFR12), with '
        'HTMX polling as the fallback path. Figure 15 shows the '
        'layered architecture; Figure 16 lists the user-facing '
        'URL routes per Django app.',
    )
    add_paragraph(
        doc,
        'Table 38 summarises the configuration of each '
        'component on the host. Table 39 captures the '
        'architectural decisions and the alternatives '
        'considered. Performance (NFR1, NFR2) rests on '
        'persistent HNSW and FTS5 indexes that survive process '
        'restarts. Reliability (NFR5 through NFR8) rests on '
        'WAL journaling, deterministic SafeFallback, and the '
        'audit-hash chain on exports. Observability (NFR18, '
        'NFR19) rests on the administrator monitoring dashboard '
        'and the centralised AuditLog. Maintainability (NFR9) '
        'rests on the layered split and Pydantic schemas at '
        'every cross-module boundary.',
    )
    add_figure_placeholder(
        doc, 'Figure 15', 'CJPCA layered architecture.')
    add_figure_placeholder(doc, 'Figure 16', 'Django URL routes '
                           'catalogue.')
    add_caption(doc, 'Table 38.', 'Component configuration.')
    add_table(
        doc,
        headers=['Component', 'Tier', 'Configuration'],
        rows=CONFIG_PER_COMPONENT,
        widths_cm=[3.5, 2.5, 10.0],
        body_size=9,
    )
    add_caption(doc, 'Table 39.', 'Architectural decisions.')
    add_table(
        doc,
        headers=['Decision', 'Alternative considered', 'Chosen',
                 'Rationale'],
        rows=ARCH_DECISIONS,
        widths_cm=[3.0, 3.5, 3.5, 6.0],
        body_size=8,
    )


def write_325_security(doc):
    add_heading(doc, '3.2.5 Cybersecurity Considerations', level=2)
    add_paragraph(
        doc,
        'CJPCA is engineered to the financial-sector security '
        'baseline. Figure 17 shows the seven-tier '
        'defence-in-depth model that fails closed at each tier '
        '(Tarandach & Coles, 2020). Tier 1 terminates TLS 1.3 '
        'with HSTS preload, CSP, and standard security headers '
        '(McKay & Cooper, 2019; West & Sartori, 2024). Tier 2 '
        'runs GeoFence with MaxMind GeoLite2 (NFR-13). Tier 3 '
        'enforces Secure/HttpOnly/SameSite cookies, six password '
        'validators, django-axes lockout, and TOTP MFA aligned '
        'to NIST SP 800-63-4 (Temoshok et al., 2025; NFR-11, '
        'NFR-12, FR-09). Tier 4 enforces three-role RBAC with '
        'per-row created_by scope (FR-10). Tier 5 layers the '
        'two-tier injection defence, Pydantic schema gating, '
        'SafeFallback, and the citation plus NLI hallucination '
        'gate (Greshake et al., 2023; Liu et al., 2024; Huang '
        'et al., 2025). Tier 6 writes the append-only AuditLog '
        '(NFR-20, FR-12) and the SHA-256 hash chain footer on '
        'every export (CR-08). Implementation detail per tier '
        'is in Appendix A2.13.',
    )
    add_figure_placeholder(
        doc, 'Figure 17', 'CJPCA Secure Architecture.')

    add_paragraph(
        doc,
        'Table 40 enumerates the nine protected assets, '
        'Table 41 the seven threat actors weighed in the '
        'design, and Table 42 the ten attack surfaces with '
        'their closing controls.',
    )
    add_caption(doc, 'Table 40.',
                'Protected assets and sensitivity ratings.')
    add_table(
        doc,
        headers=['ID', 'Asset', 'Sensitivity', 'Why protected'],
        rows=ASSETS_ROWS,
        widths_cm=[1.0, 4.5, 1.8, 9.7],
        body_size=9,
    )
    add_caption(doc, 'Table 41.', 'Threat actors and mitigations.')
    add_table(
        doc,
        headers=['Actor', 'Motivation', 'Capability', 'Likelihood',
                 'Closing control'],
        rows=THREAT_ACTORS_ROWS,
        widths_cm=[3.2, 3.5, 1.8, 1.6, 6.9],
        body_size=9,
    )
    add_caption(doc, 'Table 42.',
                'Attack surfaces and closing controls.')
    add_table(
        doc,
        headers=['Surface', 'Threat', 'Mitigation in CJPCA'],
        rows=ATTACK_SURFACES_ROWS,
        widths_cm=[3.5, 4.5, 9.0],
        body_size=9,
    )


def write_326_threat_model(doc):
    add_heading(doc, '3.2.6 Threat Model', level=2)
    add_paragraph(
        doc,
        'Figure 18 plots CJPCA as a data flow diagram with four '
        'trust zones (untrusted internet, semi-trusted '
        'perimeter, trusted application, external semi-trusted '
        'LLM judge) and applies STRIDE to every arrow that '
        'crosses a zone boundary (Tarandach & Coles, 2020). '
        'Table 43 maps each STRIDE class to its closing control '
        'in the seven-tier model.',
    )
    add_figure_placeholder(
        doc, 'Figure 18',
        'CJPCA Threat Model (DFD + STRIDE).')
    add_caption(doc, 'Table 43.', 'STRIDE adversary analysis.')
    add_table(
        doc,
        headers=['STRIDE class', 'CJPCA-specific threat',
                 'Affected asset', 'Closing control'],
        rows=STRIDE_ROWS,
        widths_cm=[2.5, 4.5, 3.0, 7.0],
        body_size=9,
    )


def write_327_controls_mapping(doc):
    add_heading(doc, '3.2.7 Security Controls Mapping', level=2)
    add_paragraph(
        doc,
        'Figure 19 groups the 32 enforced controls into four '
        'domains: IAM (identity stack), Network and Edge '
        '(perimeter stack), AI Safety (reasoning-layer guards), '
        'and Data Integrity and Audit (storage and logging '
        'guards).',
    )
    add_figure_placeholder(
        doc, 'Figure 19',
        'CJPCA Security Controls Mapping.')


def write_328_owasp_coverage(doc):
    add_heading(doc, '3.2.8 OWASP Top 10 Coverage', level=2)
    add_paragraph(
        doc,
        'Tables 44 and 45 map every entry of OWASP Top 10 '
        '(OWASP Foundation, 2021) and OWASP Top 10 for LLM '
        'Applications (OWASP Foundation, 2025) to its closing '
        'control in CJPCA. Every entry is closed by at least '
        'one control and most are closed at more than one tier.',
    )
    add_caption(
        doc, 'Table 44.',
        'CJPCA coverage of the OWASP Top 10 web-application risks '
        '(OWASP Foundation, 2021).')
    add_table(
        doc,
        headers=['OWASP risk', 'Closing control in CJPCA', 'Tier'],
        rows=OWASP_WEB_ROWS,
        widths_cm=[4.5, 11.0, 1.5],
        body_size=9,
    )
    add_caption(
        doc, 'Table 45.',
        'CJPCA coverage of the OWASP Top 10 for LLM Applications '
        '(OWASP Foundation, 2025).')
    add_table(
        doc,
        headers=['LLM risk', 'Closing control in CJPCA', 'Tier'],
        rows=OWASP_LLM_ROWS,
        widths_cm=[4.5, 11.0, 1.5],
        body_size=9,
    )


def write_329_traceability(doc):
    add_heading(doc, '3.2.9 Requirements Traceability', level=2)
    add_paragraph(
        doc,
        'Every FR, NFR, and constraint from §3.1 is mapped to '
        'its design element. The complete traceability matrix '
        'appears in Appendix A2.1.',
    )


# -------------------------------------------------------------------------
# WRITERS — Appendix 2
# -------------------------------------------------------------------------

def write_appendix_intro(doc):
    doc.add_page_break()
    add_heading(doc, 'Appendix 2: Solution Design Supplement',
                level=1)
    add_paragraph(
        doc,
        'This appendix contains the detailed design artefacts '
        'that support §3.2: the full requirements traceability '
        'matrix (A2.1), the key data structures in detail '
        '(A2.2), per-phase sequence and activity diagrams '
        '(A2.3), lifecycle state machines (A2.5), the algorithm '
        'reference with pseudocode for auxiliary and integration '
        'algorithms (A2.7), and the algorithm constants and '
        'lookup tables (A2.8). The cybersecurity supplement '
        'covers the risk register (A2.9), the nine security '
        'policies (A2.10), the logs and detection worked '
        'examples (A2.11), the login and multi-factor '
        'authentication flow (A2.12, Figure 20), the security '
        'architecture implementation detail (A2.13), the secure '
        'development practices (A2.14), the prompt injection '
        'defence flow (A2.15, Figure 21), the GeoFence '
        'middleware flow (A2.16, Figure 22), and the audit and '
        'hash chain flow (A2.17, Figure 23).',
    )


def write_a21_traceability(doc):
    add_heading(doc, 'A2.1 Requirements Traceability Matrix', level=2)
    add_paragraph(
        doc,
        'The matrix below maps every requirement from §3.1 to its '
        'design element in §3.2. Three tables cover functional '
        'requirements (Table A2.1), non-functional requirements '
        '(Table A2.2), and constraints (Table A2.3).',
    )

    add_caption(doc, 'Table A2.1.',
                'Functional requirement traceability.')
    add_table(
        doc,
        headers=['FR ID', 'Requirement (short)',
                 'Design element(s) covering it'],
        rows=TRACE_FR,
        widths_cm=[1.4, 5.5, 9.1],
        body_size=8,
    )

    add_caption(doc, 'Table A2.2.',
                'Non-functional requirement traceability.')
    add_table(
        doc,
        headers=['NFR ID', 'Requirement (short)',
                 'Design element(s) covering it'],
        rows=TRACE_NFR,
        widths_cm=[1.4, 5.5, 9.1],
        body_size=8,
    )

    add_caption(doc, 'Table A2.3.',
                'Constraint traceability.')
    add_table(
        doc,
        headers=['CON ID', 'Constraint (short)',
                 'Design element(s) covering it'],
        rows=TRACE_CONSTRAINTS,
        widths_cm=[1.4, 5.5, 9.1],
        body_size=8,
    )


A23_FIGURES = [
    ('A2.3a',
     'Sequence diagram of an analyst-led policy mapping. Django '
     'creates the parent MappingAnalysis row and one '
     'ObligationMapping per obligation; each loop iteration runs '
     'retrieval and reasoning per obligation.'),
    ('A2.3b',
     'Sequence diagram of one Copilot round-trip. An intent '
     'router classifies the question and reuses approved '
     'ComparisonResult or ObligationMapping evidence where '
     'possible, falling back to hybrid retrieval otherwise.'),
    ('A2.3c',
     'Sequence diagram of reviewer validation with cascade. '
     'Approving the parent analysis auto-approves DRAFT/REVIEWED '
     'children with human_override=True; explicit rejects are '
     'never overridden.'),
    ('A2.3d',
     'Activity diagram of the ingestion pipeline with three swim '
     'lanes (Administrator, Django, Pipeline). Tier-A regex plus '
     'Tier-B LLM judge gate every chunk before it reaches the '
     'indexes; flagged chunks go to QuarantinedChunk.'),
    ('A2.3e',
     'Activity diagram of hybrid retrieval. Keyword (FTS5 BM25, '
     'top-20) and semantic (ChromaDB HNSW, top-20) run in '
     'parallel, merge with RRF (k=60), and rerank with a '
     'cross-encoder.'),
    ('A2.3f',
     'Activity diagram of the reasoning loop. Draft, then '
     'verify (citation grounding plus NLI entailment), then '
     'correct on failure with bounded retries before '
     'SafeFallback.'),
]


def write_a22_key_data_structures(doc):
    add_heading(doc, 'A2.2 Key data structures in detail',
                level=2)
    add_paragraph(
        doc,
        'Three structures on the core path deserve a closer '
        'look beyond the rationale in Table 35.',
    )

    add_paragraph(doc, 'LangGraph reasoning state.',
                  bold=True, color=NAVY, space_after=2)
    add_paragraph(
        doc,
        'A small TypedDict that moves through the three '
        'reasoning steps (draft, verify, correct) and carries '
        'four fields: the query, the retrieved chunks, a '
        'reasoning trace, and a retry counter. The counter is '
        'capped at max_retries = 2; once the budget is '
        'exhausted, the state machine returns the deterministic '
        'SafeFallback answer rather than looping indefinitely. '
        'The TypedDict shape is what makes the verify/correct '
        'control flow explicit and lets every node read the '
        'same fields without coupling.',
    )

    add_paragraph(doc, 'Reciprocal Rank Fusion (RRF).',
                  bold=True, color=NAVY, space_after=2)
    add_paragraph(
        doc,
        'Two parallel searches run over the corpus: BM25 over '
        'SQLite FTS5 (keyword) and HNSW over ChromaDB '
        '(semantic). Each returns its own ranked list. RRF '
        'merges them with the position-based formula '
        'score(c) = sum over lists of 1 / (60 + rank(c)). The '
        'constant k = 60 is the published RRF default and '
        'removes the need to calibrate between two different '
        'score scales.',
    )

    add_paragraph(doc, 'Audit-hash chain.', bold=True,
                  color=NAVY, space_after=2)
    add_paragraph(
        doc,
        'Each PDF and XLSX export carries a 16-character '
        'SHA-256 prefix computed over an identity tuple bound '
        'to the prior export. The tuple is the class name, '
        'primary key, status, completed_at, submitted_at, and '
        'created_by id. The hash is stamped into the export '
        'footer and recorded in the AuditLog. Anyone receiving '
        'the file can recompute the hash from the same fields '
        'and detect silent tampering, achieving '
        'audit-defensibility without the operational cost of a '
        'full digital-signature system.',
    )


def write_a23(doc):
    add_heading(doc, 'A2.3 Per-phase mechanics', level=2)
    add_paragraph(
        doc,
        'The figures below expand each phase introduced in §3.2.2. '
        'Sequence diagrams trace one user journey from start to '
        'end; activity diagrams trace the internal steps of one '
        'phase.',
    )
    for label, caption in A23_FIGURES:
        add_figure_placeholder(
            doc, f'Figure {label}', '')
        add_paragraph(doc, caption, italic=True, color=MUTED, size=10)


A25_FIGURES = [
    ('A2.5a',
     'State machine for a MappingAnalysis record. RUNNING moves '
     'to COMPLETE or FAILED; only COMPLETE rows reach REVIEW. '
     'APPROVED is immutable; corrections require a fresh DRAFT '
     'run, leaving the old row in the audit log.'),
    ('A2.5b',
     'State machine for an ObligationMapping record. Findings '
     'reach APPROVED via explicit reviewer action '
     '(human_override=False) or cascade from the parent '
     '(human_override=True). Explicit REJECTED is never '
     'overridden by cascade.'),
    ('A2.5c',
     'State machine for a ComparisonRun record. PARTIALLY_FAILED '
     'exists so a single bad pair does not sink the whole run; '
     'FAILED is reserved for runs where every pair failed. '
     'Reviewers can still approve a PARTIALLY_FAILED run.'),
]


def write_a25(doc):
    add_heading(doc, 'A2.5 Lifecycle states', level=2)
    add_paragraph(
        doc,
        'The state machines below show the lifecycle of the three '
        'workflow records the system tracks. Each transition is a '
        'controlled action; nothing changes state silently.',
    )
    for label, caption in A25_FIGURES:
        add_figure_placeholder(doc, f'Figure {label}', '')
        add_paragraph(doc, caption, italic=True, color=MUTED,
                      size=10)


def write_a27(doc):
    add_heading(doc, 'A2.7 Algorithm reference', level=2)
    add_paragraph(
        doc,
        'This appendix expands the algorithms named but not boxed '
        'in §3.2.3. Section A2.7.1 covers auxiliary procedures '
        'inside the AI pipeline (scoring, classification, '
        'retrieval helpers, the LLM invocation). Section A2.7.2 '
        'covers the three Django integration algorithms that '
        'connect the AI pipeline to the web layer.',
    )

    add_heading(doc, 'A2.7.1 Auxiliary algorithms', level=3)
    add_paragraph(
        doc,
        'Nine procedures expanded here, numbered 8 through 16 to '
        'continue from the main body. Each carries the formula '
        'or logic that the main-body algorithms reference by '
        'name. Weights, thresholds, and lookup tables are in '
        'Appendix 2.8.',
    )
    aux_algorithms = [
        ('Algorithm 8', 'StrictnessScore.'),
        ('Algorithm 9', 'DivergenceRanking.'),
        ('Algorithm 10', 'RiskScore.'),
        ('Algorithm 11', 'QueryRouter.'),
        ('Algorithm 12', 'TermDictionaryExpand.'),
        ('Algorithm 13', 'AutoRouteScope.'),
        ('Algorithm 14', 'ChunkClassify.'),
        ('Algorithm 15', 'SafeFallback.'),
        ('Algorithm 16', 'InvokeLocalLLM.'),
    ]
    for label, caption in aux_algorithms:
        add_figure_placeholder(doc, label, caption)

    add_heading(doc, 'A2.7.2 Django integration algorithms',
                level=3)
    add_paragraph(
        doc,
        'Three patterns that glue the AI pipeline to the Django '
        'web layer, numbered 17 through 19. Each illustrates a '
        'distinct integration mechanism: a Django signal cascade, '
        'an async dispatch pattern, and a manual cross-app '
        'cascade.',
    )
    integration_algorithms = [
        ('Algorithm 17', 'SyncGapOnApproval.'),
        ('Algorithm 18', 'LaunchSubprocess.'),
        ('Algorithm 19', 'CascadeApproval.'),
    ]
    for label, caption in integration_algorithms:
        add_figure_placeholder(doc, label, caption)


TAXONOMY_ROWS = [
    ('lawful_basis', 'Lawful basis & consent',
     'consent; legitimate_interests; legal_obligation; '
     'vital_or_public_task'),
    ('data_subject_rights', 'Data subject rights',
     'access; rectification; erasure; objection_and_automated'),
    ('notice_and_transparency', 'Notice & transparency',
     'privacy_notice; secondary_use_notice; language_accessibility'),
    ('cross_border', 'Cross-border transfers & data residency',
     'adequacy_assessment; transfer_mechanisms; data_localisation; '
     'transfer_exemptions'),
    ('sensitive_data', 'Sensitive & special-category data',
     'sensitive_processing; children_and_minors'),
    ('security', 'Security controls',
     'technical_measures; organisational_measures; access_control; '
     'logging_and_monitoring'),
    ('breach_management', 'Breach management',
     'incident_detection; regulator_notification; '
     'data_subject_notification; incident_response_plan'),
    ('retention', 'Retention & disposal',
     'retention_periods; secure_disposal; archive_and_backup'),
    ('governance', 'Governance & accountability',
     'dpo_appointment; records_of_processing; dpia_and_risk; '
     'policies_and_procedures'),
    ('third_party', 'Third-party & outsourcing',
     'processor_obligations; vendor_due_diligence; '
     'cloud_and_offshoring; data_sharing'),
    ('sector_specific',
     'Sector-specific (banking & financial)',
     'kyc_and_cdd; aml_and_sanctions; customer_protection; '
     'operational_resilience'),
    ('enforcement', 'Enforcement & remedies',
     'regulator_powers; penalties; complaints_and_grievance; '
     'individual_redress'),
]


RISK_WEIGHTS = [
    ('Bahrain (PDPL + Orders)', '0.95', '0.80',
     'Highest statutory penalties and active enforcement regime'),
    ('India (DPDPA 2023 + Rules)', '0.90', '0.65',
     'High fines; enforcement still ramping under DPB'),
    ('Kuwait (DPPR 26/2024)', '0.75', '0.70',
     'Moderate penalties; CITRA enforcement active but lower fines'),
]


IMPACT_WEIGHTS = [
    ('consent', '0.95'),
    ('breach', '0.95'),
    ('cross_border', '0.90'),
    ('security', '0.85'),
    ('retention', '0.75'),
    ('governance', '0.55'),
    ('training', '0.50'),
]


COVERAGE_FACTOR = [
    ('not_covered', '1.00',
     'No policy clause addresses the obligation'),
    ('partial', '0.55',
     'Policy partially addresses the obligation'),
    ('review', '0.65', 'Policy unclear; reviewer must read'),
    ('covered', '0.05', 'Policy fully addresses the obligation'),
]


SEVERITY_BUCKETS = [
    ('Critical', '14 days',
     'Score >= 0.65; legal exposure or active enforcement risk'),
    ('High', '30 days',
     'Score 0.45-0.65; significant gap requiring near-term '
     'remediation'),
    ('Medium', '90 days',
     'Score 0.25-0.45; remediation needed within the quarter'),
    ('Low', '180 days',
     'Score < 0.25; track but no immediate exposure'),
]


CONFIG_CONSTANTS = [
    ('HALLUCINATION_THRESHOLD', '0.10',
     'Algorithm 2: max NLI risk before a draft is rejected'),
    ('RRF k', '60', 'Algorithm 3: Reciprocal Rank Fusion constant'),
    ('TOP_K (vector + BM25)', '20',
     'Algorithm 3: candidates from each retriever before fusion'),
    ('FINAL_TOP_K', '5', 'Algorithm 3: chunks returned to the agent'),
    ('max_retries', '2',
     'Algorithm 1: bounded retry budget before fallback'),
    ('MIN_QUOTE_LENGTH', '10 chars',
     'Algorithm 2: shortest accepted exact_quote'),
    ('CONFIDENCE_FLOOR', '0.30',
     'Algorithm 14: minimum classifier confidence to accept a tag'),
    ('MERGE_THRESHOLD', '0.85',
     'Algorithm 6: semantic similarity for chunk merging'),
    ('IDLE_TIMEOUT', '1800 s (30 min)',
     'Algorithm 19: inactivity before forced logout'),
    ('GRACE_PERIOD', '90 s',
     'Algorithm 18: minimum age of a RUNNING row before reset'),
    ('NAV_CACHE_TIMEOUT', '30 s',
     'Sidebar badge cache TTL'),
    ('Audit hash length', '16 hex chars (64 bits)',
     'Algorithm 7: SHA-256 prefix on every export'),
]


DIVERGENCE_WEIGHTS_COMPONENTS = [
    ('rel (relationship strength)', '0.40'),
    ('conf (model confidence)', '0.30'),
    ('1 - sim (lexical distance)', '0.20'),
    ('principle (criticality of topic)', '0.10'),
]


DIVERGENCE_WEIGHTS_MAPPING = [
    ('conflicting', '1.00', 'Clauses contradict each other'),
    ('stricter_in_a', '0.70', 'Side A is stricter than B'),
    ('stricter_in_b', '0.70', 'Side B is stricter than A'),
    ('additional_in_a', '0.50',
     'Only in A; no counterpart in B'),
    ('additional_in_b', '0.50',
     'Only in B; no counterpart in A'),
    ('equivalent', '0.00', 'Clauses align'),
]


EVALUATION_BENCHMARKS = [
    ('Hybrid retrieval (this system)', 'hit_rate@5', '0.950',
     '40-pair design benchmark; BM25 (SQLite FTS5, persistent) + '
     'ChromaDB + RRF + cross-encoder rerank'),
    ('LlamaIndex baseline (in-memory)', 'hit_rate@5', '0.875',
     'Same 40-pair benchmark; rebuilt per process, no filter '
     'pushdown'),
    ('Hybrid retrieval', 'NLI faithfulness (RAGAS)', '> 0.85',
     '8-question test set with Claude Haiku 4.5 as judge'),
    ('Single-shot LLM call (no retrieval)', 'hit_rate@5',
     '<= 0.10',
     'Baseline: model relies on training data only; included to '
     'motivate retrieval'),
]


def write_a28(doc):
    add_heading(doc, 'A2.8 Algorithm constants and lookup tables',
                level=2)
    add_paragraph(
        doc,
        'This appendix carries the lookup tables, weights, and '
        'configuration constants that the algorithms in §3.2.3 '
        'and Appendix 2.7 read from. Eight tables are provided.',
    )

    add_heading(doc, 'A.8.1 chunk_tags taxonomy', level=3)
    add_caption(doc, 'Table A.8.1.',
                'chunk_tags taxonomy used by ChunkClassify and '
                'AutoRouteScope.')
    add_table(
        doc,
        headers=['Topic tag', 'Label', 'Subcategories'],
        rows=TAXONOMY_ROWS,
        widths_cm=[3.0, 5.0, 8.0],
        body_size=8,
    )

    add_heading(doc, 'A.8.2 Per-jurisdiction risk weights', level=3)
    add_caption(doc, 'Table A.8.2.',
                'Penalty and enforcement weights per jurisdiction '
                '(used by RiskScore, Algorithm 10).')
    add_table(
        doc,
        headers=['Jurisdiction', 'Penalty weight',
                 'Enforcement weight', 'Rationale'],
        rows=RISK_WEIGHTS,
        widths_cm=[4.0, 2.4, 2.6, 7.0],
        body_size=8,
    )

    add_heading(doc, 'A.8.3 Per-topic impact weights', level=3)
    add_caption(doc, 'Table A.8.3.',
                'Impact weight per topic (RiskScore).')
    add_table(
        doc,
        headers=['Topic', 'Impact weight'],
        rows=IMPACT_WEIGHTS,
        widths_cm=[5.0, 3.0],
        body_size=9,
    )

    add_heading(doc, 'A.8.4 Coverage factor by status', level=3)
    add_caption(doc, 'Table A.8.4.',
                'Coverage factor per ObligationMapping status '
                '(RiskScore multiplier).')
    add_table(
        doc,
        headers=['Coverage status', 'Factor', 'Meaning'],
        rows=COVERAGE_FACTOR,
        widths_cm=[3.5, 1.8, 9.7],
        body_size=9,
    )

    add_heading(doc, 'A.8.5 Severity-to-due-date buckets', level=3)
    add_caption(doc, 'Table A.8.5.',
                'Severity bucket to default due-date offset (a '
                'reviewer may override per Gap).')
    add_table(
        doc,
        headers=['Severity bucket', 'Default due offset',
                 'Trigger condition'],
        rows=SEVERITY_BUCKETS,
        widths_cm=[3.0, 3.0, 9.0],
        body_size=9,
    )

    add_heading(doc, 'A.8.6 Algorithm configuration constants',
                level=3)
    add_paragraph(
        doc,
        'Tunable constants referenced across the algorithms in '
        '§3.2.3 and Appendix 2.7. Values are loaded from cfg at '
        'process start; the thresholds shown are the defaults used '
        'in the BBK deployment.',
    )
    add_caption(doc, 'Table A.8.6.',
                'Algorithm configuration constants.')
    add_table(
        doc,
        headers=['Constant', 'Value', 'Used by'],
        rows=CONFIG_CONSTANTS,
        widths_cm=[4.5, 3.5, 7.0],
        body_size=8,
    )

    add_heading(doc, 'A.8.7 DivergenceRanking weights', level=3)
    add_paragraph(
        doc,
        'Importance formula weights used by DivergenceRanking '
        '(Algorithm 9) and the relationship-to-strength mapping that '
        'feeds the rel term.',
    )
    add_caption(doc, 'Table A.8.7 (a).',
                'Importance-formula component weights.')
    add_table(
        doc,
        headers=['Component', 'Weight'],
        rows=DIVERGENCE_WEIGHTS_COMPONENTS,
        widths_cm=[7.0, 3.0],
        body_size=9,
    )
    add_caption(doc, 'Table A.8.7 (b).',
                'Relationship-to-rel-weight mapping.')
    add_table(
        doc,
        headers=['Relationship', 'rel weight', 'Meaning'],
        rows=DIVERGENCE_WEIGHTS_MAPPING,
        widths_cm=[3.5, 2.0, 9.5],
        body_size=9,
    )

    add_heading(doc, 'A.8.8 Retrieval evaluation benchmarks',
                level=3)
    add_paragraph(
        doc,
        'Design-time benchmark scores used to select the hybrid '
        'retrieval architecture. Post-implementation validation '
        'numbers from the deployed system appear in §3.4.5 with '
        'the methodology in Appendix 4.',
    )
    add_caption(doc, 'Table A.8.8.',
                'Retrieval and reasoning evaluation benchmarks '
                '(design-time).')
    add_table(
        doc,
        headers=['System', 'Metric', 'Score', 'Conditions'],
        rows=EVALUATION_BENCHMARKS,
        widths_cm=[4.0, 3.5, 1.8, 6.7],
        body_size=8,
    )


def write_a29_risk_assessment(doc):
    add_heading(doc, 'A2.9 Risk Assessment', level=2)
    add_paragraph(
        doc,
        'The risk register below catalogues every threat surfaced '
        'by the CJPCA data flow diagram in §3.2.6 Figure 18, '
        'scored on the standard likelihood by impact rubric. Each '
        'row names the affected asset, the STRIDE category, the '
        'threat scenario, the inherent risk before controls are '
        'applied, the mitigating control mapped to a tier from '
        'Figure 17, and the residual risk after controls are in '
        'place.',
    )
    add_caption(doc, 'Table A2.4.',
                'CJPCA risk register, scored before and after '
                'controls.')

    risk_color_rows = {}
    for r_idx, row in enumerate(RISK_ROWS):
        risk_color_rows[r_idx] = {}
        inherent_hex = RISK_COLOR_MAP.get(row[6])
        residual_hex = RISK_COLOR_MAP.get(row[8])
        if inherent_hex:
            risk_color_rows[r_idx][6] = inherent_hex
        if residual_hex:
            risk_color_rows[r_idx][8] = residual_hex

    headers = ['ID', 'Asset', 'STRIDE', 'Threat scenario', 'L', 'I',
               'Inherent', 'Mitigating control (Tier)', 'Residual']
    widths = [0.8, 2.0, 1.2, 3.5, 0.5, 0.5, 1.4, 5.6, 1.5]
    table = doc.add_table(rows=1 + len(RISK_ROWS), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for col_idx, w in enumerate(widths):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)
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
    for r_idx, row_values in enumerate(RISK_ROWS, start=1):
        row = table.rows[r_idx]
        for c_idx, value in enumerate(row_values):
            cell = row.cells[c_idx]
            cell.text = str(value)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            for para in cell.paragraphs:
                for run in para.runs:
                    set_run_style(
                        run, bold=(c_idx == 0),
                        color=DARK_GRAY, size=8)
            color = risk_color_rows.get(r_idx - 1, {}).get(c_idx)
            if color:
                shade_cell(cell, color)
                for para in cell.paragraphs:
                    for run in para.runs:
                        set_run_style(
                            run, bold=True, color=WHITE, size=8)

    add_paragraph(
        doc,
        'After controls are applied, 17 of the 20 catalogued risks '
        'reduce to LOW, three remain at MEDIUM, and zero remain '
        'HIGH or CRITICAL. The three residual MEDIUM risks are '
        'R07 prompt injection, R08 LLM hallucination, and the '
        'related LLM-side risks, acknowledged as the irreducible '
        'residual risk inherent to retrieval-augmented generation '
        'systems.',
    )


def write_a210_security_policies(doc):
    add_heading(doc, 'A2.10 Security Policies', level=2)
    add_paragraph(
        doc,
        'The nine policies below govern day-to-day operation of '
        'CJPCA on the BBK on-premises host. Each entry names the '
        'policy, the enforcement point in the code, and the '
        'review cadence.',
    )
    headers = ['Policy', 'Enforcement point', 'Review']
    rows = [
        (name.split(' ', 1)[1] if ' ' in name else name,
         enforcement.rstrip('.'), review.rstrip('.'))
        for name, _statement, enforcement, review in POLICIES
    ]
    add_caption(doc, 'Table A2.5.', 'Security policies.')
    add_table(
        doc,
        headers=headers,
        rows=rows,
        widths_cm=[5.0, 8.0, 4.0],
        body_size=9,
    )


def write_a211_logs_detection(doc):
    add_heading(doc, 'A2.11 Logs and Detection Flow', level=2)
    add_paragraph(
        doc,
        'Security events travel through five stages: trigger, '
        'middleware, application handler, AuditLog write, and '
        'per-job log file. Three independent stores '
        '(append-only AuditLog table, write-once per-job log '
        'file, and the SHA-256 hash chain footer on exports) '
        'cross-validate one another and satisfy OWASP A09. '
        'Table A2.6 traces three worked examples.',
    )
    add_caption(doc, 'Table A2.6.',
                'Worked examples of logging and detection.')
    add_table(
        doc,
        headers=['Event', 'Trigger and detection chain',
                 'AuditLog action'],
        rows=[
            ('Login failure',
             'Bad password → axes increments counter → 5 fails '
             'in 30 min triggers lockout → Django returns 401',
             'auth.failure (IP, UA, role=anonymous)'),
            ('Prompt injection',
             'Upload PDF with hidden override → Tier-A regex '
             'flags chunk → Tier-B LLM judge classifies '
             '(fail-closed) → QuarantinedChunk row created',
             'ingest.quarantine (doc id, chunk id)'),
            ('Export integrity',
             'Click export → view renders from verified '
             'citations → SHA-256 over identity tuple → first '
             '16 chars stamped in footer',
             'export.create (new hash, prior hash)'),
        ],
        widths_cm=[3.2, 9.0, 4.8],
        body_size=9,
    )


ASSETS_ROWS = [
    ('A1', 'Internal BBK policy corpus', 'High',
     'Discloses the bank procedures, response windows, and control '
     'inventory; the corpus is the primary input to every analysis.'),
    ('A2', 'Generated compliance reports', 'High',
     'May be filed with or shown to regulators, so integrity is '
     'paramount; tampering invalidates the audit chain.'),
    ('A3', 'AuditLog table', 'High',
     'Evidence of who took what action; must be tamper evident and '
     'append only at the application layer.'),
    ('A4', 'User credentials and MFA secrets', 'Critical',
     'Foothold for everything else in the system; compromise '
     'bypasses all downstream controls.'),
    ('A5', 'LLM API key', 'Critical',
     'Direct billing impact and pivot to the LLM endpoint; never '
     'committed and never logged.'),
    ('A6', 'Regulatory corpus and Term Dictionary', 'Medium',
     'Public regulations, but the bank curation and structuring is '
     'proprietary and reveals priorities.'),
    ('A7', 'Application source code', 'Medium',
     'Reveals controls and attack surface to insider threats.'),
    ('A8', 'Embedding and classification models', 'Low',
     'Public BGE and DeBERTa weights with no proprietary data '
     'inside.'),
    ('A9', 'Vector index chroma.sqlite3 and FTS5 bm25.db',
     'High',
     'Encodes the entire searchable corpus including internal '
     'policies; equivalent in sensitivity to A1.'),
]


THREAT_ACTORS_ROWS = [
    ('External opportunistic',
     'Credential stuffing or brute force',
     'Low to Medium', 'Moderate',
     'Axes lockout, MFA, password validators.'),
    ('Insider (curious employee)',
     'Browse outside their RBAC scope', 'Medium', 'Moderate',
     'Group decorators, per-row owner filter, AuditLog.'),
    ('Insider (malicious)',
     'Exfiltrate policies or tamper outputs',
     'Medium to High', 'Low',
     'RBAC, AuditLog, append-only logging, role-at-time snapshot.'),
    ('Compromised dependency',
     'Supply chain (pip, CDN)', 'High', 'Low',
     'Pinned requirements, CDN allowlist, recommended pip-audit.'),
    ('Targeted adversary (nation-state)',
     'Reconnaissance for financial-sector attack',
     'High', 'Low',
     'Defence in depth (Figure 17); operational endpoint '
     'protection by BBK IT.'),
    ('Prompt-injection attacker via uploaded document',
     'Cause the LLM to reveal or perform off-policy actions',
     'Medium', 'Moderate',
     'Two-tier injection defence (Tier-A regex, Tier-B judge), '
     'verbatim citation verifier, NLI gate.'),
    ('Data-poisoning attacker via uploaded document',
     'Cause the retriever to surface a poisoned chunk',
     'Medium', 'Low',
     'QuarantinedChunk review queue, reviewer accept/reject '
     'lifecycle, append-only audit.'),
]


ATTACK_SURFACES_ROWS = [
    ('Login form', 'Brute force',
     'django-axes (5 attempts / 30 min), MFA, strong password '
     'validators.'),
    ('Session cookie', 'Theft via XSS or network MITM',
     'Secure + HttpOnly + SameSite=Lax + HSTS + 1800-second idle '
     'timeout.'),
    ('CSRF', 'Cross-site forged action',
     'CsrfViewMiddleware on every POST; CSRF tokens on every '
     'form.'),
    ('File upload', 'Malicious PDF or DOCX',
     'Suffix whitelist, content-hash dedup, Docling without OCR '
     'extracts text only, hard size cap at the proxy.'),
    ('Document text rendered to UI', 'Stored XSS',
     'Django autoescape on by default; no mark_safe filter on '
     'user document content.'),
    ('Chat free-text input', 'Prompt injection',
     'Tier-A regex pattern detector + Tier-B Claude Haiku judge '
     'wrapped in spotlight delimiters with fail-closed behaviour.'),
    ('Uploaded document content',
     'Indirect prompt injection via the corpus',
     'Verifier requires verbatim grounding; falsified quotes are '
     'auto-dropped; LLM cannot tool-call outside the schema.'),
    ('LLM API key', 'Exposure via logs or error pages',
     'Loaded from .env; never logged; DEBUG=False in production '
     'removes traceback leakage; audit sanitiser strips key '
     'tokens.'),
    ('Static asset CDN', 'Supply chain',
     'Strict CSP with explicit allowlist; recommended SRI hashes '
     'on critical scripts.'),
    ('Django admin', 'Lateral movement after compromise',
     'Admin disabled in production or guarded by extra auth; '
     'staff users have unique credentials and MFA enforced.'),
]


STRIDE_ROWS = [
    ('Spoofing', 'Steal session, impersonate analyst',
     'A4 Credentials + MFA secrets',
     'TOTP MFA, Secure / HttpOnly / SameSite cookies, '
     'IdleSessionTimeoutMiddleware.'),
    ('Tampering',
     'Modify a persisted ObligationMapping or AuditLog row',
     'A2 Reports + A3 AuditLog',
     'Application-layer append-only audit, ORM-only writes, '
     'admin-protected DB, regular backups.'),
    ('Repudiation', 'User denies running a mapping job',
     'A3 AuditLog',
     'AuditLog keyed to user with role-at-time snapshot; cannot '
     'be edited through the UI.'),
    ('Information disclosure',
     'Read internal policy outside RBAC scope',
     'A1 Policy corpus + A9 Indexes',
     'View-level RBAC, per-row owner filter, filter push-down, '
     'CSRF, secure cookies.'),
    ('Denial of service',
     'Saturate the jobs queue or LLM rate limit',
     'All', 'Job concurrency cap, recommended per-user '
     'throttling, LLM retry budget = 2, timeout = 180 s.'),
    ('Elevation of privilege',
     'Analyst gains DPO rights', 'A1, A2, A3',
     'Django groups, admin-only signup, password rotation, '
     'AuditLog on every group change.'),
]


SECURITY_ARCH_ROWS = [
    ('Authentication',
     'Django User with Argon2 (preferred) or PBKDF2-SHA256 hashing. '
     'AUTH_PASSWORD_VALIDATORS enforce ≥12 characters, similarity, '
     'common-password, and custom complexity rules. '
     'AUTHENTICATION_BACKENDS chains axes.backends.AxesStandalone '
     'before the model backend so lockouts apply before credential '
     'check.'),
    ('Multi-factor authentication',
     'django-otp with django-two-factor-auth. TOTP authenticator '
     'app via RFC 6238 and optional backup tokens through '
     'django_otp.plugins.otp_static. The ForceMFAEnrolment '
     'middleware redirects any authenticated user without a '
     'confirmed device to /two_factor/setup/.'),
    ('RBAC and IAM',
     'Django auth groups analyst, reviewer, dpo, and admin. View '
     'enforcement through @role_required decorators in '
     'apps/core/roles.py. Per-row owner enforcement on '
     'MappingAnalysis and ComparisonRun filters by '
     'created_by=request.user unless the user is dpo or admin.'),
    ('Session handling',
     'SESSION_COOKIE_SECURE=True (prod), HttpOnly=True, '
     'SameSite=Lax, SESSION_EXPIRE_AT_BROWSER_CLOSE=True. '
     'IdleSessionTimeoutMiddleware enforces a 1800-second idle '
     'window with redirect to /accounts/login/?reason=idle. '
     'Database-backed session engine cleaned by clearsessions.'),
    ('Encryption',
     'In transit: TLS 1.2+ at the perimeter with HSTS '
     '(SECURE_HSTS_SECONDS=31 536 000 with includeSubDomains and '
     'preload). At rest: passwords hashed (Argon2 / PBKDF2), TOTP '
     'seeds encoded by django-otp, SQLite on a host-encrypted '
     'volume. API keys in .env with file permissions 600.'),
    ('API security',
     'No external REST API. The single outbound LLM call uses an '
     'Authorization: Bearer header issued from the server side, '
     'never from the browser. Each request is logged with a hash '
     'of the body (never the body itself) and the client-side '
     'retry budget is 2.'),
    ('Secure communications',
     'All inbound HTTPS only, HSTS-pinned in production. All '
     'outbound HTTPS only with an explicit allowlist covering '
     'api.openrouter.ai, api.anthropic.com, huggingface.co for '
     'model downloads, and the CSP-listed CDNs.'),
    ('Logging strategy',
     'Module-level loggers writing to console plus per-job log '
     'files at cjpca/logs/run_<job_type>_<id>.log. Sensitive '
     'fields are stripped before persistence by '
     'apps.core.audit.sanitize. DEBUG=False prevents stack '
     'traces from reaching the browser.'),
    ('Monitoring',
     'HTMX polling at 1 to 2 s for job progress; AuditLog '
     'surfaced in the admin dashboard and the analytics '
     'recent-activity widget. Process metrics (CPU, RAM, disk) '
     'are the operator responsibility (Windows Performance '
     'Monitor or equivalent).'),
    ('Alerting',
     'Notification model fires UI alerts on job completion, gap '
     'assignment, and due-date approach. Email alerts deferred '
     'to a future iteration; recommended hook is signals.post_save '
     'on the Gap model.'),
    ('Network segmentation',
     'The BBK workstation lives on the bank compliance VLAN. Only '
     'the perimeter proxy is reachable from the user network. '
     'Outbound traffic is restricted to the configured LLM '
     'endpoint and HuggingFace. SQLite and Chroma stores are '
     'local files with no listening network ports beyond the '
     'Django ASGI socket.'),
    ('Zero-trust principle',
     'Authentication, MFA verification, role, and idle status '
     'are re-checked on every request via middleware rather than '
     'once at login. Identity is verified at each crossing of a '
     'trust boundary, satisfying the per-request re-evaluation '
     'requirement of NIST SP 800-207.'),
    ('Secrets management',
     '.env file at the project root with filesystem-permission '
     '600 in production. cjpca/cjpca/settings.py reads .env at '
     'startup and sets environment variables. No secret is ever '
     'committed; .gitignore excludes .env. Production recommends '
     'a move to Windows Credential Manager or HashiCorp Vault.'),
    ('Input validation',
     'Django forms validate every user input. Pydantic schemas '
     'validate every LLM output. File uploads validate suffix, '
     'size, and content hash. Free-text fields are autoescaped '
     'on render and never reach the database through string '
     'interpolation (ORM only).'),
    ('Output sanitisation',
     'Django template autoescape is on by default. Document '
     'text containing user content renders through {{ chunk.text }} '
     '(escaped); only intentional formatting goes through |safe '
     'on system-generated markup. HTMX partials return HTML and '
     'inherit the same autoescape protections.'),
    ('Secure coding',
     'Static type hints throughout the engines. Pydantic v2 for '
     'schema-checked LLM output. No eval, exec, or pickle.load '
     'on untrusted input. Subprocess invocations use explicit '
     'list arguments with shell=False.'),
    ('Secure deployment',
     'DEBUG=False in production (verified by python manage.py '
     'check --deploy). ALLOWED_HOSTS narrowed to the deployment '
     'hostname. SECRET_KEY rotated and supplied via environment '
     'variable. WhiteNoise serves static files with hashed '
     'filenames and far-future cache headers. HTTPS-only via '
     'the reverse proxy.'),
]


SEC_DEV_ROWS = [
    ('Dependency management',
     'Versions pinned in requirements.txt at the root and in '
     'cjpca/requirements.txt. Recommended pip-audit or safety '
     'report each iteration. HuggingFace model hashes are stored '
     'alongside model snapshots in hf_cache/.'),
    ('Secrets handling',
     '.env only, loaded at Django startup. Never logged. The '
     'audit sanitiser strips fields with keys matching '
     '*key*, *token*, *secret*, *password* before any payload is '
     'persisted to the AuditLog.'),
    ('CI/CD security',
     'No CI configuration is committed today; the recommended '
     'pipeline runs lint, type check, unit tests, integration '
     'tests, pip-audit, bandit static analysis, '
     'manage.py check --deploy, RAGAS evaluation snapshot, build '
     'artefact, then manual approval to deploy.'),
    ('Logging strategy',
     'Module-level loggers, per-job log files for long-running '
     'operations, sanitiser strips secrets, daily rotation with '
     '30-day retention recommended at the operator level.'),
    ('Monitoring strategy',
     'Application metrics through @trace_span decorators '
     'recording job durations; resource metrics via Windows '
     'Performance Monitor. Future iteration: Prometheus '
     'exporter through django-prometheus.'),
    ('Patch management',
     'Python dependencies reviewed monthly. Django security '
     'advisories tracked. HuggingFace model versions pinned and '
     'upgrades validated against the RAGAS evaluation suite '
     'before promotion.'),
    ('Error handling',
     'Exceptions inside reasoning workflows trigger the fallback '
     'node, which emits an empty typed report rather than '
     'propagating up the stack. DEBUG=False in production '
     'replaces stack traces with a friendly 500 page while '
     'per-job log files retain the full traceback for '
     'post-mortem.'),
    ('Security testing',
     'Unit tests for input validation. Integration tests for '
     'view-level authentication and RBAC. Recommended bandit on '
     'every push and pip-audit on every dependency update. '
     'Penetration test scheduled before production cut-over.'),
    ('Incident response readiness',
     'AuditLog is the primary forensic artefact. Per-job logs '
     'are the secondary artefact. Backups of cjpca/db.sqlite3, '
     'chroma_data/, and data/ allow rollback to a known-good '
     'state. The runbook defines incident contacts.'),
    ('DevSecOps applied',
     'Shift-left through Pydantic schemas and verifiers that '
     'catch defects early; threat modelling as design input '
     '(STRIDE outputs became NFRs and constraints); continuous '
     'evaluation through RAGAS snapshots; defence in depth '
     'across the seven tiers; least privilege through '
     'filesystem layout, RBAC, and the outbound allowlist; '
     'auditability through the append-only log.'),
]


def write_a213_security_arch_detail(doc):
    add_heading(doc,
                'A2.13 Security Architecture Implementation Details',
                level=2)
    add_paragraph(
        doc,
        'The main body §3.2.5 enumerates the controls grouped by '
        'OSI tier. This appendix gives the implementation detail '
        'for each control category at the level a maintainer '
        'needs to reproduce the configuration. Each row names '
        'the control surface and the concrete Django, '
        'middleware, or operational setting that enforces it.',
    )
    add_caption(doc, 'Table A2.5.',
                'Security architecture implementation detail.')
    add_table(
        doc,
        headers=['Control surface', 'Implementation detail'],
        rows=SECURITY_ARCH_ROWS,
        widths_cm=[4.2, 12.8],
        body_size=9,
    )


def write_a214_secure_dev_practices(doc):
    add_heading(doc, 'A2.14 Secure Development Practices',
                level=2)
    add_paragraph(
        doc,
        'CJPCA applies DevSecOps practices across dependencies, '
        'secrets, CI/CD, logging, monitoring, patching, error '
        'handling, security testing, and incident response. The '
        'table below records the current practice and the '
        'recommended next step for each area.',
    )
    add_caption(doc, 'Table A2.6.',
                'Secure development practices applied in CJPCA.')
    add_table(
        doc,
        headers=['Practice area', 'Current state and next step'],
        rows=SEC_DEV_ROWS,
        widths_cm=[4.2, 12.8],
        body_size=9,
    )


def write_a212_mfa_flow(doc):
    add_heading(doc, 'A2.12 Login and Multi-Factor Authentication '
                'Flow', level=2)
    add_paragraph(
        doc,
        'Figure 20 traces an account across four swim lanes: '
        'admin provisioning with temporary password plus '
        'force_password_change and mfa_required flags; first '
        'login (password reset → TOTP enrolment); steady-state '
        'login (axes check → PBKDF2 → TOTP via django-otp → '
        '1800-second idle timer); and failed-login lockout on '
        'the fifth failure within 30 minutes.',
    )
    add_figure_placeholder(
        doc, 'Figure 20',
        'CJPCA login and multi-factor authentication flow.')


def write_a215_prompt_injection_flow(doc):
    add_heading(doc, 'A2.15 Prompt Injection Defence Flow', level=2)
    add_paragraph(
        doc,
        'Figure 21 traces an uploaded chunk through the two-tier '
        'injection defence. Tier-A runs nine deterministic regex '
        'rule groups; clean chunks go straight to embedding and '
        'indexing. Flagged chunks cross to Tier-B, the LLM judge '
        'with spotlight delimiters and fail-closed behaviour; an '
        'injection verdict routes the chunk to QuarantinedChunk.',
    )
    add_figure_placeholder(
        doc, 'Figure 21',
        'CJPCA two-tier prompt injection defence flow.')


def write_a216_geofence_flow(doc):
    add_heading(doc, 'A2.16 GeoFence Middleware Flow', level=2)
    add_paragraph(
        doc,
        'Figure 22 traces a request through GeoFenceMiddleware: '
        'read forwarded IP, look up country via MaxMind GeoLite2, '
        'compare against the env-controlled allowlist. Disallowed '
        'countries return 403 and write auth.geofence_block; '
        'private and loopback IPs always pass; the middleware '
        'fails open if GeoLite2 is unavailable to avoid locking '
        'BBK out of its own deployment.',
    )
    add_figure_placeholder(
        doc, 'Figure 22',
        'CJPCA GeoFence middleware flow.')


def write_a217_audit_hash_chain_flow(doc):
    add_heading(doc, 'A2.17 Audit and Hash Chain Flow', level=2)
    add_paragraph(
        doc,
        'Figure 23 traces a mutating action: log_event fires a '
        'signal with actor, action, target, and payload; the '
        'sanitiser strips key/token/secret/password fields; the '
        'handler writes the AuditLog row with '
        'user_role_at_time, the per-job log file captures '
        'context, and any export chains a SHA-256 over the row '
        'identity tuple bound to the prior export, stamping the '
        '16-character prefix into the footer.',
    )
    add_figure_placeholder(
        doc, 'Figure 23',
        'CJPCA audit log and SHA-256 export hash chain flow.')


REFERENCES_3_2 = [
    'Cabane, H., & Farias, K. (2024). On the impact of '
    'event-driven architecture on performance: An exploratory '
    'study. Future Generation Computer Systems, 153, 52-69. '
    'https://doi.org/10.1016/j.future.2023.10.021',

    'Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, '
    'T., & Fritz, M. (2023). Not what you have signed up for: '
    'Compromising real-world LLM-integrated applications with '
    'indirect prompt injection. In Proceedings of the 16th ACM '
    'Workshop on Artificial Intelligence and Security (pp. '
    '79-90). Association for Computing Machinery. '
    'https://doi.org/10.1145/3605764.3623985',

    'Hindi, M., Mohammed, L., Maaz, O., & Alwarafy, A. (2025). '
    'Enhancing the precision and interpretability of '
    'retrieval-augmented generation (RAG) in legal technology: A '
    'survey. IEEE Access, 13, 46171-46189. '
    'https://doi.org/10.1109/ACCESS.2025.3550145',

    'Huang, L., Yu, W., Ma, W., Zhong, W., Feng, Z., Wang, H., '
    'Chen, Q., Peng, W., Feng, X., Qin, B., & Liu, T. (2025). A '
    'survey on hallucination in large language models: '
    'Principles, taxonomy, challenges, and open questions. ACM '
    'Transactions on Information Systems, 43(2), Article 42. '
    'https://doi.org/10.1145/3703155',

    'Kim, J., & Min, M. (2024). From RAG to QA-RAG: Integrating '
    'generative AI for pharmaceutical regulatory compliance '
    'process. In Proceedings of the 40th ACM/SIGAPP Symposium on '
    'Applied Computing (pp. 1295-1303). Association for Computing '
    'Machinery. https://doi.org/10.1145/3672608.3707749',

    'Liu, Y., Jia, Y., Geng, R., Jia, J., & Gong, N. Z. (2024). '
    'Formalizing and benchmarking prompt injection attacks and '
    'defenses. In Proceedings of the 33rd USENIX Security '
    'Symposium (pp. 1831-1847). USENIX Association. '
    'https://www.usenix.org/conference/usenixsecurity24/'
    'presentation/liu-yupei',

    'McKay, K. A., & Cooper, D. A. (2019). Guidelines for the '
    'selection, configuration, and use of Transport Layer '
    'Security (TLS) implementations (NIST Special Publication '
    '800-52 Rev. 2). National Institute of Standards and '
    'Technology. https://doi.org/10.6028/NIST.SP.800-52r2',

    'Özkan, O., Babur, Ö., & van den Brand, M. (2025). '
    'Domain-driven design in software development: A systematic '
    'literature review on implementation, challenges, and '
    'effectiveness. Journal of Systems and Software, 228, '
    'Article 112473. https://doi.org/10.1016/j.jss.2025.112473',

    'OWASP Foundation. (2021). OWASP Top 10:2021. '
    'https://owasp.org/Top10/2021/',

    'OWASP Foundation. (2025). OWASP Top 10 for Large Language '
    'Model applications 2025. '
    'https://genai.owasp.org/resource/'
    'owasp-top-10-for-llm-applications-2025/',

    'Shinn, N., Cassano, F., Berman, E., Gopinath, A., '
    'Narasimhan, K., & Yao, S. (2023). Reflexion: Language agents '
    'with verbal reinforcement learning. In Advances in Neural '
    'Information Processing Systems 36 (pp. 8634-8652). '
    'https://proceedings.neurips.cc/paper_files/paper/2023/'
    'hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html',

    'Tarandach, I., & Coles, M. J. (2020). Threat modeling: A '
    'practical guide for development teams. O\'Reilly Media.',

    'Temoshok, D., Proud-Madruga, D., Choong, Y.-Y., Galluzzo, '
    'R., Gupta, S., LaSalle, C., Lefkovitz, N., & Regenscheid, '
    'A. (2025). Digital identity guidelines (NIST Special '
    'Publication 800-63-4). National Institute of Standards and '
    'Technology. https://doi.org/10.6028/NIST.SP.800-63-4',

    'West, M., & Sartori, A. (2024). Content Security Policy '
    'Level 3 (W3C Working Draft, 22 November 2024). World Wide '
    'Web Consortium. '
    'https://www.w3.org/TR/2024/WD-CSP3-20241122/',
]


def add_reference(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1.0)
    p.paragraph_format.first_line_indent = Cm(-1.0)
    p.paragraph_format.space_after = Pt(8)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(text)
    set_run_style(run, color=DARK_GRAY, size=10.5)


def write_references_3_2(doc):
    add_heading(doc, 'References for §3.2', level=2)
    add_paragraph(
        doc,
        'The references below are cited in §3.2 Solution Design. '
        'Five anchor the design-methodology, architectural, and '
        'algorithmic decisions (Cabane & Farias, Hindi et al., '
        'Kim & Min, Özkan et al., Shinn et al.). The remaining '
        'eight anchor the cybersecurity subsections (§3.2.5 '
        'through §3.2.8): Greshake et al. (2023) and Liu et al. '
        '(2024) on prompt-injection threat models; Huang et al. '
        '(2025) on the hallucination taxonomy; McKay and Cooper '
        '(2019) on TLS guidance; Temoshok et al. (2025) on NIST '
        'digital-identity guidelines; Tarandach and Coles (2020) '
        'on STRIDE-based threat modelling; West and Sartori '
        '(2024) on Content Security Policy; and the two OWASP '
        'Foundation references for the web and LLM Top 10 risk '
        'catalogues. No reference duplicates one used in §2.1 '
        'Related Theory, Appendix 1, §3.4 Testing, or §4 '
        'Discussion, and all are 2019 or later.',
    )
    for ref in REFERENCES_3_2:
        add_reference(doc, ref)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '3_2_solution_design_combined.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = (out_dir /
                             f'3_2_solution_design_combined_v{n}'
                             '.docx')
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    # Main body
    write_intro(doc)
    write_320_methodologies(doc)
    write_321_data_structures(doc)
    write_322_design_diagrams(doc)
    write_323_algorithms(doc)
    write_324_architecture(doc)
    write_325_security(doc)
    write_326_threat_model(doc)
    write_327_controls_mapping(doc)
    write_328_owasp_coverage(doc)
    write_329_traceability(doc)
    write_references_3_2(doc)

    # Appendix
    write_appendix_intro(doc)
    write_a21_traceability(doc)
    write_a22_key_data_structures(doc)
    write_a23(doc)
    write_a25(doc)
    write_a27(doc)
    write_a28(doc)
    write_a29_risk_assessment(doc)
    write_a210_security_policies(doc)
    write_a211_logs_detection(doc)
    write_a212_mfa_flow(doc)
    write_a213_security_arch_detail(doc)
    write_a214_secure_dev_practices(doc)
    write_a215_prompt_injection_flow(doc)
    write_a216_geofence_flow(doc)
    write_a217_audit_hash_chain_flow(doc)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
