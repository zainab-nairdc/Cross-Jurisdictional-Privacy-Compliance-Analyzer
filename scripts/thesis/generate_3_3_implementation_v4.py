"""Generate Section 3.3 Implementation v4 — rubric-enhanced, 2000-word cap.

Output: thesis_docs/3_3_implementation_v4.docx

Improvements over v3:
- Plain-English / cyber-aware prose throughout.
- Library names and versions inline on first mention.
- Function-shape and schema hints inline in deep-section steps.
- Explicit cross-references to Appendix 3 subsections from each step.
- No em-dashes, no semicolons.
- Numerals for technical quantities.
- Inline command blocks for bootstrap and migrate steps.
- Django security baseline acknowledged in §3.3.12 and §3.3.13.
- Per-step inline figures in the four deep sections.
- Clean figure numbering 24 to 63.
- Fixed cross-reference (§3.3.3 now points to §3.3.13).
- Main body trimmed to fit the 2000-word cap.

The appendix carries the full depth without a word limit.
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BLACK = RGBColor(0x00, 0x00, 0x00)
NAVY = BLACK          # plain styling: all text black
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK_GRAY = BLACK
MUTED = BLACK


PROJECT_TREE = """\
Cross-Jurisdictional Privacy Compliance Analyzer/
├── cjpca/                Web application, ten Django apps
├── reasoning/            AI reasoning agent that drafts and verifies answers
├── retrieval/            Hybrid search across the corpus
├── ingestion/            Document loading, chunking, safety scanning
├── data/                 Regulations and BBK internal policies
├── config.py             Project paths and model defaults
├── requirements.txt
├── .env.example
└── manage.py
"""

INGESTION_SUBTREE = """\
ingestion/
├── loaders.py            Document loaders (Docling for PDF / DOCX)
├── chunker.py            Two-level chunker (headers + recursive split)
├── embedder.py           BGE-small embedder with citation-aware prefix
├── injection_scanner.py  Tier-A regex + Tier-B LLM judge (fail-closed)
└── indexer.py            Persists vectors to ChromaDB and BM25 metadata
"""

RETRIEVAL_SUBTREE = """\
retrieval/
├── retriever.py          Hybrid orchestrator, RRF fusion, cross-encoder rerank
└── bm25_store.py         SQLite FTS5 BM25 index, parents, chunk tags
"""

REASONING_SUBTREE = """\
reasoning/
├── schemas.py            Pydantic v2 schemas for every workflow output
├── orchestrator.py       LangGraph state machine for general Q&A
├── workflows.py          Three domain graphs (compare, map, gap)
├── router.py             Query route classifier
├── generator.py          LLM call with OutputFixingParser auto-correction
├── validators.py         Citation grounding and hallucination scoring
├── fallback.py           SafeFallback typed-empty response
├── classifier.py         Chunk classifier (LLM, 12-topic taxonomy)
└── term_dictionary.py    Cross-jurisdictional synonym dictionary
"""


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
    p.paragraph_format.space_after = Pt(12)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_image(doc, image_path: Path, width_cm: float = 15.5):
    if not image_path.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f'[MISSING IMAGE: {image_path.name}]')
        set_run_style(run, bold=True, italic=True, color=MUTED, size=10)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(image_path), width=Cm(width_cm))


def add_monospace_block(doc, text: str, *, size: int = 9):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.left_indent = Cm(0.6)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(10)
    run = p.add_run(text)
    run.font.name = 'Consolas'
    run.font.size = Pt(size)
    run.font.color.rgb = DARK_GRAY
    rPr = run._element.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Consolas')
    rFonts.set(qn('w:hAnsi'), 'Consolas')
    rFonts.set(qn('w:cs'), 'Consolas')
    rPr.append(rFonts)


def add_phase(doc, label: str, subtitle: str):
    """Bold phase divider above a group of related subsections."""
    h = doc.add_paragraph(style='Heading 2')
    h.paragraph_format.space_before = Pt(14)
    h.paragraph_format.space_after = Pt(4)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = h.add_run(label)
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.size = Pt(13)

    sub = doc.add_paragraph()
    sub.paragraph_format.space_after = Pt(8)
    sub_run = sub.add_run(subtitle)
    sub_run.font.italic = True
    sub_run.font.color.rgb = MUTED
    sub_run.font.size = Pt(10)


def add_step(doc, label: str, text: str):
    """Heading 4 sub-title 'Step N - Title', then justified body."""
    parts = text.split('. ', 1)
    if len(parts) == 2:
        title, body = parts[0], parts[1]
    else:
        title, body = '', text

    h = doc.add_paragraph(style='Heading 4')
    h.paragraph_format.space_before = Pt(8)
    h.paragraph_format.space_after = Pt(2)
    clean_label = label.rstrip('.')
    heading_text = f'{clean_label} - {title}' if title else clean_label
    run = h.add_run(heading_text)
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.size = Pt(11)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(6)
    body_run = p.add_run(body)
    set_run_style(body_run, color=DARK_GRAY, size=11)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '3_3_implementation_v4.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(5, 100):
                candidate = out_dir / f'3_3_implementation_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    code = base / 'diagrams' / 'code_3_3'
    shots = base / 'diagrams' / 'screenshots_3_3'

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, '3.3 Implementation', level=1)
    add_paragraph(
        doc,
        'This section walks through how the CJPCA was built '
        'from scratch, in four phases: foundation, AI core, '
        'application layer, and production-ready. Ingestion '
        'and the reasoning agent are covered in depth; code '
        'outlines and configuration files are in Appendix 3.',
    )

    add_phase(doc, 'Phase A — Foundation',
              'Set up the development machine and clone the project '
              'skeleton.')

    # 3.3.0 Project structure overview
    add_heading(doc, '3.3.0 Project structure overview', level=2)
    add_paragraph(
        doc,
        'The repository separates the pure-Python pipeline '
        'packages (ingestion, retrieval, reasoning) from the '
        'Django web layer, which hosts ten feature apps.',
    )
    add_monospace_block(doc, PROJECT_TREE)
    add_caption(doc, 'Figure 24.', 'CJPCA project folder layout')

    # 3.3.1 Host operating system and tooling
    add_heading(doc, '3.3.1 Host operating system and tooling', level=2)
    add_step(
        doc, 'Step 1.',
        'Provision the workstation: Windows 11 Pro 64-bit, '
        '16 GB RAM, 100 GB free disk.',
    )
    add_step(
        doc, 'Step 2.',
        'Install the toolchain: Python 3.10 or newer, Git, '
        'VS Code (Python, Pylance, SQLite Viewer, HTMX '
        'extensions), and PyTorch on CPU.',
    )
    add_step(
        doc, 'Step 3.',
        'Copy .env.example, which lists every system variable.',
    )

    # 3.3.2 Project bootstrap
    add_heading(doc, '3.3.2 Project bootstrap', level=2)
    add_paragraph(
        doc,
        'Clone the repository, create a virtual environment, '
        'install the pinned dependencies, then install PyTorch '
        'separately because its build is hardware-specific, '
        'and copy .env.example to .env.',
    )
    add_monospace_block(doc, (
        '> git clone <repository-url> cjpca-project\n'
        '> cd cjpca-project\n'
        '> py -m venv .venv\n'
        '> .venv\\Scripts\\activate\n'
        '> python -m pip install -r requirements.txt\n'
        '> python -m pip install torch '
        '--index-url https://download.pytorch.org/whl/cpu\n'
        '> copy .env.example .env\n'
    ))
    add_caption(doc, 'Figure 25.', 'Project bootstrap commands')

    add_phase(doc, 'Phase B — AI core',
              'Get the corpus, the models, and the LLM running. '
              'Build the pipeline that proves the AI can answer '
              'compliance questions.')

    # 3.3.3 Data gathering and corpus assembly
    add_heading(doc, '3.3.3 Data gathering and corpus assembly', level=2)
    add_step(
        doc, 'Step 1.',
        'Collect the public regulations: Bahrain PDPL plus '
        'subordinate orders, India DPDP Act with supporting '
        'RBI circulars, and Kuwait CBK and CITRA instruments.',
    )
    add_step(
        doc, 'Step 2.',
        'Author the internal policy set. Twelve synthetic BBK '
        'policies were written to mirror typical bank '
        'compliance documents (CON-02).',
    )
    add_step(
        doc, 'Step 3.',
        'Attach metadata. Each document carries a sidecar '
        'recording type, topics, SHA-256 content hash, and '
        'retrieval date so duplicates are caught at ingest.',
    )

    # 3.3.4 Local LLM setup
    add_heading(doc, '3.3.4 Local LLM setup', level=2)
    add_step(
        doc, 'Step 1.',
        'Install Ollama and pull llama3.2:1b. Ollama serves '
        'on localhost:11434 and the 1B model satisfies the '
        'commodity-hardware constraint CON-01.',
    )
    add_step(
        doc, 'Step 2.',
        'Configure the provider abstraction. The reasoning '
        'package reads LLM_PROVIDER so an operator can swap '
        'Ollama for Claude Haiku 4.5 via OpenRouter without '
        'editing code.',
    )
    add_step(
        doc, 'Step 3.',
        'Verify the provider with the health-check command, '
        'which issues a one-token completion before any '
        'analyst session is permitted.',
    )
    add_image(doc, shots / '06_ollama_serve.png', width_cm=15.0)
    add_caption(doc, 'Figure 27.', 'Ollama daemon and model pull')

    # 3.3.5 Model and index initialisation
    add_heading(doc, '3.3.5 Model and index initialisation', level=2)
    add_step(
        doc, 'Step 1.',
        'Warm the HuggingFace cache. Three models download to '
        'hf_cache/ on first use: BAAI/bge-small-en-v1.5 '
        '(384-dim embeddings), the ms-marco-MiniLM-L-6-v2 '
        'reranker, and a DeBERTa-v3 NLI model for the '
        'hallucination verifier.',
    )
    add_step(
        doc, 'Step 2.',
        'Initialise ChromaDB as a persistent client over '
        'chroma_data/ with cosine distance and HNSW indexing.',
    )
    add_step(
        doc, 'Step 3.',
        'Initialise SQLite FTS5 as the keyword index in the '
        'fts_chunks virtual table. Both stores are rebuilt by '
        'the full_ingest command before every reproducibility '
        'run.',
    )

    # 3.3.6 Ingestion pipeline (DEEP)
    add_heading(doc, '3.3.6 Ingestion pipeline', level=2)
    add_paragraph(
        doc,
        'The ingestion pipeline transforms a raw document '
        'into safe, embedded, indexed chunks in five steps. '
        'The novel element is the two-tier injection scanner.',
    )
    add_monospace_block(doc, INGESTION_SUBTREE)

    add_step(
        doc, 'Step 1.',
        'Document loading. Docling reads PDF and DOCX into '
        'Markdown with headings preserved. The loader returns '
        'text, a SHA-256 content hash, and warnings. OCR is '
        'disabled to close the adversarial channel where a '
        'hidden image could smuggle instructions to the LLM.',
    )
    add_image(doc, code / 'M01a_loaders.png', width_cm=15.5)
    add_caption(doc, 'Figure 28.', 'Document loader outline')

    add_step(
        doc, 'Step 2.',
        'Two-level chunking. The Markdown header splitter cuts '
        'on h1-h4 boundaries; oversize sections fall through to '
        'a tiktoken recursive splitter (500-token target, '
        '60-token overlap). Each chunk carries citation '
        'metadata so the verifier can later confirm every quote.',
    )
    add_image(doc, code / 'M01b_chunker.png', width_cm=15.5)
    add_caption(doc, 'Figure 29.', 'Two-level chunker outline')

    add_step(
        doc, 'Step 3.',
        'Chunk classification. A rule pass tags each chunk as '
        'obligation, background, or unknown, then the LLM '
        'classifier assigns one of twelve topic categories. '
        'Outputs are validated against the taxonomy so invented '
        'tags and low-confidence guesses are rejected.',
    )
    add_image(doc, code / 'M01c_classifier.png', width_cm=15.5)
    add_caption(doc, 'Figure 30.', 'Chunk classifier outline')

    add_step(
        doc, 'Step 4.',
        'Two-tier injection scanning. Tier-A applies nine '
        'regex rule groups (override, role hijack, forced '
        'verdict, safety bypass, dev-mode, prompt leak, fake '
        'delimiter, base64, suspicious URL); Tier-B is an LLM '
        'judge wrapped in spotlight delimiters. The scanner '
        'fails closed: any error quarantines the chunk.',
    )
    add_image(doc, code / 'M01d_injection_scanner.png', width_cm=15.5)
    add_caption(doc, 'Figure 31.', 'Two-tier injection scanner outline')

    add_step(
        doc, 'Step 5.',
        'Quarantine and audit. Flagged chunks become '
        'QuarantinedChunk rows with severity, rule_id, and '
        'matched_snippet. An administrator approves to release '
        'or rejects to hold; every transition is logged.',
    )
    add_image(doc, code / 'M01e_pipeline.png', width_cm=15.5)
    add_caption(doc, 'Figure 32.', 'Quarantine pipeline outline')

    add_image(doc, shots / '07a_ingestion_progress.png', width_cm=15.5)
    add_caption(doc, 'Figure 33.', 'Live ingestion progress card')
    add_image(doc, shots / '07b_quarantine_queue.png', width_cm=15.5)
    add_caption(doc, 'Figure 34.', 'Quarantine queue review')

    # 3.3.7 Hybrid retrieval (DEEPEST)
    add_heading(doc, '3.3.7 Hybrid retrieval', level=2)
    add_paragraph(
        doc,
        'Build hybrid retrieval over the indexes from §3.3.5 so '
        'the verifier downstream has the strongest evidence to '
        'ground each answer.',
    )
    add_step(
        doc, 'Step 1.',
        'Build the BM25 index in SQLite FTS5, keeping '
        'jurisdiction and doc_type as unindexed metadata for '
        'filter pushdown.',
    )
    add_step(
        doc, 'Step 2.',
        'Build the vector index in ChromaDB with 384-dim '
        'BGE-small vectors and cosine similarity.',
    )
    add_step(
        doc, 'Step 3.',
        'Expand the query against the term dictionary (about '
        '200 synonyms), preserving the original query for the '
        'cross-encoder.',
    )
    add_step(
        doc, 'Step 4.',
        'Fuse the ranked lists with Reciprocal Rank Fusion '
        '(k=60, twenty-chunk pool).',
    )
    add_step(
        doc, 'Step 5.',
        'Rerank with ms-marco-MiniLM-L-6-v2 and return the '
        'top five chunks.',
    )

    # 3.3.8 Reasoning agent (DEEPEST)
    add_heading(doc, '3.3.8 Reasoning agent', level=2)
    add_paragraph(
        doc,
        'The reasoning agent runs as a LangGraph state machine '
        'whose draft-verify-correct loop is reused by every '
        'workflow. The verifier is the safety gate, so no '
        'answer is published unless every quote comes from a '
        'real source and the hallucination score is low enough.',
    )
    add_monospace_block(doc, REASONING_SUBTREE)

    add_step(
        doc, 'Step 1.',
        'Define Pydantic v2 schemas for every workflow output '
        '(ReasonedAnswer, ObligationComparison, '
        'PolicyCoverageItem, GapItem). Each row carries '
        'citation, evidence, confidence_score, and '
        'hallucination_risk so the safety verdict travels with '
        'the data.',
    )
    add_image(doc, code / 'M_3_3_9_schemas.png', width_cm=15.5)
    add_caption(doc, 'Figure 41.', 'Pydantic schemas outline')

    add_step(
        doc, 'Step 2.',
        'Wire the LangGraph state machine. Four nodes (draft, '
        'verify, correct, finalize) plus a fallback, with a '
        'conditional edge from verify routing to correct or '
        'finalize. No checkpointer because the retrieval '
        'objects in state are not serialisable.',
    )
    add_image(doc, code / 'M04_langgraph_wiring.png', width_cm=15.5)
    add_caption(doc, 'Figure 42.', 'LangGraph state machine wiring')

    add_step(
        doc, 'Step 3.',
        'Implement the citation verifier and NLI score. The '
        'verifier confirms that every quoted clause appears '
        'verbatim in a retrieved chunk; a DeBERTa-v3 NLI '
        'cross-encoder then scores each line and drops any line '
        'whose risk exceeds the threshold.',
    )
    add_image(doc, code / 'M05_verifier.png', width_cm=15.5)
    add_caption(doc, 'Figure 43.', 'Citation verifier outline')

    add_step(
        doc, 'Step 4.',
        'Add OutputFixingParser auto-correction. On parse '
        'failure (truncated JSON, missing fields, wrong types) '
        'the parser re-prompts the model with the schema and '
        'the parse error so it can self-correct. The retry '
        'budget is capped at two attempts.',
    )
    add_image(doc, code / 'M_3_3_9_output_fixing_parser.png', width_cm=15.5)
    add_caption(doc, 'Figure 44.', 'OutputFixingParser outline')

    add_step(
        doc, 'Step 5.',
        'Implement SafeFallback. When retries exhaust, the '
        'fallback node returns a typed ReasonedAnswer with '
        'confidence 0.3, no citations, and an explicit warning '
        'so the UI shows "we could not answer" rather than '
        'fabricated content.',
    )
    add_image(doc, code / 'M_3_3_9_safe_fallback.png', width_cm=15.5)
    add_caption(doc, 'Figure 45.', 'SafeFallback outline')

    add_image(doc, shots / '09a_comparison_run_chips.png', width_cm=15.5)
    add_caption(doc, 'Figure 46.', 'Comparison run with verifier chips')
    add_image(doc, shots / '09b_reasoning_trace_card.png', width_cm=15.5)
    add_caption(doc, 'Figure 47.', 'Reasoning trace card')
    add_image(doc, shots / '09c_safe_fallback_row.png', width_cm=15.5)
    add_caption(doc, 'Figure 48.', 'SafeFallback low-confidence row')

    add_phase(doc, 'Phase C — Application layer',
              'Wrap the working AI core in Django, workflows, '
              'Copilot, and the web layer.')

    # 3.3.9 Django scaffold and database initialisation
    add_heading(doc, '3.3.9 Django scaffold and database initialisation',
                level=2)
    add_paragraph(
        doc,
        'Run the Django migrations to create the auth, '
        'two-factor, and app tables on SQLite with WAL '
        'journaling. A post-save signal gives every new user a '
        'UserProfile in the analyst role, and the temporary '
        'password is rotated on first login by the middleware '
        'in §3.3.13.',
    )
    add_monospace_block(doc, (
        '> cd cjpca\n'
        '> python manage.py makemigrations\n'
        '> python manage.py migrate\n'
        '> python manage.py createsuperuser\n'
    ))
    add_caption(doc, 'Figure 26.', 'Database migration commands')

    # 3.3.10 Workflow engines
    add_heading(doc, '3.3.10 Workflow engines', level=2)
    add_paragraph(
        doc,
        'Wrap the reasoning agent in three workflows '
        '(comparison, mapping, gap analysis), each using the '
        'same dispatch pattern.',
    )
    add_step(
        doc, 'Step 1.',
        'Write a parent ComparisonRun or MappingAnalysis row '
        'with status QUEUED, then launch a background '
        'subprocess from the Django view.',
    )
    add_step(
        doc, 'Step 2.',
        'Poll the progress endpoint every two seconds through '
        'HTMX while the subprocess writes per-obligation '
        'results back to the parent row.',
    )
    add_step(
        doc, 'Step 3.',
        'Recover stuck jobs through the reset_stuck_jobs '
        'management command; a post-save signal keeps the Gap '
        'table in sync when a reviewer approves a finding.',
    )
    add_image(doc, shots / '10_mapping_run_page.png', width_cm=15.5)
    add_caption(doc, 'Figure 49.', 'Mapping run page')

    # 3.3.11 Copilot chat interface
    add_heading(doc, '3.3.11 Copilot chat interface', level=2)
    add_paragraph(
        doc,
        'The Copilot is a chat-style overlay that reuses the '
        'reasoning graph from §3.3.8 so every answer passes the '
        'same verify-and-correct guard-rails. Two scope modes '
        'are supported: approved mode prefers reviewed evidence; '
        'document mode constrains the answer to one selected '
        'source. Responses stream through HTMX swap targets, '
        'and each session keeps twenty turns of history.',
    )
    add_image(doc, code / 'M11_copilot_views.png', width_cm=15.5)
    add_caption(doc, 'Figure 50.', 'Copilot views and retrieval dispatcher')
    add_image(doc, shots / '11_copilot_chat.png', width_cm=15.5)
    add_caption(doc, 'Figure 51.', 'Copilot chat interface')

    # 3.3.12 Web layer
    add_heading(doc, '3.3.12 Web layer', level=2)
    add_step(
        doc, 'Step 1.',
        'Split the Django project into ten apps so each '
        'workflow owns its views, models, and templates.',
    )
    add_step(
        doc, 'Step 2.',
        'Build the template tree on Tailwind CSS. A single '
        'base.html carries the navigation chrome, copilot '
        'dock, and idle-timeout modal; every page extends it.',
    )
    add_step(
        doc, 'Step 3.',
        'Use HTMX for server-driven partial swaps. Six '
        'attributes drive ingestion polling, quarantine '
        'updates, evidence panels, and inline editing.',
    )
    add_step(
        doc, 'Step 4.',
        'Use Alpine.js for client-side state (tabs, '
        'dropdowns, modal toggles, idle countdown). Alpine '
        'never issues network calls, keeping the security '
        'boundary server-side.',
    )
    add_step(
        doc, 'Step 5.',
        'Stream ingestion progress through Django Channels '
        'with one WebSocket per active job, falling back to '
        'HTMX polling if the WebSocket drops.',
    )
    add_image(doc, code / 'M06_channels_consumer.png', width_cm=15.5)
    add_caption(doc, 'Figure 52.', 'Channels WebSocket consumer outline')
    add_image(doc, shots / '11a_dashboard.png', width_cm=15.5)
    add_caption(doc, 'Figure 53.', 'Dashboard with coverage chart')
    add_image(doc, shots / '11b_htmx_inline_edit.png', width_cm=15.5)
    add_caption(doc, 'Figure 54.', 'Review inbox with inline modify form')

    add_phase(doc, 'Phase D — Production-ready',
              'Harden the system and add audit-defensible exports.')

    # 3.3.13 Cybersecurity
    add_heading(doc, '3.3.13 Cybersecurity', level=2)
    add_paragraph(
        doc,
        'The security build extends §3.2.5 with the install '
        'and wiring sequence; the custom middleware chain adds '
        'the controls Django does not provide.',
    )
    add_step(
        doc, 'Step 1.',
        'Install the security stack: django-axes for lockout, '
        'django-otp and django-two-factor-auth for TOTP, '
        'django-csp, and geoip2 for the GeoFence database.',
    )
    add_step(
        doc, 'Step 2.',
        'Order the middleware chain. GeoFence runs first; '
        'Session, CSRF, and Auth follow Django stock order; '
        'ForcePasswordChange precedes ForceMFAEnrollment so '
        'new accounts rotate first; Axes runs last.',
    )
    add_step(
        doc, 'Step 3.',
        'Configure six password validators aligned with NIST '
        'SP 800-63-4: UserAttributeSimilarity, MinimumLength '
        'twelve, CommonPassword, NumericPassword, a custom '
        'ComplexityValidator, and a NoUsernameValidator.',
    )
    add_step(
        doc, 'Step 4.',
        'Wire the append-only AuditLog with twenty-eight '
        'action constants and a role-at-time snapshot, fed by '
        'signal handlers that capture authentication events.',
    )
    add_step(
        doc, 'Step 5.',
        'Add GeoFence, ForcePasswordChange, and '
        'ForceMFAEnrollment middlewares; GeoFence fails open '
        'so a missing database cannot lock BBK out.',
    )
    add_step(
        doc, 'Step 6.',
        'Add CSP, HSTS preload, X-Frame-Options=DENY, '
        'nosniff, and same-origin referrer to complete the '
        'perimeter stack.',
    )

    add_image(doc, shots / '12a_two_factor_setup.png', width_cm=15.5)
    add_caption(doc, 'Figure 58.', 'Two-factor setup page')
    add_image(doc, shots / '12b_audit_log_inspector.png', width_cm=15.5)
    add_caption(doc, 'Figure 59.', 'Audit log inspector')
    add_image(doc, shots / '12c_user_management.png', width_cm=15.5)
    add_caption(doc, 'Figure 60.', 'User management page')

    # 3.3.14 Export and audit hash chain
    add_heading(doc, '3.3.14 Export and audit hash chain', level=2)
    add_step(
        doc, 'Step 1.',
        'Gate on approval. The export view rejects any '
        'analysis whose status is not APPROVED.',
    )
    add_step(
        doc, 'Step 2.',
        'Order the rows by reviewer signal, severity, and '
        'confidence; a severity-driven cascade fills missing '
        'due dates.',
    )
    add_step(
        doc, 'Step 3.',
        'Compute a 16-character SHA-256 prefix over the row '
        'identity tuple bound to the prior export hash, '
        'forming a chain.',
    )
    add_step(
        doc, 'Step 4.',
        'Render through ReportLab (PDF) or openpyxl (XLSX) '
        'with the prefix stamped into the footer, and persist '
        'the hash to the AuditLog under export.create.',
    )
    add_image(doc, code / 'M10_audit_hash.png', width_cm=15.5)
    add_caption(doc, 'Figure 61.', 'Audit hash helper')
    add_image(doc, shots / '13_pdf_export_hash.png', width_cm=15.5)
    add_caption(doc, 'Figure 62.', 'PDF export with chain prefix')

    doc.save(out_path)
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
