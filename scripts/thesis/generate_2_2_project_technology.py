"""Generate §2.2 Project Technology as 9 separate tables.

Output: thesis_docs/2_2_project_technology.docx

Each table covers one technology category (Programming Language, Web
Framework, Databases, AI Pipeline Frameworks, LLM Providers, Frontend,
ML Models, Document Parsing, Development Tools). Each row follows the
saved thesis convention: Use, Justification, Challenge as three
sentences in a single Description cell.
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


def add_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_tech_table(doc, rows, widths_cm=(4.5, 12.0), body_size=10):
    table = doc.add_table(rows=1 + len(rows), cols=2)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for col_idx, w in enumerate(widths_cm):
        for cell in table.columns[col_idx].cells:
            cell.width = Cm(w)
    header_row = table.rows[0]
    for i, h in enumerate(['Technology', 'Description']):
        cell = header_row.cells[i]
        cell.text = h
        shade_cell(cell, '002583')
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in para.runs:
            set_run_style(run, bold=True, color=WHITE, size=11)
    for r_idx, (tech, desc) in enumerate(rows, start=1):
        row = table.rows[r_idx]
        tech_cell = row.cells[0]
        tech_cell.text = tech
        tech_cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
        for para in tech_cell.paragraphs:
            for run in para.runs:
                set_run_style(run, bold=True, color=DARK_GRAY,
                              size=body_size)
        desc_cell = row.cells[1]
        desc_cell.text = desc
        desc_cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
        for para in desc_cell.paragraphs:
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            for run in para.runs:
                set_run_style(run, color=DARK_GRAY, size=body_size)


# -------------------------------------------------------------------------
# DATA — 9 categories
# -------------------------------------------------------------------------

PROGRAMMING_LANGUAGE = [
    ('Python 3.11+',
     'Python 3.11+ is the language for the entire stack including the '
     'web application, the ingestion pipeline, the retrieval layer, '
     'and the reasoning workflows. JavaScript and Java were considered '
     'as alternatives, but Python provides earlier access to AI and '
     'NLP frameworks and avoids polyglot integration costs. Python is '
     'slower than Java for CPU-intensive workloads, which is mitigated '
     'by offloading heavy inference to PyTorch and external LLM '
     'providers.'),
]


WEB_FRAMEWORK = [
    ('Django 5',
     'Django 5 provides the web framework, the ORM, the authentication '
     'backend, the MFA hooks via django-otp, and the admin interface. '
     'FastAPI with React and Flask were considered, but Django reduces '
     'development overhead and lets the project focus on AI '
     'functionality rather than framework plumbing. Django\'s '
     'synchronous request cycle requires Django Channels for live AI '
     'task streaming, adding an ASGI deployment path alongside the '
     'WSGI request path.'),
]


DATABASES = [
    ('SQLite 3',
     'SQLite 3 is the primary relational store for users, documents, '
     'audit logs, and reasoning artefacts. PostgreSQL and MySQL were '
     'alternatives, but the single-file architecture removes the need '
     'for a separate database server and simplifies thesis-prototype '
     'deployment. Limited high-concurrency write support means a '
     'production deployment at BBK scale would need migration to '
     'PostgreSQL.'),
    ('SQLite FTS5',
     'SQLite FTS5 is the BM25-ranked lexical retriever, with '
     'persistent on-disk indexing and metadata filtering on '
     'jurisdiction and document type. LlamaIndex\'s in-memory '
     'retriever was the alternative, but FTS5 achieved a higher '
     'hit-rate@5 on the gold test set and supports incremental '
     'indexing without rebuilding from scratch. Index schemas require '
     'manual maintenance when document metadata changes, mitigated by '
     'a single management command for reindex.'),
    ('ChromaDB',
     'ChromaDB hosts the semantic retrieval layer with a persistent '
     'in-process vector store and metadata filtering for '
     'jurisdiction-scoped queries. FAISS, Qdrant, and PostgreSQL with '
     'pgvector were considered, but ChromaDB requires no separate '
     'server and integrates directly with LlamaIndex. Occasional '
     'Windows file-locking when multiple clients access it '
     'simultaneously, mitigated by serialising concurrent writes.'),
]


AI_FRAMEWORKS = [
    ('LangChain',
     'LangChain provides prompt templates, output parsers, and the '
     'OutputFixingParser used for bounded automatic correction of LLM '
     'responses. Manual API wrappers were the alternative, but '
     'LangChain abstracts model providers, accelerates prompt '
     'iteration, and standardises retry handling. Frequent breaking '
     'changes between versions require pinned dependencies and '
     'defensive imports.'),
    ('LangGraph',
     'LangGraph orchestrates the reasoning agent as an explicit state '
     'machine with prepare, draft, verify, correct, finalize, and '
     'fallback nodes. Linear chains and manual Python retry loops '
     'were considered, but the graph structure makes verification '
     'logic extensible and improves debuggability by exposing every '
     'state transition. Relative novelty means fewer tutorials and '
     'community examples, requiring deeper reading of source code '
     'when extending nodes.'),
    ('LlamaIndex',
     'LlamaIndex is the retrieval framework that connects queries to '
     'ChromaDB and FTS5, runs reciprocal rank fusion, and applies the '
     'cross-encoder reranker. LangChain retrievers and custom '
     'retrieval code were considered, but LlamaIndex has built-in '
     'fusion, flexible integration, and a NodeWithScore abstraction '
     'that fits the citation-grounding requirement. Fixed defaults on '
     'some parameters and occasional version compatibility issues '
     'with the vector store interface.'),
]


LLM_PROVIDERS = [
    ('Ollama',
     'Ollama serves the primary LLM inference layer locally on '
     'localhost:11434, hosting llama3.2:1b for the analytical '
     'content path. Direct cloud APIs (Anthropic, OpenAI) and '
     'OpenRouter were considered, but local hosting keeps every '
     'analyst query and every retrieved regulatory clause inside '
     'the on-premises host. Slower CPU inference than cloud models, '
     'mitigated by routing analytical content through Ollama and '
     'reserving the only external call for the narrow Tier-B '
     'injection judge described in the next row.'),
    ('Claude Haiku 4.5',
     'Claude Haiku 4.5 serves the Tier-B prompt-injection judge, '
     'called only on chunks already flagged as suspect by the '
     'Tier-A regex scanner. GPT-4 and Gemini Flash were considered, '
     'but Claude Haiku offers the best speed and cost for short '
     'verdict-style prompts. This is the only external call in the '
     'system, and it carries only the suspect chunk with no analyst '
     'identifier, no document metadata, and no analytical content.'),
]


IAM_LIBRARIES = [
    ('django-otp',
     'django-otp provides the TOTP device framework that backs the '
     'multi-factor authentication flow. django-allauth and Authy '
     'were considered, but django-otp integrates cleanly with the '
     'Django auth backend and supports backup-token recovery. '
     'Documentation is sparse for non-standard device types.'),
    ('django-axes',
     'django-axes locks accounts after a configurable threshold of '
     'failed login attempts, keyed on username and source IP. '
     'Custom rate-limit middleware was considered, but django-axes '
     'integrates with the Django auth signals and exposes admin '
     'views out of the box. Aggressive defaults can lock legitimate '
     'users, mitigated by tuning the cool-off period.'),
    ('django-csp',
     'django-csp emits the Content Security Policy response headers '
     'that whitelist allowed script, style, and image sources. '
     'Manual header middleware was considered, but django-csp '
     'covers every CSP directive without hand-coded strings. Strict '
     'CSP requires whitelisting external CDNs explicitly.'),
]


DEPLOYMENT_INFRA = [
    ('Caddy',
     'Caddy terminates TLS 1.3 at the perimeter, enforces HSTS, sets '
     'the security response headers, and reverse-proxies requests to '
     'the application server. Nginx and Apache were considered, but '
     'Caddy provides automatic certificate management and a smaller '
     'configuration file. Less throughput tuning than Nginx for very '
     'large workloads.'),
    ('Daphne',
     'Daphne hosts the Django ASGI application, serving both HTTP '
     'routes and WebSocket connections under one process. Uvicorn '
     'and Hypercorn were considered, but Daphne is the reference '
     'Channels server with the broadest community support. Lower '
     'raw performance than Uvicorn for HTTP-only workloads.'),
    ('WhiteNoise',
     'WhiteNoise serves static assets directly from the application '
     'process with compressed manifest caching. A separate static '
     'file server was considered, but WhiteNoise keeps the '
     'deployment to a single process. Not suitable for very large '
     'static asset catalogues.'),
    ('MaxMind GeoLite2',
     'MaxMind GeoLite2 supplies the IP-to-country lookup used by '
     'the GeoFence middleware to allow only Bahrain, India, and '
     'Kuwait. IP2Location and ipapi were considered, but GeoLite2 '
     'is free for non-commercial use and ships as a local file with '
     'no per-request external call. Database files require periodic '
     'refresh.'),
]


FRONTEND = [
    ('Tailwind CSS',
     'Tailwind CSS provides utility-first styling for every page, '
     'compiled via the standalone CLI without a Node build pipeline. '
     'Bootstrap and plain CSS were considered, but Tailwind enables '
     'rapid prototyping and produces small purged stylesheets that '
     'ship to the browser. Verbose class strings inside templates '
     'reduce readability, mitigated by extracting common patterns '
     'into Django template partials.'),
    ('HTMX',
     'HTMX drives partial page updates and live fragments such as the '
     'ingestion progress widget, the mapping workspace, and the '
     'quarantine queue, directly from Django templates. React and Vue '
     'were considered, but HTMX avoids a separate frontend build and '
     'API layer and keeps the security boundary on the server. Weaker '
     'support for heavy client-side state, mitigated by pairing HTMX '
     'with Alpine.js for in-page reactivity.'),
    ('Alpine.js',
     'Alpine.js provides lightweight client-side reactivity for '
     'modals, tab switching, the idle-warning countdown, and '
     'form-validation hints. Vanilla JavaScript and Vue were '
     'considered, but Alpine.js requires no build step, declares '
     'state directly in HTML attributes, and keeps the codebase free '
     'of compiled JavaScript bundles. Not suited for complex '
     'single-page application logic, mitigated by routing complex '
     'flows back through HTMX server-side partials.'),
]


ML_LIBRARIES = [
    ('PyTorch',
     'PyTorch executes the BGE-small embedding model, the '
     'cross-encoder reranker, and the DeBERTa-v3 NLI hallucination '
     'detector. TensorFlow and ONNX Runtime were considered, but '
     'HuggingFace models are released for PyTorch first and PyTorch '
     'supports seamless CPU/GPU execution. Large installation size '
     'and difficult GPU setup on Windows, mitigated by documenting '
     'the CUDA installation path and providing a CPU fallback.'),
    ('HuggingFace',
     'HuggingFace supplies the pre-trained models used for '
     'embeddings, reranking, and hallucination detection, downloaded '
     'once and cached locally. Building bespoke models was considered, '
     'but HuggingFace provides immediate access to high-quality '
     'open-weight models so project time can focus on system design. '
     'Large initial downloads (several gigabytes total) and disk '
     'storage requirements for model weights, mitigated by a shared '
     'cache path documented in .env.'),
    ('BGE-small-en-v1.5',
     'BGE-small-en-v1.5 is the 384-dimensional embedding model used '
     'by the semantic retrieval lane. all-MiniLM-L6-v2 and OpenAI '
     'text-embedding-3-small were considered, but BGE-small balances '
     'retrieval quality with CPU-feasible inference. English-only '
     'coverage, acceptable because the regulatory corpus is '
     'English-only.'),
    ('DeBERTa-v3 NLI',
     'DeBERTa-v3 base NLI is the cross-encoder Natural Language '
     'Inference model used by the hallucination gate. RoBERTa-MNLI '
     'and BART-MNLI were considered, but DeBERTa-v3 offers higher '
     'accuracy at comparable size. Inference cost per output, '
     'mitigated by aggregating clause scores before invoking the '
     'gate.'),
    ('ms-marco MiniLM cross-encoder',
     'The ms-marco MiniLM-L-6-v2 cross-encoder reranks the top 20 '
     'candidates returned by reciprocal rank fusion against the '
     'original query. Pure RRF and BERT-based rerankers were '
     'considered, but MiniLM offers the best speed-quality trade-off. '
     'Adds latency on every retrieval, capped by the 20-candidate '
     'pool.'),
]


DOC_PARSING = [
    ('Docling',
     'Docling converts regulatory and policy documents into '
     'structured text that preserves headings, tables, and reading '
     'order across PDF, DOCX, and HTML inputs. PyMuPDF and '
     'pdfminer.six were considered, but Docling preserves the '
     'structural hierarchy that legal documents rely on for citation '
     'accuracy. Relatively slow processing time and a large '
     'installation footprint, mitigated by running ingestion as a '
     'background subprocess driven by the WebSocket consumer.'),
    ('Pydantic v2',
     'Pydantic v2 validates the JSON outputs of the LLM into typed '
     'data structures consumed by the views and the workflows. '
     'Python dataclasses and ad-hoc validation were considered, but '
     'Pydantic provides strict typing, clear error reporting, and '
     'integration with the OutputFixingParser feedback loop. Strict '
     'parsing behaviour requires careful default values for partial '
     'outputs, mitigated by typed-empty SafeFallback schemas.'),
]


DEV_TOOLS = [
    ('Git',
     'Git provides distributed version control for the entire '
     'codebase, including documentation and migration history. '
     'Mercurial and SVN were considered, but Git is the industry '
     'standard with the strongest tooling for collaboration and CI '
     'integration. No significant limitations encountered in this '
     'project.'),
    ('GitHub',
     'GitHub hosts the remote repository, the issue tracker, and the '
     'continuous-integration check pipeline. GitLab and Bitbucket '
     'were considered, but GitHub has widespread adoption, free '
     'public-repository support, and strong third-party CI '
     'integration. Sensitive data such as secrets and .env files '
     'must be excluded via .gitignore, mitigated by a pre-commit '
     'hook that scans for known secret patterns.'),
    ('Visual Studio Code (VS Code)',
     'Visual Studio Code is the integrated development environment '
     'used for coding, debugging, and Git operations. PyCharm, '
     'Sublime Text, and JupyterLab were considered, but VS Code is '
     'free, has strong Python and Django support via extensions, '
     'and includes an integrated terminal. No significant '
     'limitations encountered in this project.'),
]


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '2_2_project_technology.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = (out_dir /
                             f'2_2_project_technology_v{n}.docx')
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    add_heading(doc, '2.2 Project Technology', level=1)
    add_paragraph(
        doc,
        'The system is built on a multi-layered technology stack. Each '
        'table below covers one category, listing the technology used, '
        'the justification for the choice, and the main challenge '
        'accepted with it.',
    )

    sections = [
        ('Programming Language', PROGRAMMING_LANGUAGE,
         'Table 1.', 'Programming language selection.'),
        ('Web Framework', WEB_FRAMEWORK,
         'Table 2.', 'Web framework selection.'),
        ('Identity and Access Libraries', IAM_LIBRARIES,
         'Table 3.', 'Identity and access libraries.'),
        ('Databases and Data Stores', DATABASES,
         'Table 4.', 'Databases and data stores.'),
        ('AI Pipeline Frameworks', AI_FRAMEWORKS,
         'Table 5.', 'AI pipeline frameworks.'),
        ('Language Model Providers', LLM_PROVIDERS,
         'Table 6.', 'Language model providers.'),
        ('Frontend', FRONTEND,
         'Table 7.', 'Frontend technologies.'),
        ('Machine Learning Models and Libraries', ML_LIBRARIES,
         'Table 8.', 'Machine learning models and libraries.'),
        ('Document Parsing and Data Validation', DOC_PARSING,
         'Table 9.', 'Document parsing and data validation.'),
        ('Development Tools', DEV_TOOLS,
         'Table 10.', 'Development tools.'),
        ('Deployment and Infrastructure', DEPLOYMENT_INFRA,
         'Table 11.', 'Deployment and infrastructure.'),
    ]

    for heading_text, rows, caption_label, caption_text in sections:
        add_heading(doc, heading_text, level=2)
        add_caption(doc, caption_label, caption_text)
        add_tech_table(doc, rows)

    doc.save(out_path)
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
