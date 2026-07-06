"""Generate Section 3.3 Implementation as a Word document.

Output: thesis_docs/3_3_implementation.docx

Structure: 13 chronological phases plus a project-structure opener.
Two deepest phases (retrieval, reasoning) and two deep phases (ingestion,
cybersecurity) receive replication-quality step-by-step walkthroughs.
The remaining phases are light narrative bridges so the chapter reads as
a continuous build sequence from clean Windows host to live system.

Figure numbering continues from §3.2.5 (last figure: 23). §3.3 figures
run 24 through 57.
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


PROJECT_TREE = """\
Cross-Jurisdictional Privacy Compliance Analyzer/
├── cjpca/                Django project + ten apps
│   ├── cjpca/            Settings, URL conf, ASGI, WebSocket routing
│   └── apps/             accounts, analytics, comparison, core, history,
│                         home, ingestion, library, mapping, review
├── reasoning/            LangGraph agent, schemas, verifier, fallback
├── retrieval/            BM25 over FTS5, Chroma vector search, RRF, rerank
├── ingestion/            Loaders, chunker, embedder, injection scanner
├── data/                 Regulations corpus + BBK internal policies
├── config.py             Root paths, models, embedding parameters
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
├── workflow_helpers.py   Per-row NLI scorer used by verify nodes
├── router.py             Query route classifier (open / compare / map / gap)
├── generator.py          LLM call with OutputFixingParser auto-correction
├── validators.py         Citation grounding and hallucination scoring
├── fallback.py           SafeFallback typed-empty response
├── classifier.py         Chunk classifier (obligation / background)
├── config.py             Reasoning configuration (Pydantic BaseSettings)
├── llm_shims.py          Unified LLM call surface for router and classifier
├── tracing.py            Span-style trace context manager
├── term_dictionary.py    Cross-jurisdictional synonym dictionary
└── taxonomy.py           Twelve-topic classification taxonomy
"""


# ─────────────────────────── Style helpers ────────────────────────────────

def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tc_pr.append(shd)


def set_run_style(run, *, bold=False, italic=False, color=NAVY, size=11,
                  font_name=None):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)
    if font_name:
        run.font.name = font_name


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
    """Render a code or tree block with a left-aligned monospace font."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.left_indent = Cm(0.6)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(10)
    run = p.add_run(text)
    run.font.name = 'Consolas'
    run.font.size = Pt(size)
    run.font.color.rgb = DARK_GRAY
    # Set East-Asian font fallback so the monospace renders everywhere
    rPr = run._element.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Consolas')
    rFonts.set(qn('w:hAnsi'), 'Consolas')
    rFonts.set(qn('w:cs'),    'Consolas')
    rPr.append(rFonts)


def add_step(doc, label: str, text: str):
    """Render a numbered build step with a sub-heading and a body
    paragraph.

    Input format: ``text`` should be ``"Title. Body content..."``. The
    first sentence becomes a navy Heading 4 sub-heading; the rest
    becomes the justified body paragraph beneath it.
    """
    parts = text.split('. ', 1)
    if len(parts) == 2:
        title, body = parts[0], parts[1]
    else:
        title, body = '', text

    # Step sub-heading: "Step N — Title"
    h = doc.add_paragraph(style='Heading 4')
    h.paragraph_format.space_before = Pt(8)
    h.paragraph_format.space_after = Pt(2)
    clean_label = label.rstrip('.')
    heading_text = f'{clean_label} — {title}' if title else clean_label
    run = h.add_run(heading_text)
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.size = Pt(11)

    # Step body paragraph
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(6)
    body_run = p.add_run(body)
    set_run_style(body_run, color=DARK_GRAY, size=11)


# ───────────────────────────── Document body ──────────────────────────────

def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '3_3_implementation.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
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
        'This section describes the construction of the Cross-Jurisdictional '
        'Privacy Compliance Analyzer end to end, from a clean Windows host '
        'through to the live system on the BBK workstation. The build is '
        'organised chronologically. Four subsections (ingestion, hybrid '
        'retrieval, reasoning agent, and cybersecurity) carry replication-'
        'quality detail in the main body. The Copilot chat interface and '
        'the web layer receive medium coverage. The remaining subsections '
        'narrate the supporting work and refer the reader to Appendix 3 '
        'for full setup commands and code outlines.',
    )

    # ─── 3.3.0 Project structure overview ─────────────────────────────────
    add_heading(doc, '3.3.0 Project structure overview', level=2)
    add_paragraph(
        doc,
        'The repository separates the pure-Python pipeline from the Django '
        'web layer. Three pipeline packages (ingestion, retrieval, '
        'reasoning) hold the algorithmic core. The Django project hosts ten '
        'feature apps, the security middleware chain, and the templates. '
        'A single root configuration file binds shared paths, embedding '
        'parameters, and the local language-model defaults.',
    )
    add_monospace_block(doc, PROJECT_TREE)
    add_image(doc, shots / '00_vscode_layout.png', width_cm=15.5)
    add_caption(doc, 'Figure 24.', 'CJPCA project folder layout')

    # ─── 3.3.1 Host operating system and tooling (Phase 0) ────────────────
    add_heading(doc, '3.3.1 Host operating system and tooling', level=2)
    add_paragraph(
        doc,
        'Development runs on Windows 11 Pro with Python 3.10 or newer, '
        'Git, and Visual Studio Code (Python, Pylance, SQLite Viewer '
        'extensions). 16 GB RAM and 100 GB free disk are required for '
        'the model cache and vector index.',
    )

    # ─── 3.3.2 Project bootstrap (Phase 1) ────────────────────────────────
    add_heading(doc, '3.3.2 Project bootstrap', level=2)
    add_paragraph(
        doc,
        'The repository is cloned into a working directory, a virtual '
        'environment is created with the Python launcher, and dependencies '
        'are installed from a pinned requirements file. PyTorch is '
        'installed separately from its own distribution channel because the '
        'correct build depends on the host CPU and any CUDA capability. The '
        'environment file is copied from its template and populated with '
        'the local-LLM endpoint and the security toggles described in '
        'Appendix 3.',
    )
    add_image(doc, shots / '02_pip_install.png', width_cm=15.0)
    add_caption(doc, 'Figure 26.', 'Virtual environment and requirements install')

    # ─── 3.3.3 Django scaffold and database initialisation (Phase 2) ──────
    add_heading(doc, '3.3.3 Django scaffold and database initialisation',
                level=2)
    add_paragraph(
        doc,
        'The Django project uses SQLite with write-ahead logging for crash '
        'safety. The migration sequence applies the contributed schemas '
        '(auth, sessions, admin), the django-otp and two-factor schemas, '
        'and the ten project apps. A signal creates a UserProfile row with '
        'role analyst on every user creation, so role lookups never miss. A '
        'superuser is created with the management command and the temporary '
        'password is rotated on first login by the force-password-change '
        'middleware described in §3.3.12.',
    )
    add_image(doc, shots / '03_migrate.png', width_cm=15.0)
    add_caption(doc, 'Figure 27.', 'Database migration sequence')

    # ─── 3.3.4 Data gathering and corpus assembly (Phase 3) ───────────────
    add_heading(doc, '3.3.4 Data gathering and corpus assembly', level=2)
    add_paragraph(
        doc,
        'The corpus combines three jurisdictional regulations and a set of '
        'BBK internal policies. The Bahrain PDPL and its implementing '
        'orders were obtained from the Legal Affairs Bureau portal. The '
        'India Digital Personal Data Protection Act 2023 was obtained from '
        'the Ministry of Electronics and Information Technology gazette. '
        'The Kuwait Data Privacy Protection Regulation was obtained from '
        'CITRA. The BBK internal policies were transferred under '
        'non-disclosure following a BBK consultation. Each document carries '
        'a SHA-256 content hash for deduplication, a retrieval-date stamp, '
        'and a jurisdiction tag set at ingestion time. The directory layout '
        'is described in Appendix 3.4.',
    )
    add_image(doc, shots / '04_corpus_layout.png', width_cm=15.0)
    add_caption(doc, 'Figure 28.', 'Corpus folder layout per jurisdiction')

    # ─── 3.3.5 Model and index initialisation (Phase 4) ───────────────────
    add_heading(doc, '3.3.5 Model and index initialisation', level=2)
    add_paragraph(
        doc,
        'Three HuggingFace models are warmed on first use into a local '
        'cache: the BGE-small embedder, a cross-encoder reranker, and a '
        'natural language inference model used by the verifier. The '
        'persistent ChromaDB client is created with the cosine metric and '
        'one named collection. The SQLite FTS5 virtual table is created '
        'with unindexed metadata columns so jurisdiction and document-type '
        'filters apply at query time. Full setup commands are listed in '
        'Appendix 3.5.',
    )
    add_image(doc, shots / '05_chromadb_collection.png', width_cm=15.0)
    add_caption(doc, 'Figure 29.', 'HuggingFace cache and ChromaDB collection')

    # ─── 3.3.6 Local LLM setup (Phase 5) ─────────────────────────────────
    add_heading(doc, '3.3.6 Local LLM setup', level=2)
    add_paragraph(
        doc,
        'The local language model runs through Ollama on port 11434. The '
        'service is started with the daemon command and the default model '
        'is pulled with the Ollama command-line client. The reasoning '
        'package abstracts the provider behind an environment-variable '
        'switch, so a different language model can be substituted without '
        'editing the application code. The provider abstraction outline is '
        'in Appendix 3.6.',
    )
    add_image(doc, shots / '06_ollama_serve.png', width_cm=15.0)
    add_caption(doc, 'Figure 30.', 'Ollama daemon and model pull')

    # ─── 3.3.7 Ingestion pipeline (Phase 6, DEEP) ────────────────────────
    add_heading(doc, '3.3.7 Ingestion pipeline', level=2)
    add_paragraph(
        doc,
        'The ingestion pipeline transforms a raw document into safe, '
        'embedded, indexed chunks. It is built in five steps, each carrying '
        'an explicit safety responsibility. The novel element is the '
        'two-tier injection scanner that protects the corpus from '
        'adversarial content embedded in source documents.',
    )
    add_monospace_block(doc, INGESTION_SUBTREE)
    add_step(
        doc, 'Step 1.',
        'Document loading. Docling is used as the primary loader for PDF '
        'and DOCX files because it returns structured Markdown with '
        'preserved headings, which the chunker relies on. The loader '
        'records a SHA-256 content hash for deduplication and skips OCR by '
        'design, since the corpus is text-native and OCR would introduce '
        'an additional adversarial channel.',
    )
    add_step(
        doc, 'Step 2.',
        'Two-level chunking. A Markdown header splitter forms the first '
        'level by splitting on headings one through four. Any oversize '
        'section falls through to a recursive tiktoken splitter with a '
        'five-hundred token target and a sixty-token overlap. Each chunk '
        'carries a deterministic node identifier, a hierarchy path, and '
        'citation-ready metadata so downstream layers can produce verbatim '
        'quotes without re-reading the source file.',
    )
    add_step(
        doc, 'Step 3.',
        'Chunk classification. Every chunk is tagged as obligation, '
        'background, or unknown by a deterministic rule pass with an LLM '
        'fallback on ambiguity. The tag drives downstream filtering: '
        'comparison and mapping workflows preferentially retrieve '
        'obligation chunks, while open Q&A allows the full corpus.',
    )
    add_step(
        doc, 'Step 4.',
        'Two-tier injection scanning. Tier A is a deterministic regex '
        'catalogue with nine rule groups (instruction override, role '
        'hijack, forced verdict, safety bypass, developer-mode trigger, '
        'prompt leak, fake delimiter, base64 blob, suspicious URL). Tier B '
        'is an LLM judge that wraps the chunk in spotlight delimiters so '
        'the judging model cannot itself be jailbroken by the chunk text. '
        'The scanner fails closed: if both judges raise, the chunk is '
        'quarantined rather than indexed.',
    )
    add_step(
        doc, 'Step 5.',
        'Quarantine and audit. Flagged chunks become QuarantinedChunk '
        'rows in the database with severity, rule identifier, and matched '
        'snippet preserved. An administrator can approve a row, which '
        'releases the chunk to the Chroma and BM25 indexes, or reject it, '
        'which permanently holds it out of retrieval. Every transition is '
        'recorded in the audit log via the log_event helper described in '
        '§3.3.12.',
    )
    add_image(doc, code / 'M01_injection_scanner.png', width_cm=15.5)
    add_caption(doc, 'Figure 31.', 'Two-tier injection scanner outline')
    add_image(doc, shots / '07a_ingestion_progress.png', width_cm=15.5)
    add_caption(doc, 'Figure 32.', 'Live ingestion progress card')
    add_image(doc, shots / '07b_quarantine_queue.png', width_cm=15.5)
    add_caption(doc, 'Figure 33.', 'Quarantine queue review')

    # ─── 3.3.8 Hybrid retrieval (Phase 7, DEEPEST) ───────────────────────
    add_heading(doc, '3.3.8 Hybrid retrieval', level=2)
    add_paragraph(
        doc,
        'Retrieval combines lexical and semantic search and reranks the '
        'merged candidate pool. The objective is high recall on '
        'cross-jurisdictional terminology (different countries use '
        'different words for the same concept) and high precision at the '
        'top of the ranking (where the reasoning agent will actually look).',
    )
    add_monospace_block(doc, RETRIEVAL_SUBTREE)
    add_step(
        doc, 'Step 1.',
        'BM25 keyword index. The SQLite FTS5 virtual table holds one row '
        'per chunk with unindexed metadata columns for jurisdiction, '
        'document type, regulation name, and article reference. Filters '
        'apply through standard SQL WHERE clauses so the same query can '
        'be scoped to one jurisdiction without rebuilding an index.',
    )
    add_step(
        doc, 'Step 2.',
        'Vector retriever. ChromaDB hosts a persistent index built with '
        'the cosine metric over BGE-small embeddings. The same '
        'citation-aware prefix is applied at query time as at index time '
        'so the cosine space aligns. Jurisdiction and document-type '
        'filters apply through Chroma metadata-filter expressions.',
    )
    add_step(
        doc, 'Step 3.',
        'Term-dictionary expansion. About two hundred jurisdictional '
        'synonyms are looked up before retrieval (for example "consent" '
        'picks up Bahrain and India variants). The expansion improves '
        'recall on the BM25 side; the original un-expanded query is '
        'preserved for reranking, where synonym noise hurts precision.',
    )
    add_step(
        doc, 'Step 4.',
        'Reciprocal rank fusion. Both retrievers feed a '
        'QueryFusionRetriever in reciprocal-rerank mode. The library '
        'fixes the fusion constant at sixty, which is the de-facto '
        'standard from the original Cormack and Buettcher work. The fused '
        'candidate pool is twenty chunks deep.',
    )
    add_step(
        doc, 'Step 5.',
        'Cross-encoder rerank. A MiniLM ms-marco cross-encoder scores '
        '(query, chunk) pairs directly. The reranker is the dominant cost '
        'in retrieval but only runs once per query over twenty candidates, '
        'so latency stays within budget. The reranker returns the top five, '
        'which is the slice passed to the reasoning agent.',
    )
    add_image(doc, code / 'M02_rrf_hybrid_search.png', width_cm=15.5)
    add_caption(doc, 'Figure 34.', 'Hybrid search and RRF fusion outline')
    add_image(doc, code / 'M03_cross_encoder_rerank.png', width_cm=15.5)
    add_caption(doc, 'Figure 35.', 'Cross-encoder rerank outline')
    add_image(doc, shots / '08_hybrid_search_results.png', width_cm=15.5)
    add_caption(doc, 'Figure 36.', 'Hybrid search results page')

    # ─── 3.3.9 Reasoning agent (Phase 8, DEEPEST) ────────────────────────
    add_heading(doc, '3.3.9 Reasoning agent', level=2)
    add_paragraph(
        doc,
        'The reasoning agent is a LangGraph state machine wrapped by '
        'three workflow-specific graphs (comparison, mapping, gap '
        'analysis). Every workflow shares the same draft-verify-correct-'
        'finalize-fallback shape; only the prompts and the Pydantic '
        'response schemas differ. The verifier is the critical safety '
        'control: no finding is published without verbatim grounding and '
        'a hallucination score under the configured threshold.',
    )
    add_monospace_block(doc, REASONING_SUBTREE)
    add_step(
        doc, 'Step 1.',
        'Pydantic v2 schemas. Every workflow output is bound by a Pydantic '
        'model: ReasonedAnswer for open Q&A, ObligationComparison for '
        'comparison rows, PolicyCoverageItem for mapping, GapItem for gap '
        'analysis. Each row carries citation, evidence, confidence, and '
        'hallucination-risk fields that the verifier writes back into '
        'after scoring.',
    )
    add_step(
        doc, 'Step 2.',
        'LangGraph state machine. A StateGraph is built with four nodes '
        '(draft, verify, correct, finalize) plus a fallback escape. A '
        'conditional edge from verify routes either to correct on '
        'failure or to finalize on pass. Correct re-enters verify after a '
        'bounded retry. The compiled graph is invoked once per call; the '
        'checkpointer is omitted because the in-state retrieval objects '
        'do not serialise.',
    )
    add_step(
        doc, 'Step 3.',
        'Citation verifier and NLI score. The verifier confirms every '
        'cited chunk identifier maps to a retrieved chunk and that the '
        'quoted evidence appears verbatim inside that chunk after light '
        'normalisation. A cross-encoder natural language inference model '
        'then scores each analysis line against the chunk it cited. Lines '
        'with hallucination risk above the configured threshold are '
        'dropped, not silently retained.',
    )
    add_step(
        doc, 'Step 4.',
        'OutputFixingParser auto-correction. The draft step uses a '
        'Pydantic output parser. On a parse failure (truncated JSON, '
        'extra fields, type mismatch) the OutputFixingParser re-prompts '
        'the language model with the schema and the parse error so the '
        'model can self-correct. Retries are bounded at two attempts.',
    )
    add_step(
        doc, 'Step 5.',
        'SafeFallback typed empty. When the correct loop exhausts its '
        'retries the fallback node returns a typed ReasonedAnswer with '
        'confidence 0.3, no citations, and an explicit warning that the '
        'answer is not fully grounded. Downstream consumers display this '
        'as a "we could not answer" message rather than fabricated '
        'content.',
    )
    add_image(doc, code / 'M04_langgraph_wiring.png', width_cm=15.5)
    add_caption(doc, 'Figure 37.', 'LangGraph state machine wiring')
    add_image(doc, code / 'M05_verifier.png', width_cm=15.5)
    add_caption(doc, 'Figure 38.', 'Citation verifier and NLI score outline')
    add_image(doc, shots / '09a_comparison_run_chips.png', width_cm=15.5)
    add_caption(doc, 'Figure 39.', 'Comparison run with verifier chips')
    add_image(doc, shots / '09b_reasoning_trace_card.png', width_cm=15.5)
    add_caption(doc, 'Figure 40.', 'Reasoning trace card')
    add_image(doc, shots / '09c_safe_fallback_row.png', width_cm=15.5)
    add_caption(doc, 'Figure 41.', 'SafeFallback low-confidence row')

    # ─── 3.3.10 Workflow engines (Phase 9, light) ────────────────────────
    add_heading(doc, '3.3.10 Workflow engines', level=2)
    add_paragraph(
        doc,
        'Three workflows wrap the reasoning agent for the application '
        'domains the analysts actually work in: regulation comparison, '
        'policy mapping, and gap analysis. Long-running workflows are '
        'launched from Django views by spawning a management command in a '
        'subprocess, so the web layer never blocks on language-model '
        'latency. A signal-based cascade keeps the gap table in sync '
        'whenever a reviewer approves an ObligationMapping flagged as a '
        'gap. The subprocess pattern and the signal cascade are detailed '
        'in Appendix 3.7.',
    )
    add_image(doc, shots / '10_mapping_run_page.png', width_cm=15.5)
    add_caption(doc, 'Figure 42.', 'Mapping run page')

    # ─── 3.3.11 Copilot chat interface (light-medium) ────────────────────
    add_heading(doc, '3.3.11 Copilot chat interface', level=2)
    add_paragraph(
        doc,
        'The Copilot is a chat-style entry point that lets analysts ask '
        'free-form questions across the corpus and the analyses already '
        'in flight. It reuses the general-purpose reasoning graph from '
        '§3.3.9, so every Copilot answer passes through the same draft, '
        'verify, correct, and finalize guard-rails as the structured '
        'workflows. The chat endpoint supports two retrieval modes: '
        'an approved mode that prefers reviewed comparison and mapping '
        'rows and falls back to raw regulatory text, and a document '
        'mode that constrains the answer to one picked source. A small '
        'scope classifier returns a readiness state (not ready, '
        'partially ready, or ready) so the analyst always sees what '
        'the Copilot can currently answer from. Each session keeps a '
        'rolling history of the last twenty turns, and the chat '
        'fragment renders through HTMX swap targets so the conversation '
        'streams without a page reload.',
    )
    add_image(doc, code / 'M11_copilot_views.png', width_cm=15.5)
    add_caption(doc, 'Figure 43.', 'Copilot views and retrieval dispatcher')
    add_image(doc, shots / '11_copilot_chat.png', width_cm=15.5)
    add_caption(doc, 'Figure 44.', 'Copilot chat interface')

    # ─── 3.3.12 Web layer (medium, including the main pages) ─────────────
    add_heading(doc, '3.3.12 Web layer', level=2)
    add_paragraph(
        doc,
        'The web layer is ten Django apps that share one ASGI process. '
        'Django views render server-side HTML enhanced with HTMX for '
        'partial updates and Alpine.js for client-side state. Three '
        'roles share one set of templates: per-role visibility is '
        'enforced at the view layer through the role-required decorator '
        'and a per-row owner filter, never through template guards alone.',
    )
    add_paragraph(
        doc,
        'Five user-facing pages carry the bulk of analyst time. The '
        'dashboard surfaces the coverage chart, the gap-priority '
        'distribution, and a recent-activity feed pulled from the audit '
        'log. The document library presents regulations and BBK '
        'internal policies in two grids with jurisdiction and topic '
        'filters. The comparison page lets an analyst pick a regulation '
        'pair (Bahrain and India for example) and a topic scope, then '
        'spawns a comparison run whose progress streams back as HTMX '
        'fragments. The mapping page receives an internal policy, '
        'auto-detects or accepts a jurisdiction scope, and produces a '
        'mapped coverage report that flows into the review inbox. The '
        'review inbox lets a reviewer accept, reject, or modify each '
        'row, with the audit log capturing every transition. Long-running '
        'ingestion jobs stream progress through Django Channels, which '
        'carries one WebSocket per active job and joins a per-job '
        'channel group for fan-out.',
    )
    add_image(doc, code / 'M06_channels_consumer.png', width_cm=15.5)
    add_caption(doc, 'Figure 45.', 'Channels WebSocket consumer outline')
    add_image(doc, shots / '11a_dashboard.png', width_cm=15.5)
    add_caption(doc, 'Figure 46.', 'Dashboard with coverage chart')
    add_image(doc, shots / '11b_htmx_inline_edit.png', width_cm=15.5)
    add_caption(doc, 'Figure 47.', 'Review inbox with inline modify form')

    # ─── 3.3.13 Cybersecurity (Phase 11, DEEP) ───────────────────────────
    add_heading(doc, '3.3.13 Cybersecurity', level=2)
    add_paragraph(
        doc,
        'The security build extends the design described in §3.2.5 with '
        'the actual installation and wiring sequence. The middleware chain '
        'is the central artefact: order is load-bearing and each slot '
        'serves a specific defensive role.',
    )
    add_step(
        doc, 'Step 1.',
        'Install the security stack. Five packages cover the surface: '
        'django-axes for brute-force lockout, django-otp and '
        'django-two-factor-auth for TOTP enrolment, django-csp for '
        'Content Security Policy headers, and geoip2 for the optional '
        'GeoFence database. Pinned versions are listed in Appendix 3.2.',
    )
    add_step(
        doc, 'Step 2.',
        'Order the middleware chain. Sixteen layers compose the request '
        'pipeline. The GeoFence runs first so blocked countries never '
        'reach login. Sessions, CSRF, and authentication follow the '
        'Django stock order. The OTP middleware must follow authentication '
        'because it reads request.user. Idle session timeout runs before '
        'the MFA gate so an inactive user gets the login page cleanly. '
        'Force-password-change runs before force-MFA so new accounts '
        'rotate their temporary password before the TOTP setup wizard. '
        'django-axes runs last so it observes the auth view response and '
        'can lock the account.',
    )
    add_step(
        doc, 'Step 3.',
        'Configure password validators. Six validators apply on every '
        'credential change: the four Django built-ins '
        '(UserAttributeSimilarityValidator at the stricter 0.5 threshold, '
        'MinimumLengthValidator at twelve characters, '
        'CommonPasswordValidator, NumericPasswordValidator) plus two '
        'custom validators (ComplexityValidator requiring upper, lower, '
        'digit, and symbol; NoUsernameValidator rejecting passwords that '
        'embed the username or email).',
    )
    add_step(
        doc, 'Step 4.',
        'Wire the audit log and signal handlers. The AuditLog model is '
        'append-only at the application layer with twenty-eight action '
        'constants, an actor foreign key with SET_NULL, a role-at-time '
        'snapshot column, and composite indexes on user and event type. '
        'Four signal handlers turn every authentication event '
        '(user_logged_in, user_logged_out, user_login_failed, TOTPDevice '
        'first-time confirmation) into an AuditLog row through a single '
        'log_event helper that swallows write failures rather than '
        'derailing the view.',
    )
    add_step(
        doc, 'Step 5.',
        'Install GeoFence with MaxMind GeoLite2. The MaxMind country '
        'database is downloaded once into the data directory. The GeoFence '
        'middleware reads it on the first request after process start, '
        'caches the reader, and applies a country-code allowlist (Bahrain, '
        'India, Kuwait, United Arab Emirates by default). The middleware '
        'fails open on lookup error so a missing database does not lock '
        'BBK staff out.',
    )
    add_step(
        doc, 'Step 6.',
        'Add the Force-* middlewares and patch the admin. Force-password-'
        'change reads the must_change_password flag on every authenticated '
        'request and redirects to the change form when set. Force-MFA '
        'redirects users without a confirmed TOTP device to the setup '
        'wizard. The Django admin is patched with TWO_FACTOR_PATCH_ADMIN '
        'so the same MFA gate covers the admin interface.',
    )
    add_step(
        doc, 'Step 7.',
        'Add the Content Security Policy and security headers. The CSP '
        'restricts script and style sources to a small CDN allowlist '
        '(unpkg, jsdelivr, fontshare), pins connect-src to self, and sets '
        'frame-ancestors to none for clickjacking defence. Strict '
        'Transport Security is enabled with a one-year max-age, '
        'subdomain inclusion, and preload. X-Frame-Options, '
        'no-content-type-sniffing, and same-origin referrer policy '
        'complete the header stack.',
    )
    add_image(doc, code / 'M07_middleware_chain.png', width_cm=15.5)
    add_caption(doc, 'Figure 48.', 'Ordered middleware chain')
    add_image(doc, code / 'M08_password_validators.png', width_cm=15.5)
    add_caption(doc, 'Figure 49.', 'Password validators configuration')
    add_image(doc, code / 'M09_audit_signals.png', width_cm=15.5)
    add_caption(doc, 'Figure 50.', 'Audit signal handlers')
    add_image(doc, shots / '12a_two_factor_setup.png', width_cm=15.5)
    add_caption(doc, 'Figure 51.', 'Two-factor setup page')
    add_image(doc, shots / '12b_audit_log_inspector.png', width_cm=15.5)
    add_caption(doc, 'Figure 52.', 'Audit log inspector')
    add_image(doc, shots / '12c_user_management.png', width_cm=15.5)
    add_caption(doc, 'Figure 53.', 'User management page')

    # ─── 3.3.14 Export and audit hash chain (Phase 12, light) ────────────
    add_heading(doc, '3.3.14 Export and audit hash chain', level=2)
    add_paragraph(
        doc,
        'Reviewers export approved analyses as PDF (ReportLab) or XLSX '
        '(openpyxl). Each exported row carries a sixteen-character '
        'SHA-256 prefix computed over the row identity tuple (class name, '
        'primary key, lifecycle status, completion timestamp, submission '
        'timestamp, creator identifier). Recipients can re-compute the '
        'hash from the row and confirm the exported artefact still '
        'references the same identity. The export-builder outline is in '
        'Appendix 3.10.',
    )
    add_image(doc, code / 'M10_audit_hash.png', width_cm=15.5)
    add_caption(doc, 'Figure 54.', 'Audit hash helper')
    add_image(doc, shots / '13_pdf_export_hash.png', width_cm=15.5)
    add_caption(doc, 'Figure 55.', 'PDF export with chain prefix')

    # ─── 3.3.15 Deployment to BBK workstation (Phase 13, light) ──────────
    add_heading(doc, '3.3.15 Deployment to BBK workstation', level=2)
    add_paragraph(
        doc,
        'The BBK deployment runs on a single Windows workstation behind a '
        'reverse proxy that terminates TLS on port 443. The Django '
        'settings switch DEBUG to False, rotate the SECRET_KEY, enable '
        'HSTS preload, and turn on the SSL redirect. The MaxMind '
        'GeoLite2 country database is installed into the data directory '
        'so the optional GeoFence becomes enforceable when the operator '
        'chooses. Four directories are listed for the operator to back '
        'up: the SQLite database, the Chroma vector index, the media '
        'directory, and the per-job log directory. The deployment check '
        'is verified with the standard Django check command.',
    )
    add_image(doc, shots / '14_check_deploy_clean.png', width_cm=15.5)
    add_caption(doc, 'Figure 56.', 'Deployment check clean output')

    doc.save(out_path)
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
