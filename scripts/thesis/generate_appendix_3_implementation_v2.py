"""Generate Appendix 3 Implementation v2 - comprehensive, no word limit.

Output: thesis_docs/appendix_3_implementation_v2.docx

Narrative format inspired by Hussain Basem Hasan (2024). Each section
uses a Roman numeral heading. Each subsection has:
  - Numbered title (1), 2), ...)
  - Dense narrative paragraph (2-4 sentences) naming libraries and
    integration points, with the cyber-aware framing from §3.3
  - Figure referenced inline (code outline screenshot from
    thesis_docs/code_3_3_outlines/, captured to diagrams/code_3_3/)

16 sections, ~80 subsections. No app screenshots: those live in the
user manual. Public-pattern code (MIDDLEWARE list, CSP dict, .env
schema, Caddy config) is shown real where possible. Domain IP is kept
as NDA-safe outlines.

Style: no em-dashes, no semicolons, numerals for tech specs,
cyber-aware framing.
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


NAVY = RGBColor(0x00, 0x25, 0x83)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK_GRAY = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x6B, 0x72, 0x80)

# Figure counter so we never have to renumber by hand.
_fig_counter = {'i': 0}


def next_fig():
    _fig_counter['i'] += 1
    return _fig_counter['i']


def set_run_style(run, *, bold=False, italic=False, color=NAVY, size=11):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)


def add_paragraph(doc, text, *, color=DARK_GRAY, size=11):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    set_run_style(run, color=color, size=size)
    return p


def add_section_heading(doc, text):
    h = doc.add_paragraph(style='Heading 2')
    run = h.add_run(text)
    run.font.color.rgb = NAVY
    run.font.bold = True
    run.font.size = Pt(13)
    return h


def add_subsection_title(doc, text):
    """Numbered subsection title like '1) Document Loader'."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    set_run_style(run, bold=True, color=NAVY, size=11)
    return p


def add_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(10)
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


def add_monospace(doc, text: str, *, size: int = 9):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.left_indent = Cm(0.6)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
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


def subsection(doc, code_dir: Path, title: str, narrative: str,
               outline_png: str = None, caption_label: str = None):
    """Render a numbered subsection: title, narrative paragraph, figure."""
    add_subsection_title(doc, title)
    add_paragraph(doc, narrative)
    if outline_png:
        add_image(doc, code_dir / outline_png, width_cm=15.5)
        n = next_fig()
        label = f'Figure A.3.{n}.'
        add_caption(doc, label, caption_label or title.split(') ', 1)[-1])


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'appendix_3_implementation_v2.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(3, 100):
                candidate = out_dir / f'appendix_3_implementation_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    code = base / 'diagrams' / 'code_3_3'

    doc = Document()
    for s in doc.sections:
        s.top_margin = Cm(2.0)
        s.bottom_margin = Cm(2.0)
        s.left_margin = Cm(2.0)
        s.right_margin = Cm(2.0)

    # ─────────────────────────── Title ────────────────────────────────────
    h = doc.add_paragraph(style='Heading 1')
    run = h.add_run('Appendix 3 - Implementation Supplements')
    run.font.color.rgb = NAVY
    run.font.bold = True
    run.font.size = Pt(16)

    add_paragraph(
        doc,
        'This appendix supports §3.3 with the operational and code-level '
        'detail every implementation phase carries. Each section names '
        'the libraries, files, schemas, and integration points a '
        'professional would need to rebuild the system. Code outlines '
        'are NDA-safe stubs of the real source: function signatures and '
        'step-by-step logic comments are preserved, while proprietary '
        'implementation strings are excluded by agreement. Where the '
        'code is a public pattern (Django settings, CSP dict, reverse '
        'proxy config, env-var schema), the real listing is shown. '
        'Style follows §3.3: plain English, cyber-aware framing, '
        'no em-dashes, no semicolons, numerals for technical quantities.',
    )

    # ════════════════════════════════════════════════════════════════════
    # I. Project bootstrap and host environment
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'I. Project Bootstrap and Host Environment')

    subsection(
        doc, code,
        '1) Windows Host Preparation',
        'The development host runs Windows 11 Pro on an x86_64 workstation '
        'with at least 16 GB RAM and 100 GB free disk. Required tools are '
        'Python 3.10 or newer, Git for Windows, and Visual Studio Code '
        'with the Python, Pylance, and SQLite Viewer extensions. The host '
        'install is bank-managed under BBK endpoint protection, so '
        'anti-malware coverage of the media and data directories is '
        'inherited from the workstation policy.',
    )
    add_monospace(doc, (
        '> winget install Python.Python.3.12\n'
        '> winget install Git.Git\n'
        '> winget install Microsoft.VisualStudioCode\n'
        '> code --install-extension ms-python.python\n'
        '> code --install-extension ms-python.vscode-pylance\n'
        '> code --install-extension alexcvzz.vscode-sqlite\n'
    ))
    add_caption(doc, f'Figure A.3.{next_fig()}.', 'Host setup commands')

    subsection(
        doc, code,
        '2) Virtual Environment and Pinned Dependencies',
        'A Python virtual environment is created inside the project root '
        'so package versions do not collide with the system Python. The '
        'pinned requirements.txt holds the core RAG stack (chromadb, '
        'llama-index-core, sentence-transformers, rank-bm25, '
        'langchain-text-splitters, tiktoken), document loaders (docling, '
        'pymupdf, python-docx), data and reporting libraries (pandas, '
        'openpyxl, reportlab), and HTTP client (requests). PyTorch is '
        'installed separately from its own distribution channel because '
        'the correct build depends on the host CPU and any CUDA '
        'capability, so the build is hardware-specific. Pinning every '
        'package closes the supply-chain drift risk where a transitive '
        'dependency changes behaviour between machines.',
        outline_png='AP01_requirements.png',
        caption_label='requirements.txt highlights',
    )
    add_monospace(doc, (
        '> py -m venv .venv\n'
        '> .venv\\Scripts\\activate\n'
        '> python -m pip install -r requirements.txt\n'
        '> python -m pip install torch '
        '--index-url https://download.pytorch.org/whl/cpu\n'
        '> copy .env.example .env\n'
    ))
    add_caption(doc, f'Figure A.3.{next_fig()}.',
                'Virtual environment and pinned-dependency install')

    subsection(
        doc, code,
        '3) Django Scaffold and Database Initialisation',
        'Django 5.x is configured with SQLite for the development and '
        'pilot deployment, with write-ahead logging enabled for crash '
        'safety. The migration sequence applies the contributed schemas '
        '(auth, sessions, admin), the django-otp and '
        'django-two-factor-auth schemas, and the 10 project apps. A '
        'post-save signal in apps.accounts.signals creates a UserProfile '
        'row with role analyst on every user creation, so role lookups '
        'downstream never miss. The superuser is created interactively, '
        'and the temporary password is rotated on first login by the '
        'ForcePasswordChangeMiddleware described in §3.3.13.',
    )
    add_monospace(doc, (
        '> cd cjpca\n'
        '> python manage.py makemigrations\n'
        '> python manage.py migrate\n'
        '> python manage.py createsuperuser\n'
    ))
    add_caption(doc, f'Figure A.3.{next_fig()}.', 'Database migration sequence')

    # ════════════════════════════════════════════════════════════════════
    # II. Data acquisition and corpus assembly
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'II. Data Acquisition and Corpus Assembly')

    subsection(
        doc, code,
        '1) Corpus Sources and Provenance',
        'The corpus combines public regulations and BBK internal policies '
        'across the three target jurisdictions. The Bahrain Personal Data '
        'Protection Law and its implementing orders are obtained from the '
        'Legal Affairs Bureau portal. The India Digital Personal Data '
        'Protection Act 2023 is obtained from the Ministry of Electronics '
        'and Information Technology gazette. The Kuwait Data Privacy '
        'Protection Regulation is obtained from CITRA. BBK internal '
        'policies are transferred under non-disclosure following a BBK '
        'consultation. Each document is fingerprinted with a SHA-256 '
        'content hash for deduplication, stamped with its retrieval '
        'date, and tagged by jurisdiction at the directory level so '
        'public-regulation chunks and BBK-internal chunks stay '
        'separable downstream.',
    )

    subsection(
        doc, code,
        '2) Storage Layout and Document Metadata Schema',
        'Public regulations live under data/regulations/<jurisdiction>/ '
        'and BBK internal policies under data/internal_policies/. Each '
        'Document row in the Django library carries title, jurisdiction, '
        'doc_type (regulation or policy), regulation_name, content_hash, '
        'file path, chunk_count, classified_topics, uploaded_by, and '
        'uploaded_at. A metadata.csv at the data root supplies extra '
        'fields (effective_date, issuing_authority, source_url, '
        'concept_tags, applicable_sector) that the full_ingest command '
        'hydrates into Document rows after Stage 3.',
    )
    add_monospace(doc, (
        'data/\n'
        '├── regulations/\n'
        '│   ├── bahrain/\n'
        '│   ├── india/\n'
        '│   └── kuwait/\n'
        '├── internal_policies/\n'
        '├── processed/             Markdown after Docling conversion\n'
        '└── metadata.csv           Hydration source for Document rows\n'
    ))
    add_caption(doc, f'Figure A.3.{next_fig()}.', 'Corpus directory layout')

    # ════════════════════════════════════════════════════════════════════
    # III. Model and index initialisation
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'III. Model and Index Initialisation')

    subsection(
        doc, code,
        '1) HuggingFace Model Cache',
        '3 HuggingFace models warm into a local cache on first use. '
        'BAAI/bge-small-en-v1.5 (384-dim) embeds chunks at ingestion and '
        'queries at retrieval. cross-encoder/ms-marco-MiniLM-L-6-v2 '
        'reranks the merged candidate pool. A cross-encoder NLI model '
        'scores hallucination risk in the verifier. HF_HOME is pointed '
        'at <project_root>/hf_cache so models are cached on disk and '
        'never re-downloaded. The cache directory consumes about 4 GB '
        'after all 3 models warm.',
    )

    subsection(
        doc, code,
        '2) ChromaDB Persistent Client',
        'ChromaDB 0.4.x runs as a persistent client pointed at '
        '<project_root>/chroma_data/. The collection is created with '
        'metadata={"hnsw:space": "cosine"} so similarity is measured by '
        'cosine distance. The same BGE-small embedder is used at index '
        'and query time so the cosine space aligns. Jurisdiction and '
        'document-type metadata are stored alongside every vector so '
        'queries can filter through Chroma metadata-filter expressions '
        'without touching the index structure.',
        outline_png='AP02_chromadb_init.png',
        caption_label='ChromaDB persistent client initialisation',
    )

    subsection(
        doc, code,
        '3) SQLite FTS5 Keyword Index',
        'The keyword index is built on SQLite FTS5 (full-text search '
        'virtual table) with the unicode61 tokenizer. The DDL creates '
        'one bm25_index virtual table with indexed content plus '
        'unindexed metadata columns (node_id, jurisdiction, doc_type, '
        'doc_title, regulation_name, article_ref), so SQL WHERE clauses '
        'scope a query to one jurisdiction without rebuilding the '
        'index. A second parents table stores oversize parent chunks '
        'for context expansion, and a chunk_tags table holds the '
        'classifier output for analytics.',
        outline_png='AP03_fts5_ddl.png',
        caption_label='SQLite FTS5 virtual table DDL',
    )

    # ════════════════════════════════════════════════════════════════════
    # IV. Local language-model setup
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'IV. Local Language-Model Setup')

    subsection(
        doc, code,
        '1) Ollama Daemon Installation',
        'Ollama is the local LLM runtime. The Windows installer registers '
        'a background service that auto-starts on login and listens on '
        'localhost:11434. The default reasoning model is llama3.2:1b '
        '(1.3 GB on disk). The daemon does not need to be started '
        'manually on Windows because the installer handles it, but the '
        'manual command is provided for systems where it is disabled.',
    )
    add_monospace(doc, (
        '> winget install Ollama.Ollama\n'
        '> ollama pull llama3.2:1b\n'
        '> ollama list\n'
    ))
    add_caption(doc, f'Figure A.3.{next_fig()}.', 'Ollama install and model pull')

    subsection(
        doc, code,
        '2) Provider Abstraction',
        'The reasoning package wraps the LLM behind an env-var-driven '
        'provider abstraction in reasoning.generator. A primary provider '
        '(OpenRouter or any chat completions endpoint) is built first, '
        'then the local Ollama is wrapped as a fallback through '
        "LangChain's with_fallbacks. Any exception from the primary "
        '(network failure, rate limit, auth error, parser error) hands '
        'the call over to Ollama transparently. The fallback can be '
        'disabled via cfg.llm.fallback_enabled, which closes the data '
        'exfiltration surface when an analyst requires fully on-host '
        'inference.',
        outline_png='AP04_provider_abstraction.png',
        caption_label='LLM provider abstraction with fallback',
    )

    # ════════════════════════════════════════════════════════════════════
    # V. Ingestion pipeline components
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'V. Ingestion Pipeline Components')

    subsection(
        doc, code,
        '1) Document Loader',
        'ingestion.loaders.load_document(path) is the entry point for '
        'document parsing. Docling 2.x is the primary loader for PDF and '
        'DOCX, BeautifulSoup handles HTML, and Markdown files pass '
        'through unchanged. The loader returns a LoadedDocument carrying '
        'text (Markdown with the heading structure preserved), '
        'content_hash (SHA-256 over the raw file bytes via '
        'hashlib.sha256), page_count, and any extraction warnings. OCR '
        'is deliberately disabled because the corpus is text-native and '
        'OCR would open an adversarial channel where a malicious image '
        'embedded in a PDF could smuggle hidden instructions into the '
        'LLM downstream.',
        outline_png='M01a_loaders.png',
        caption_label='Document loader function signature and logic',
    )

    subsection(
        doc, code,
        '2) Two-Level Chunker',
        'ingestion.chunker.chunk_document splits a Markdown document in '
        '2 passes. The first level uses MarkdownHeaderTextSplitter from '
        'langchain-text-splitters 0.3.x on h1 through h4 headings. Any '
        'section that exceeds the chunk budget falls through to a '
        'RecursiveCharacterTextSplitter encoded by tiktoken cl100k_base '
        'with a 500-token target and 60-token overlap. Each chunk is a '
        'dict with node_id (deterministic identifier), text, '
        'section_title, hierarchy_path, obligation_tag, jurisdiction, '
        'doc_title, regulation_name, and page_hint. The deterministic '
        'node_id is what the citation verifier later uses to prove that '
        'every quoted line came from a real source chunk.',
        outline_png='M01b_chunker.png',
        caption_label='Two-level chunker function signature and logic',
    )

    subsection(
        doc, code,
        '3) Chunk Classifier',
        'Chunk classification happens in 2 passes. A deterministic rule '
        'pass inside the chunker labels every chunk as obligation, '
        'background, or unknown based on deontic verbs and modal '
        'auxiliaries (shall, must, is required to). A later batch '
        'process invokes reasoning.classifier.classify_chunk, which '
        'wraps an LLM call with a PydanticOutputParser and an '
        'OutputFixingParser. The LLM output is validated against the '
        '12-topic taxonomy at output normalisation, so invented topics '
        'or low-confidence guesses (below 0.3) are rejected and the row '
        'falls back to UNCLASSIFIED. This keeps the index from being '
        'polluted by tags the model invented.',
        outline_png='M01c_classifier.png',
        caption_label='Chunk classifier function signature and logic',
    )

    subsection(
        doc, code,
        '4) Embedder',
        'ingestion.embedder.embed_chunks wraps the BGE-small '
        'SentenceTransformer with a citation-aware prefix. Each chunk is '
        'prefixed with Jurisdiction and Citation lines before encoding, '
        'so the embedded vector carries provenance signal alongside the '
        'content. The same SentenceTransformer instance is used '
        'throughout the process (singleton via embedder.get_model), so '
        'the model loads once and stays warm for the rest of the '
        'ingestion run. Output vectors are returned as plain Python '
        'lists so they pass through ChromaDB without type coercion.',
    )

    subsection(
        doc, code,
        '5) Two-Tier Injection Scanner',
        'ingestion.injection_scanner is the most novel safety component '
        'in the pipeline. It applies 2 independent layers to every chunk '
        'before that chunk reaches ChromaDB or the BM25 store. Tier A is '
        'a deterministic regex catalogue with 9 rule groups (instruction '
        'override, role hijack, forced verdict, safety bypass, '
        'developer-mode trigger, prompt leak, fake delimiter, base64 '
        'blob, suspicious URL). Each rule produces a Detection on match '
        'with the rule identifier and a 200-character matched snippet '
        'preserved for forensic audit. Tier B is an LLM judge that wraps '
        'the chunk text in spotlight delimiters before sending it to the '
        'model, so the judging model cannot itself be jailbroken by the '
        'chunk content under review. Claude Haiku 4.5 via OpenRouter is '
        'the primary judge and a local Ollama judge is the fallback. If '
        'both providers raise, the chunk is quarantined as '
        'JUDGE_UNAVAILABLE for human review rather than indexed '
        'silently. This fail-closed behaviour closes the silent-failure '
        'attack surface that a naive scanner would leave open.',
        outline_png='M01d_injection_scanner.png',
        caption_label='Two-tier injection scanner function signatures',
    )

    subsection(
        doc, code,
        '6) ChromaDB Indexer',
        'ingestion.indexer.index_chunks persists embedded chunks into '
        'ChromaDB in batches. Metadata is sanitised via sanitize_metadata '
        'because Chroma rejects nested dictionaries and non-primitive '
        'types, so every metadata value is coerced to str, int, bool, or '
        'float. The indexer uses get_or_create_collection so re-ingestion '
        'is idempotent on collection identity. A custom _NoOpEmbeddings '
        'class prevents LangChain from re-embedding vectors that already '
        'carry their own embedding, which would otherwise double the '
        'compute cost on re-runs.',
    )

    subsection(
        doc, code,
        '7) Quarantine Pipeline',
        'cjpca.apps.ingestion.pipeline orchestrates the per-job pipeline '
        'inside the Django app. _scan_chunks_for_injection takes the raw '
        'chunk list, calls scan_chunks from the ingestion library, and '
        'turns every Detection into a QuarantinedChunk row with '
        'severity, rule_id, matched snippet, all_detections JSON, and '
        'the chunk metadata. An AuditLog entry is written for every '
        'flagged chunk with action quarantine.flagged. An admin can '
        'approve a quarantined row through the QuarantineDecideView, '
        'which releases the chunk to the Chroma and BM25 indexes, or '
        'reject it, which permanently holds it out of retrieval. Every '
        'transition is audited so the forensic trail is independent of '
        'the queue table itself.',
        outline_png='M01e_pipeline.png',
        caption_label='Quarantine pipeline function signatures',
    )

    # ════════════════════════════════════════════════════════════════════
    # VI. Hybrid retrieval components
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'VI. Hybrid Retrieval Components')

    subsection(
        doc, code,
        '1) BM25 Keyword Index',
        'retrieval.bm25_store wraps the SQLite FTS5 keyword index. '
        'upsert_chunks writes each chunk to the bm25_index virtual '
        'table, search_bm25 runs a MATCH query with optional WHERE '
        'filters for jurisdiction and doc_type, and the result is '
        'ordered by the FTS5 bm25() function. The unindexed metadata '
        'columns make jurisdiction filtering a one-clause SQL operation '
        'rather than an index rebuild, which keeps internal BBK policies '
        'separable from public regulations at zero query cost.',
        outline_png='M02a_bm25_store.png',
        caption_label='BM25 keyword store function signatures',
    )

    subsection(
        doc, code,
        '2) Vector Retriever',
        'retrieval.retriever.RetrievalService wraps the ChromaDB client '
        'as a stateful singleton so heavy resources (Chroma collection, '
        'BGE-small embedder, cross-encoder reranker) load once per '
        'process. _get_index lazy-opens the Chroma collection through '
        'chromadb.PersistentClient(path=chroma_data/) with the cosine '
        'metric. The same SentenceTransformer model is used at index '
        'and query time so the cosine space aligns. Jurisdiction and '
        'document-type metadata filters apply through Chroma '
        'metadata-filter expressions, mirroring the BM25 scoping '
        'behaviour at the vector layer.',
        outline_png='M02b_vector_retriever.png',
        caption_label='Vector retriever class outline',
    )

    subsection(
        doc, code,
        '3) Term-Dictionary Expansion',
        'reasoning.term_dictionary holds about 200 jurisdictional '
        'synonyms with cross-regulator variants. synonyms_for_query '
        'tokenises the user query into legal terms and looks each token '
        'up in the static dictionary, returning a deduplicated list of '
        'variants. The retriever appends these to the query before BM25 '
        'search so a "consent" question also catches the Bahrain and '
        'India statutory phrasings. The original un-expanded query is '
        'preserved for reranking, because synonym noise at rerank time '
        'would elevate near-misses and hurt the precision of the chunks '
        'the reasoning agent actually reads.',
        outline_png='M02c_term_dictionary.png',
        caption_label='Term-dictionary expansion outline',
    )

    subsection(
        doc, code,
        '4) Parent Chunk Docstore',
        'For oversize sections that the chunker had to split, the full '
        'parent text is preserved separately in the parents table inside '
        'the BM25 SQLite database. upsert_parents inserts or replaces by '
        'node_id, and get_parent retrieves a parent on demand. The '
        'reasoning agent can request the parent of a hit chunk when the '
        'context window allows, which expands the surrounding clause or '
        'article around a single matched paragraph without re-reading '
        'the source file.',
    )

    subsection(
        doc, code,
        '5) Reciprocal Rank Fusion',
        'hybrid_search wraps the BM25 retriever and the Chroma vector '
        'retriever inside a QueryFusionRetriever from llama-index-core '
        '0.10.x. The fusion mode is reciprocal_rerank and the library '
        'fixes the constant at 60 (the standard from Cormack and '
        'Buettcher). The fused candidate pool is 20 chunks deep. RRF is '
        'order-stable across re-runs and does not require score '
        'calibration between the two retrievers, which makes it the '
        'natural choice when one retriever is lexical and the other is '
        'semantic.',
        outline_png='M02_rrf_hybrid_search.png',
        caption_label='Hybrid search and RRF fusion outline',
    )

    subsection(
        doc, code,
        '6) Cross-Encoder Reranker',
        'After RRF returns 20 candidates, _rerank_candidates feeds each '
        '(query, chunk) pair through cross-encoder/ms-marco-MiniLM-L-6-v2 '
        'to produce a direct relevance score. Cross-encoders see the '
        'query and the candidate together at the model layer, so they '
        'catch matches that lexical and bi-encoder approaches miss. The '
        'reranker is the dominant cost in retrieval but it runs only '
        'once per query over 20 candidates and returns the top 5, which '
        'keeps end-to-end retrieval latency inside the NFR-01 budget of '
        '1.5 seconds on a CPU-only host.',
        outline_png='M03_cross_encoder_rerank.png',
        caption_label='Cross-encoder reranker outline',
    )

    # ════════════════════════════════════════════════════════════════════
    # VII. Reasoning agent components
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'VII. Reasoning Agent Components')

    subsection(
        doc, code,
        '1) Pydantic v2 Schemas',
        'Every workflow output is shaped by a Pydantic 2.x model from '
        'reasoning.schemas. ReasonedAnswer covers open Q&A, '
        'ObligationComparison covers comparison rows, PolicyCoverageItem '
        'covers mapping, and GapItem covers gap analysis. Every row '
        'carries citation, evidence, confidence_score (0 to 100), and '
        'hallucination_risk (0.0 to 1.0). The verifier writes scores '
        'back into these fields after each row is checked, so the '
        'safety verdict travels with the data and downstream consumers '
        'cannot see a result without also seeing its safety score. This '
        'closes the surface where a UI bug could hide the risk score '
        'while still displaying the body.',
        outline_png='M_3_3_9_schemas.png',
        caption_label='Pydantic schemas for every workflow output',
    )

    subsection(
        doc, code,
        '2) Query Router',
        'reasoning.router classifies an incoming query into one of 4 '
        'reasoning routes: open, compare, map, or gap. The first pass '
        'is a deterministic keyword heuristic for unambiguous cases. '
        'Ambiguous queries fall through to an LLM-backed QueryRouter '
        'that calls _call_llm with a tight routing prompt and parses '
        'the verdict. Caching is enabled so repeated queries do not pay '
        'the LLM cost twice.',
    )

    subsection(
        doc, code,
        '3) LangGraph State Machine',
        'reasoning.orchestrator builds the general-purpose LangGraph '
        'state machine. langgraph 0.2.x StateGraph has 6 nodes (route, '
        'draft, verify, correct, finalize, fallback). The entry point '
        'is route. Deterministic edges connect route to draft, and '
        'correct back to verify. A conditional edge from verify routes '
        'either to correct on failure or to finalize on pass. A second '
        'conditional edge from draft routes to verify or END on parse '
        'failure. The checkpointer is omitted on purpose because the '
        'in-state retrieval objects (NodeWithScore) are not '
        'msgpack-serializable and each call is one-shot anyway.',
        outline_png='M04_langgraph_wiring.png',
        caption_label='LangGraph state machine wiring',
    )

    subsection(
        doc, code,
        '4) Citation Verifier and NLI Score',
        'reasoning.validators is the verifier. verify_grounding loops '
        'through every citation in the draft, looks the chunk_id up in '
        'the retrieved chunks, and confirms the verbatim quote appears '
        'inside the chunk after light normalisation (whitespace, smart '
        'quotes, case). The quote must be at least 10 characters long '
        'to count. score_hallucination then loads a cross-encoder NLI '
        'model and predicts (contradiction, neutral, entailment) logits '
        'for the (chunk, analysis) pair. Softmax converts logits to '
        'probabilities and the hallucination risk is 1.0 minus the '
        'entailment probability, rounded to 3 decimal places. Lines '
        'above the configured threshold are dropped, not silently '
        'kept, so fabricated content never reaches the user.',
        outline_png='M05_verifier.png',
        caption_label='Citation verifier and NLI score outline',
    )

    subsection(
        doc, code,
        '5) OutputFixingParser Auto-Correction',
        'reasoning.generator wraps every LLM call in a '
        'PydanticOutputParser. If parsing fails on the first attempt '
        '(truncated JSON, extra fields, type mismatch), '
        'OutputFixingParser from langchain.output_parsers re-prompts '
        'the language model with the schema and the parse error so the '
        'model can self-correct. Retries are bounded at '
        'cfg.llm.retry_attempts (default 2), after which control passes '
        'to the fallback so the system cannot loop forever on a '
        'broken response.',
        outline_png='M_3_3_9_output_fixing_parser.png',
        caption_label='OutputFixingParser auto-correction outline',
    )

    subsection(
        doc, code,
        '6) LLM Provider Abstraction',
        '_build_llm in reasoning.generator is the central factory. It '
        'builds the primary LLM (OpenRouter Claude Haiku 4.5 by default) '
        'and, when cfg.llm.fallback_enabled is True, wraps it with the '
        'local Ollama fallback through with_fallbacks. Any exception '
        'from the primary (network failure, rate limit, auth error, '
        'parser error after retries) transparently shifts the call to '
        'the local model. _get_llm caches the wrapped runnable across '
        'calls so the build cost is paid once per process.',
    )

    subsection(
        doc, code,
        '7) SafeFallback Typed Empty',
        'reasoning.fallback.safe_fallback_response returns a typed '
        'ReasonedAnswer with confidence 0.3, an empty citations list, '
        'and an explicit warnings entry that the answer is not fully '
        'grounded. A short refusal body explains that a grounded answer '
        'was not possible with the available context. A keyword-based '
        'suggestion list points the user at authoritative external '
        'sources (PDPL, DPDPA, DPPR, regulator guidance). Suggestions '
        'are static strings, not LLM calls, so no further hallucination '
        'risk is introduced by the fallback itself.',
        outline_png='M_3_3_9_safe_fallback.png',
        caption_label='SafeFallback typed-empty response outline',
    )

    # ════════════════════════════════════════════════════════════════════
    # VIII. Workflow engines
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'VIII. Workflow Engines')

    subsection(
        doc, code,
        '1) Comparison, Mapping, and Gap Workflows',
        'reasoning.workflows exposes 3 workflow-specific LangGraphs '
        'wrapped around the general reasoning agent. compare_regulations '
        'takes two jurisdictions and produces a ComparisonReport. '
        'map_policy_coverage takes a policy and a jurisdiction scope '
        'and produces a PolicyMappingReport. generate_gap_analysis '
        'takes a finished mapping result and produces a '
        'GapAnalysisReport with severity-bucketed remediation '
        'suggestions. Each workflow has its own per-call state shape '
        '(ComparisonState, MappingState, GapState) but shares the same '
        'draft, verify, correct, finalize, fallback node pattern with '
        'only the prompts and the Pydantic response schemas changing.',
    )

    subsection(
        doc, code,
        '2) Subprocess Dispatch',
        'Long-running workflows are launched from Django views by '
        'spawning a Django management command in a subprocess, so the '
        'web layer never blocks on language-model latency. The '
        'run_comparison_job and run_mapping_job commands re-assert the '
        'job status to RUNNING in case AppConfig.ready had reset it on '
        'startup, then call the per-workflow background function. A '
        'crashed LLM call cannot take down the request thread because '
        'it lives in a separate OS process, and a hung job can be '
        'killed at the OS level without restarting the web server.',
        outline_png='AP05_subprocess_dispatch.png',
        caption_label='Comparison job subprocess dispatch outline',
    )

    subsection(
        doc, code,
        '3) Signal-Based Gap Synchronisation',
        'apps.mapping.models.Gap.sync_gap_on_approval is a class method '
        'invoked by a post_save signal on ObligationMapping. When a '
        'reviewer approves a mapping row whose coverage is partial or '
        'none, the cascade creates or updates the corresponding Gap '
        'row in one operation using update_or_create on (analysis, '
        'obligation), so the cascade is idempotent across re-saves. '
        'Every gap-sync writes a review.gap_synced AuditLog row so the '
        'lifecycle is fully traceable from approval to remediation '
        'queue.',
        outline_png='AP06_sync_gap_signal.png',
        caption_label='Gap synchronisation post-save signal outline',
    )

    subsection(
        doc, code,
        '4) Comparison Domain Helpers',
        'apps.comparison ships several scoring helpers that the '
        'workflow consumes. strictness.py scores each row along '
        'procedural, substantive, and enforcement strictness dimensions '
        'using regex heuristics over the verbatim regulation text. '
        'concepts.py clusters rows by legal concept so the UI can show '
        'that multiple jurisdictions converge on the same idea even '
        'when their wording diverges. topic_scan.py canonicalises the '
        'set of topics a finished comparison touches against the '
        'taxonomy. insights.py exposes divergence_ranking and '
        'coverage_summary for the comparison index page.',
    )

    subsection(
        doc, code,
        '5) Mapping Severity Bucketing',
        'apps.mapping.risk.severity_to_due_date translates a gap severity '
        'into a remediation due date. High severity maps to today plus '
        '30 days, medium to today plus 90 days, low to today plus 180 '
        'days, and an unknown severity returns None. The bucketing '
        'reflects BBK compliance guidance and is used by the review '
        'inbox when the cascaded Gap row is created.',
    )

    # ════════════════════════════════════════════════════════════════════
    # IX. Copilot chat interface
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'IX. Copilot Chat Interface')

    subsection(
        doc, code,
        '1) CopilotMessageView',
        'apps.core.views.CopilotMessageView is the POST endpoint at '
        '/copilot/message/. The view pulls session state '
        '(copilot_include_drafts, copilot_history with a rolling 20-turn '
        'window, doc_title, mode), routes the request through the '
        'trust-tier dispatcher in approved mode or _retrieve_regulatory '
        'in document mode, re-fetches the underlying chunks via '
        'hybrid_search so the verify node has the node_id and content '
        'pairs it expects, and invokes the compiled reasoning_graph '
        'from §3.3.9. The HTMX swap fragment is rendered with the '
        'answer, confidence, citations, hallucination_risk, and the '
        'data_quality chips that explain the source mix to the analyst.',
        outline_png='M11_copilot_views.png',
        caption_label='CopilotMessageView and retrieval dispatcher',
    )

    subsection(
        doc, code,
        '2) Trust-Tier Retrieval Dispatcher',
        '_approved_retrieve is the trust-tier mixer. It queries '
        'ReviewItem rows with status APPROVED that match the message. '
        'If hits exist and include_drafts is False, those reviewed rows '
        'are the primary context. If include_drafts is True, the '
        'function unions in submitted-for-review rows. When approved '
        'hits are sparse, the dispatcher augments with regulatory '
        'chunks from hybrid_search and labels the layer mixed. When '
        'there are no approved hits at all, the layer falls back to '
        'pure regulatory text with a fallback message explaining the '
        'demotion. The labelling lets the UI tell the analyst which '
        'trust layer the answer came from.',
    )

    subsection(
        doc, code,
        '3) Scope State Classifier',
        'apps.core.scope holds the readiness classifier. classify_state '
        'reads the four category states (regulations, internal_policies, '
        'approved_comparisons, approved_mappings) and returns one of '
        'not_ready, partially_ready, or ready. When no regulations or '
        'policies are usable the system is not ready. When all four are '
        'usable the system is ready. Otherwise the partial-template '
        'engine builds a sentence that names the ready and missing '
        'source categories. A context processor injects the readiness '
        'state and the doc-picker options into every template render.',
    )

    subsection(
        doc, code,
        '4) Conversation History',
        'Each Copilot session keeps copilot_history in the Django '
        'session, capped at the last 20 turns. New turns are appended '
        'as (user_message, ai_response) tuples and the list is '
        'truncated on every write. CopilotClearView wipes the history '
        'on demand. The chat fragment template uses HTMX hx-swap to '
        'append the latest turn without reloading the page, so the '
        'session feels like a chat client even though the server still '
        'renders every fragment.',
    )

    # ════════════════════════════════════════════════════════════════════
    # X. Web layer
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'X. Web Layer')

    subsection(
        doc, code,
        '1) The Ten Django Apps',
        'The Django project hosts 10 feature apps. accounts holds the '
        'UserProfile model, RBAC decorators, the custom middlewares, '
        'and the password validators. analytics renders the dashboard '
        'and computes coverage and gap-priority metrics. comparison '
        'owns the regulation-versus-regulation workflow. core holds '
        'shared helpers, the Copilot chat endpoint, and the per-row '
        'scope filter. history is the audit log. home is the dashboard '
        'landing page. ingestion holds the upload UI, the quarantine '
        'queue, and the Channels WebSocket. library is the document '
        'browser. mapping owns the policy-versus-regulations workflow. '
        'review owns the accept, reject, modify lifecycle and the '
        'export builders.',
    )

    subsection(
        doc, code,
        '2) URL Routing Topology',
        'cjpca.urls is the project URL conf. It mounts each app under '
        'its own prefix (/accounts/, /library/, /comparison/, '
        '/mapping/, /review/, /history/, /analytics/, /ingestion/) and '
        'pulls in the two-factor flow at the project root through '
        'apps.accounts.urls_two_factor. Inside each app, the urls.py '
        'binds named routes to views with role gates applied at the '
        'view level through @role_required, never through template '
        'guards alone, so a template mistake cannot leak a view to the '
        'wrong role.',
    )

    subsection(
        doc, code,
        '3) Template Hierarchy',
        'cjpca/templates holds a single base.html that defines the '
        'navigation chrome, the Copilot side panel, and the messages '
        'frame. partials/ holds reusable fragments (the Copilot scope '
        'chip, the recent-activity card, the inline-edit form, the '
        'review decision chips). Each app contributes its own '
        'pages/<app>/ subdirectory that extends base.html. registration/ '
        'and two_factor/ override the django-allauth and '
        'django-two-factor-auth defaults so the login and MFA flows '
        'match the BBK visual style.',
    )

    subsection(
        doc, code,
        '4) HTMX Progress Polling Pattern',
        'Long-running jobs use HTMX polling: the run page loads with '
        'hx-get pointed at the progress endpoint and hx-trigger set to '
        'a 1 to 2 second timer. The progress endpoint returns a small '
        'HTML fragment that hx-swap inserts into the run page. When '
        'the job status transitions to DONE, the response sets an '
        'HX-Trigger header so the page can stop polling and load the '
        'final result table. This pattern keeps the request thread '
        'short-lived and works with the same view code as a '
        'full-page response, branching on request.htmx set by '
        'HtmxMiddleware.',
        outline_png='AP07_htmx_polling.png',
        caption_label='HTMX progress polling endpoint outline',
    )

    subsection(
        doc, code,
        '5) Channels WebSocket Consumer',
        'apps.ingestion.consumers.IngestionConsumer is the WebSocket '
        'endpoint at ws://<host>/ws/ingestion/<job_id>/. It joins a '
        'per-job channel group on connect, leaves the group on '
        'disconnect, and relays every group message to the client as '
        'JSON. The ingestion pipeline publishes progress events through '
        'channel_layer.group_send so the upload page sees stage '
        'transitions in real time. The channel layer is the Channels '
        'in-memory layer, which is sufficient for the single-host '
        'pilot.',
        outline_png='M06_channels_consumer.png',
        caption_label='Ingestion WebSocket consumer outline',
    )

    subsection(
        doc, code,
        '6) Alpine.js and HTMX',
        'Alpine.js 3.x handles small client-side state (dropdown open, '
        'modal visibility, tab selection) without a build step. HTMX '
        '2.x carries every partial swap and form submission. The two '
        'libraries combine well: Alpine drives in-page interactivity '
        'and HTMX drives server round trips. Both load from the unpkg '
        'CDN and the CSP script-src directive allows only those two '
        'origins plus jsdelivr.',
    )

    subsection(
        doc, code,
        '7) Tailwind and Chart.js',
        'Styling uses Tailwind via the CDN build, which avoids a Node '
        'build step on the BBK host. The CSP style-src directive '
        'allows fontshare.com for the typeface and self for the inline '
        'Tailwind atoms. Chart.js renders the dashboard coverage chart '
        'and the gap-priority distribution from a small JSON payload '
        'embedded in the page on render, so no extra round trip is '
        'needed once the dashboard is loaded.',
    )

    subsection(
        doc, code,
        '8) WhiteNoise Static-File Serving',
        'WhiteNoise sits second in the middleware chain and serves '
        'every static asset with cache-busting hashes and gzip '
        'compression. CompressedManifestStaticFilesStorage is the '
        'storage backend, which produces deterministic filenames so a '
        'CDN or browser cache can rely on the hash to detect '
        'changes. python manage.py collectstatic is the one-off '
        'command that gathers all app static files into '
        'STATIC_ROOT before deployment.',
    )

    # ════════════════════════════════════════════════════════════════════
    # XI. Cybersecurity build
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'XI. Cybersecurity Build')

    subsection(
        doc, code,
        '1) Security Stack Installation',
        '5 packages cover the cybersecurity surface. django-axes 6.x '
        'enforces brute-force lockout. django-otp 1.x and '
        'django-two-factor-auth 1.x provide TOTP enrolment and the '
        'login wizard. django-csp 4.x emits Content Security Policy '
        'headers. geoip2 4.x reads the MaxMind GeoLite2 country '
        'database for the optional GeoFence. All versions are pinned '
        'in requirements.txt so a supply-chain drift cannot land '
        'silently between machines.',
    )

    subsection(
        doc, code,
        '2) Middleware Chain Order',
        'cjpca.settings.MIDDLEWARE is the central artefact. 16 layers '
        'compose the request pipeline. The order is load-bearing and '
        'each slot has a specific defensive role. GeoFence runs first '
        'so blocked countries never reach login. Sessions, CSRF, and '
        'authentication follow the Django stock order. The OTP '
        'middleware must follow AuthenticationMiddleware because it '
        'reads request.user. Idle session timeout runs before the MFA '
        'gate. Force-password-change runs before force-MFA so new '
        'accounts rotate the temporary password before the TOTP setup '
        'wizard. django-axes runs last so it can observe the auth view '
        'response.',
        outline_png='M07_middleware_chain.png',
        caption_label='Ordered MIDDLEWARE chain',
    )

    subsection(
        doc, code,
        '3) Password Validators',
        'AUTH_PASSWORD_VALIDATORS runs 6 validators on every credential '
        'change. UserAttributeSimilarityValidator is set to 0.5 '
        '(stricter than the Django default of 0.7) to reject passwords '
        'that share substrings with the username, name, or email. '
        'MinimumLengthValidator is bumped to 12 characters. '
        'CommonPasswordValidator and NumericPasswordValidator catch '
        'breached-list entries and all-numeric passwords. Two custom '
        'validators (ComplexityValidator, NoUsernameValidator) cover '
        'character-class requirements and username embedding.',
        outline_png='M08_password_validators.png',
        caption_label='AUTH_PASSWORD_VALIDATORS configuration',
    )

    subsection(
        doc, code,
        '4) Custom ComplexityValidator and NoUsernameValidator',
        'apps.accounts.validators.ComplexityValidator requires upper, '
        'lower, digit, and a non-alphanumeric symbol. The toggles let '
        'individual classes be relaxed in test environments but the '
        'production install requires all 4. NoUsernameValidator rejects '
        'a password that contains the username or the email substring '
        'after lower-casing. Both raise ValidationError with a '
        'code attribute so the templates can produce targeted error '
        'messages that tell the user which class is missing.',
        outline_png='AP08_complexity_validator.png',
        caption_label='ComplexityValidator class outline',
    )

    subsection(
        doc, code,
        '5) AuditLog Model and Twenty-Eight Action Constants',
        'apps.history.models.AuditLog is the append-only audit table. '
        'Fields are event_type, user (FK with on_delete=SET_NULL so '
        'rows survive user deletion), user_role_at_time (snapshot at '
        'write time), ip_address, timestamp, description, '
        'related_object_type, related_object_id, and change_detail '
        '(JSON). Composite indexes on (user, -timestamp) and '
        '(event_type, -timestamp) keep compliance queries fast. The '
        'Actions class enumerates 28 constants including auth.login, '
        'auth.logout, auth.login_failed, auth.idle_timeout, '
        'auth.mfa_enrolled, document.upload, document.delete, '
        'quarantine.flagged, quarantine.approved, quarantine.rejected, '
        'comparison.run, comparison.done, mapping.run, mapping.done, '
        'review.approved, review.rejected, review.modified, '
        'review.gap_synced, export.pdf, export.xlsx, '
        'user.password_changed, user.role_changed, user.created, and '
        'reasoning.validation_error.',
        outline_png='AP12_audit_log_model.png',
        caption_label='AuditLog model and indexes',
    )

    subsection(
        doc, code,
        '6) log_event Helper',
        'apps.history.audit.log_event is the single write surface for '
        'audit rows. It accepts user, action, request, target_type, '
        'target_id, description, and metadata. Internally it resolves '
        'the username, snapshots the actor role through _snapshot_role, '
        'extracts the client IP through _extract_ip (X-Forwarded-For '
        'first hop or REMOTE_ADDR), and writes the row through '
        'AuditLog.objects.create. The entire body is wrapped in try '
        'and except so a write failure logs a warning but never '
        'propagates into the calling view. This keeps audit failures '
        'from cascading into a user-visible 500.',
        outline_png='AP13_log_event.png',
        caption_label='log_event helper outline',
    )

    subsection(
        doc, code,
        '7) Auth Signal Handlers',
        'apps.history.signals connects every Django auth signal to '
        'log_event. user_logged_in writes auth.login. user_logged_out '
        'writes auth.logout. user_login_failed writes '
        'auth.login_failed and stores the attempted_username in the '
        'metadata payload (the password has already been stripped by '
        'Django before the signal fires). A post_save receiver on '
        'TOTPDevice writes auth.mfa_enrolled on the first save of a '
        'confirmed device. The signals never block the auth flow '
        'because log_event swallows write failures.',
        outline_png='M09_audit_signals.png',
        caption_label='Auth signal handlers outline',
    )

    subsection(
        doc, code,
        '8) GeoFence Middleware',
        'apps.accounts.middleware.GeoFenceMiddleware reads the MaxMind '
        'GeoLite2 country database with double-checked locking and '
        'caches the reader on the middleware instance. Private and '
        'loopback IP ranges always pass. For external IPs the country '
        'code is looked up and matched against an upper-cased allowlist '
        '(BH, IN, KW, AE by default). The middleware fails open on '
        'lookup error so a missing database does not lock BBK staff '
        'out, which is the right trade-off for an internal system.',
        outline_png='AP11_geofence.png',
        caption_label='GeoFenceMiddleware outline',
    )

    subsection(
        doc, code,
        '9) ForceMFAEnrollmentMiddleware',
        'apps.accounts.middleware.ForceMFAEnrollmentMiddleware redirects '
        'any authenticated user without a confirmed TOTP device to the '
        'two-factor setup wizard. The check is gated by REQUIRE_MFA '
        '(False in the BBK demo, True in production). Path prefixes '
        'and URL names for the setup flow itself are exempt so the '
        'redirect is not a redirect loop. The middleware imports '
        'django_otp.user_has_device lazily so the module imports '
        'cleanly even on minimal installs.',
        outline_png='AP10_force_mfa.png',
        caption_label='ForceMFAEnrollment middleware outline',
    )

    subsection(
        doc, code,
        '10) IdleSessionTimeoutMiddleware',
        'apps.accounts.middleware.IdleSessionTimeoutMiddleware tracks '
        '_last_activity in the session and signs the user out after '
        'SESSION_IDLE_TIMEOUT seconds (default 1 800). On expiry it '
        'writes an auth.idle_timeout AuditLog row with idle_seconds in '
        'the metadata before calling logout and redirecting to the '
        'login page with ?reason=idle, so the login template can '
        'render the right banner.',
        outline_png='AP09_idle_session.png',
        caption_label='IdleSessionTimeout middleware outline',
    )

    subsection(
        doc, code,
        '11) RBAC Decorator and Mixin',
        'apps.accounts.decorators exposes @role_required and '
        'RoleRequiredMixin for class-based views. Both resolve the '
        'role via get_user_role on the UserProfile, redirect '
        'unauthenticated callers via login_required, and return '
        'HttpResponseForbidden 403 on role mismatch. Per-row scope '
        'enforcement on MappingAnalysis and ComparisonRun runs '
        'separately, filtering by created_by so analysts see only '
        'their own jobs while reviewers and admins see the full set.',
        outline_png='AP14_role_required.png',
        caption_label='role_required decorator outline',
    )

    subsection(
        doc, code,
        '12) Content Security Policy and Security Headers',
        'CONTENT_SECURITY_POLICY in settings.py is a dict-driven CSP '
        'configuration consumed by django-csp 4.x. default-src is '
        'self, script-src adds unpkg and jsdelivr, style-src adds '
        'api.fontshare.com, img-src adds flagcdn.com and data: blob:, '
        'connect-src is self, frame-ancestors is none for clickjacking '
        'defence, base-uri and form-action are self. HSTS is enabled '
        'with a 31 536 000 second max-age, subdomain inclusion, and '
        'preload. X-Frame-Options is DENY, '
        'SECURE_CONTENT_TYPE_NOSNIFF is True, and '
        'SECURE_REFERRER_POLICY is same-origin. The legacy '
        'SECURE_BROWSER_XSS_FILTER is also enabled as a defence in '
        'depth for older browsers.',
    )

    # ════════════════════════════════════════════════════════════════════
    # XII. Export and audit hash chain
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'XII. Export and Audit Hash Chain')

    subsection(
        doc, code,
        '1) PDF Builder',
        'apps.review.exports.build_pdf renders a finished mapping or '
        'comparison as an A4 PDF through ReportLab 4.x. A '
        'SimpleDocTemplate is built with a title block, a header '
        'metadata table, and a per-row Table styled in navy with '
        'alternating row shading. The audit_hash is appended as the '
        'last column on every row, so the artefact carries its '
        'tamper-evident prefix down to the row level.',
        outline_png='AP15_export_builder.png',
        caption_label='PDF and XLSX export builder outline',
    )

    subsection(
        doc, code,
        '2) XLSX Builder',
        'build_xlsx uses openpyxl 3.x to produce a parallel XLSX '
        'workbook. The header row includes an audit_hash column and '
        'each row is written with its hash alongside the data. The '
        'XLSX export is what analysts share with auditors who prefer a '
        'spreadsheet, while the PDF is used for printed evidence and '
        'board-level reports.',
    )

    subsection(
        doc, code,
        '3) audit_hash Helper',
        'apps.review.exports.audit_hash returns the first 16 characters '
        'of a SHA-256 hex digest over the row identity tuple (class '
        'name, primary key, lifecycle status, completed_at, '
        'submitted_for_review_at, created_by_id). It is not a digital '
        'signature (no key, no certificate). It is a tamper-evidence '
        'marker. A reviewer who downloads a PDF can recompute the hash '
        'from the live row and compare, so a silent post-export edit '
        'is detectable.',
        outline_png='M10_audit_hash.png',
        caption_label='audit_hash helper full outline',
    )

    # ════════════════════════════════════════════════════════════════════
    # XIII. Management commands inventory
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'XIII. Management Commands Inventory')

    add_paragraph(
        doc,
        '12 management commands cover ingestion, workflow dispatch, '
        'classification backfill, library reconciliation, demo seeding, '
        'and operational maintenance. Every command is invoked through '
        'python manage.py <name> and exits with a non-zero code on '
        'failure so it integrates cleanly with cron or task-scheduler '
        'runners.',
    )

    subsection(doc, code, '1) full_ingest',
        'Bulk ingestion command. Walks data/regulations and '
        'data/internal_policies, optionally re-converts PDFs through '
        'Docling in subprocess workers, wipes the existing indexes, '
        'rebuilds them per file (load -> chunk -> scan -> embed -> '
        'index), hydrates metadata from metadata.csv, recounts chunks, '
        'and runs the wiring_audit at the end. Requires --apply to do '
        'destructive work, otherwise prints a dry-run plan.')

    subsection(doc, code, '2) run_comparison_job',
        'Subprocess entry point that runs one ComparisonRun by primary '
        'key. Spawned by the comparison_scope view when the analyst '
        'clicks Run. Re-asserts the run as RUNNING in case '
        'AppConfig.ready had reset it, then calls '
        '_run_comparison_background.')

    subsection(doc, code, '3) run_mapping_job',
        'Symmetric to run_comparison_job for the mapping workflow. '
        'Receives an analysis_pk plus an --auto-scope flag and calls '
        '_run_mapping_background.')

    subsection(doc, code, '4) classify_chunks',
        'Backfill command for the LLM chunk classifier. Selects chunks '
        'without a chunk_tags row, calls reasoning.classifier.'
        'classify_chunk per chunk, and writes the result through '
        'retrieval.bm25_store.upsert_chunk_tags.')

    subsection(doc, code, '5) classify_doc_topics',
        'Aggregates per-chunk topic tags into per-Document '
        'classified_topics arrays so the library grid can filter '
        'documents by topic without re-querying chunk_tags every '
        'render.')

    subsection(doc, code, '6) sync_documents',
        'Walks the corpus folder and adds Document rows for new files '
        'or marks rows missing whose files have been deleted on disk. '
        'Keeps the Django library in sync with the file system source '
        'of truth.')

    subsection(doc, code, '7) reconcile_library',
        'Repair command for inconsistent state between Document rows, '
        'chunks in the BM25 store, and vectors in Chroma. Updates '
        'Document.chunk_count from BM25 and flags mismatches.')

    subsection(doc, code, '8) restore_from_chunks',
        'Rebuilds the in-memory indexes from the persisted chunk '
        'tables when chroma_data is wiped (cache loss, corruption). '
        'Walks bm25_store rows, re-embeds, and re-indexes through '
        'Chroma.')

    subsection(doc, code, '9) seed_demo',
        'Populates a small demo corpus (one document per jurisdiction) '
        'for screenshots and smoke tests. Triggers full_ingest scoped '
        'to those files.')

    subsection(doc, code, '10) demo_injection_doc',
        'Generates a PDF that triggers every Tier-A regex rule. Used '
        'to populate the quarantine queue with a known set of '
        'detections for the user manual screenshots.')

    subsection(doc, code, '11) seed_review_samples',
        'Creates ReviewItem rows in mixed states (pending, approved, '
        'modified) so the review inbox renders all three columns '
        'during a demo.')

    subsection(doc, code, '12) cleanup_failed',
        'Moves any RUNNING ComparisonRun or MappingAnalysis older than '
        'the configured timeout (default 120 minutes) to FAILED. '
        'Called from AppConfig.ready on process start so the system '
        'never displays a stuck job after a crash restart.')

    # ════════════════════════════════════════════════════════════════════
    # XIV. Reasoning extras
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'XIV. Reasoning Extras')

    subsection(
        doc, code,
        '1) The Twelve-Topic Taxonomy',
        'reasoning.taxonomy defines the 12 canonical topics used by '
        'chunk classification, the comparison topic-scan, and the '
        'analytics view. The 12 topics are Definitions, '
        'Data_Subject_Rights, Lawful_Basis, Consent, '
        'Cross_Border_Transfer, Breach_Notification_Timeline, DPO, '
        'Sensitive_Data, Record_Keeping, Vendor_Management, '
        'Enforcement, and Children_and_Minors. Every chunk that the '
        'LLM classifier accepts maps to one of these or to '
        'UNCLASSIFIED. The taxonomy is a controlled vocabulary, so '
        'invented topics from the LLM are rejected at the normalisation '
        'step rather than polluting the analytics aggregator.',
    )

    subsection(
        doc, code,
        '2) Term Dictionary Structure',
        'reasoning.term_dictionary holds about 200 jurisdictional '
        'synonyms organised by topic category. Each entry maps a '
        'canonical term to one or more variants used by Bahrain PDPL, '
        'India DPDPA, and Kuwait DPPR. For example, "consent" maps to '
        '"explicit consent", "informed consent", and the Arabic-to-'
        'English statutory variants present in the source corpus. The '
        'public entry points are synonyms_for_query (used by the '
        'retriever at query time), all_terms (used by the term '
        'browser), and by_category (used by analytics).',
    )

    subsection(
        doc, code,
        '3) Prompt Registry',
        'Reasoning prompts live under reasoning/prompts/ as YAML files '
        'loaded through reasoning.prompts.registry.load_prompt. Each '
        'workflow node has its own file (draft_comparison.yaml, '
        'verify.yaml, correct.yaml, chunk_classifier.yaml, '
        'route.yaml). The prompt registry pattern lets a reviewer '
        'audit every prompt without touching code, and lets a developer '
        'A or B test prompt variants by swapping the file at the '
        'registry layer rather than across the call sites.',
    )

    # ════════════════════════════════════════════════════════════════════
    # XV. Logging, observability, and configuration reference
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc,
        'XV. Logging, Observability, and Configuration Reference')

    subsection(
        doc, code,
        '1) Per-Job Log Files',
        'Every long-running job writes a per-job log file at '
        'logs/run_<job_type>_<job_id>.log. The log captures the full '
        'traceback context that AuditLog rows deliberately do not '
        'carry, so a post-mortem investigation has both the structured '
        'audit row (who, what, when) and the detailed exception trace '
        '(why) without coupling the two. Log files are rotated '
        'operationally on the BBK host on a daily schedule with a '
        '30-day retention.',
    )

    subsection(
        doc, code,
        '2) Django LOGGING Configuration',
        'settings.LOGGING defines module-level loggers for ingestion, '
        'retrieval, reasoning, and apps.history, each with a console '
        'handler and a file handler. The audit sanitiser strips fields '
        'matching key, token, secret, or password patterns from any '
        'log payload before persistence, so the per-job log files are '
        'safe to share with auditors without exposing secrets. Log '
        'level is INFO in production and DEBUG when DEBUG=True.',
    )

    subsection(
        doc, code,
        '3) Recent-Activity Widget',
        'apps.analytics.aggregators.compute_recent_activity reads the '
        'most recent 20 AuditLog rows ordered by -timestamp and '
        'serialises them for the dashboard recent-activity feed. The '
        'feed gives an analyst a quick view of what other team '
        'members are doing without granting them inspection of '
        'individual rows the role-based scope filter would otherwise '
        'hide.',
    )

    subsection(
        doc, code,
        '4) Environment Variable Reference',
        'The .env file at the project root holds every operational '
        'toggle. The replicator copies .env.example to .env and fills '
        'in the values. The table below lists every variable, its '
        'default, and what it controls.',
    )
    env_table = (
        'Variable                          Default                     What it controls\n'
        '-------------------------------------------------------------------------------------\n'
        'DEBUG                             true                        Django debug mode\n'
        'SECRET_KEY                        <placeholder>               Django secret\n'
        'DJANGO_ALLOWED_HOSTS              localhost,127.0.0.1         Allowed Host headers\n'
        'REQUIRE_MFA                       true                        Force MFA enrolment\n'
        'TWO_FACTOR_PATCH_ADMIN            true                        2FA on Django admin\n'
        'GEOFENCE_ENABLED                  false                       Country allowlist\n'
        'GEOFENCE_ALLOWED_COUNTRIES        BH,IN,KW,AE                 Allowed ISO codes\n'
        'GEOIP_DATABASE_PATH               data/GeoLite2-Country.mmdb  MaxMind DB path\n'
        'SESSION_IDLE_TIMEOUT              1800                        Idle seconds\n'
        'AXES_FAILURE_LIMIT                5                           Lockout threshold\n'
        'AXES_COOLOFF_TIME                 0.5                         Lockout hours\n'
        'OPENROUTER_API_KEY                <empty>                     LLM provider key\n'
        'INJECTION_JUDGE_MODEL             anthropic/claude-haiku-4-5  Tier-B judge model\n'
        'OLLAMA_URL                        http://localhost:11434      Local LLM endpoint\n'
        'OLLAMA_MODEL                      llama3.2:1b                 Local LLM model\n'
        'EMAIL_BACKEND                     console                     Email transport\n'
        'EMAIL_HOST / PORT / USER / PASS   <empty>                     SMTP config\n'
        'HF_HOME                           hf_cache/                   Model cache dir\n'
    )
    add_monospace(doc, env_table, size=8)
    add_caption(doc, f'Figure A.3.{next_fig()}.',
                '.env configuration reference')

    # ════════════════════════════════════════════════════════════════════
    # XVI. Deployment to BBK workstation
    # ════════════════════════════════════════════════════════════════════
    add_section_heading(doc, 'XVI. Deployment to BBK Workstation')

    subsection(
        doc, code,
        '1) Production Environment Toggles',
        'Promoting the system to the BBK workstation requires a small '
        'set of env-var changes. DEBUG is set to False, SECRET_KEY is '
        'rotated to a fresh 60-character value, REQUIRE_MFA is True, '
        'GEOFENCE_ENABLED is True, SECURE_SSL_REDIRECT is True. '
        'Every change is captured below so the replicator can copy '
        'the snippet into .env on the production host.',
    )
    add_monospace(doc, (
        'DEBUG=False\n'
        'SECRET_KEY=<rotate to a fresh 60-char value>\n'
        'REQUIRE_MFA=True\n'
        'GEOFENCE_ENABLED=True\n'
        'GEOFENCE_ALLOWED_COUNTRIES=BH,IN,KW,AE\n'
        'SECURE_SSL_REDIRECT=True\n'
    ))
    add_caption(doc, f'Figure A.3.{next_fig()}.', 'Production .env toggles')

    subsection(
        doc, code,
        '2) Reverse Proxy Configuration',
        'A Caddy reverse proxy terminates TLS 1.3 on port 443 and '
        'forwards plain HTTP to the Django ASGI process listening on '
        'localhost:8000. The Caddy config below applies gzip encoding '
        'and adds Strict-Transport-Security with a 31 536 000 second '
        'max-age, includeSubDomains, and preload. Caddy obtains and '
        'rotates the certificate automatically from the host CA store '
        'or Let s Encrypt when the host is internet-reachable, and '
        'serves the local CA-issued certificate otherwise.',
    )
    add_monospace(doc, (
        'cjpca.bbk.local {\n'
        '    encode gzip\n'
        '    tls /etc/ssl/cjpca.crt /etc/ssl/cjpca.key\n'
        '    header Strict-Transport-Security '
        '"max-age=31536000; includeSubDomains; preload"\n'
        '    reverse_proxy 127.0.0.1:8000\n'
        '}\n'
    ))
    add_caption(doc, f'Figure A.3.{next_fig()}.',
                'Caddy reverse-proxy configuration')

    subsection(
        doc, code,
        '3) ASGI Process and Channels',
        'Production runs the Django ASGI application through Daphne so '
        'WebSocket support is preserved. The daphne process is '
        'wrapped by a Windows service (created with sc.exe or NSSM) '
        'so it restarts on failure. routing.py mounts the IngestionConsumer '
        'at ws://<host>/ws/ingestion/<job_id>/. The Channels in-memory '
        'layer is sufficient for a single-host pilot, with the '
        'channel layer config in settings.py defaulting to '
        'channels.layers.InMemoryChannelLayer.',
    )
    add_monospace(doc, (
        '> daphne -b 127.0.0.1 -p 8000 cjpca.asgi:application\n'
    ))
    add_caption(doc, f'Figure A.3.{next_fig()}.', 'Daphne ASGI process command')

    subsection(
        doc, code,
        '4) Backup Procedures and Health Verification',
        '4 directories on the BBK host require regular backup: '
        'cjpca/db.sqlite3 (Django app data and audit log), '
        'chroma_data/ (vector index and BM25 store), media/ (uploaded '
        'documents), and logs/ (per-job log files). A daily '
        'Volume Shadow Copy of the project root captures all 4 in one '
        'pass. Health is verified by running python manage.py '
        'check --deploy, which must return zero issues, and by '
        'hitting /healthz/ from the reverse proxy to confirm the '
        'application is up.',
    )

    doc.save(out_path)
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
