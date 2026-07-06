"""
Generate the "Project Technology" thesis section as a .docx file.

Produces: thesis_project_technology.docx in the project root.

Word budget: tables total ~1000 words across all categories. Each cell follows
the same three-beat pattern as the user's previous thesis (Use; Justification
with alternative; Challenge), compressed into one tight sentence.
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.shared import Cm, Pt, RGBColor


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "thesis_project_technology.docx"

SECTION_HEADING = "Project Technology"

INTRO_PARAGRAPH = (
    "This section critically discusses the technologies considered and chosen for "
    "the Cross-Jurisdictional Privacy Compliance Analyzer, together with the "
    "challenges encountered during implementation. Each table justifies its "
    "selections against the alternatives weighed and identifies the most "
    "significant limitation of every choice."
)

# (heading, [(name, description)])
CATEGORIES = [
    (
        "Programming and Scripting Languages",
        [
            ("Python 3.14",
             "Backend pipeline, ML, retrieval, reasoning, and Django. Selected over Node.js because the ML ecosystem is Python-first. Limitation: 3.14 lacks pre-built wheels for PyTorch."),
            ("HTML5",
             "Server-rendered pages via Django templates. Preferred over an SPA because the system is server-driven. Challenge: keeping fragments reusable across HTMX partial swaps."),
            ("CSS3",
             "Styles every page including dashboards and document viewers. Used over Bootstrap to permit a fully custom brand palette. Challenge: maintaining bespoke component classes at scale."),
            ("JavaScript (ES6)",
             "Charts, overlays, equivalency arcs, and heatmaps. Vanilla JS chosen over React/Vue to avoid a build pipeline. Cost: manual HTMX and Alpine state coordination."),
            ("SQL (SQLite, FTS5)",
             "Used through the Django ORM and for the BM25 index. Chosen because FTS5’s native BM25 outperforms Python alternatives. Challenge: brittle syntax requires defensive escaping."),
        ],
    ),
    (
        "Web Framework and Application Server",
        [
            ("Django 5",
             "Hosts the user-facing system including auth, ORM, admin, and templates. Chosen over Flask or FastAPI for mature MFA, CSRF, and ORM integration. Limitation: monolithic, with friction around async additions."),
            ("Django Channels 4",
             "Provides WebSockets for live ingestion progress. Selected because it integrates with Django’s auth and routing. Challenge: in-memory channel layer needs Redis in production."),
            ("Daphne",
             "ASGI server that runs Django plus Channels in production. Chosen over Uvicorn because it is the Channels reference implementation. Limitation: single-process, requiring an external supervisor."),
        ],
    ),
    (
        "Frontend Development",
        [
            ("HTMX 2.0",
             "Powers AJAX-style form submissions across every workspace. Chosen over React/Vue because the UI is server-driven. Challenge: hx-attribute interactions can be hard to debug."),
            ("Alpine.js 3.14",
             "Reactivity for modals, sidebar toggles, and the copilot panel. Preferred over Vue because it adds reactivity without a build step. Limitation: no type system or component model."),
            ("Chart.js 4.4",
             "Renders KPI gauges, trend lines, and coverage doughnuts. Selected over D3 because the chart types are standard and Chart.js is CSP-friendly. Challenge: default styling clashed with the brand palette."),
            ("Custom Canvas / SVG",
             "Powers the equivalency arc, coverage heatmap, and document term overlays. Hand-authored because no library expresses asymmetric compliance semantics. Risk: regressions whenever the schema changes."),
        ],
    ),
    (
        "Styling and Typography",
        [
            ("Tailwind CSS 4.2",
             "Utility-first styling across every page. Preferred over Bootstrap because the brand identity could not survive an opinionated component library. Cost: an npm build step in an otherwise Python project."),
            ("Satoshi (Fontshare)",
             "Global typeface loaded from CDN. Chosen over Inter for a more editorial feel suited to a legal tool. Challenge: external CDN dependency requiring CSP allowlist."),
        ],
    ),
    (
        "Database and Storage",
        [
            ("SQLite 3 (Django)",
             "Persists users, MFA, audit, runs, and mappings. Preferred over PostgreSQL for zero-infra thesis demonstration. Limitation: not suitable for high-concurrency production."),
            ("ChromaDB",
             "Stores embedding vectors for every regulatory and policy chunk. Selected over Pinecone or Weaviate because regulatory text cannot leave the organisation. Challenge: required a no-op embedding wrapper."),
            ("SQLite FTS5 (BM25)",
             "Lexical index for hybrid retrieval. Chosen over rank-bm25 for persistence and metadata pushdown, lifting hit-rate@5 from 0.875 to 0.95. Challenge: unforgiving syntax."),
            ("Django ORM",
             "Models every relational entity. Chosen over raw SQL for migrations and admin generation. Limitation: complex analytics required Subquery and annotate constructs."),
        ],
    ),
    (
        "AI and Machine Learning Models",
        [
            ("BAAI/bge-small-en-v1.5",
             "Dense embeddings for every chunk and query. Chosen over bge-large for CPU compatibility at ~370 MB. Limitation: 512-token window forced strict chunk budgeting and a parent–child hierarchy."),
            ("ms-marco-MiniLM-L-6-v2",
             "Cross-encoder reranker after hybrid search. Preferred over bge-reranker-large because it outperformed it at one-tenth the size. Challenge: even MiniLM adds CPU latency."),
            ("nli-deberta-v3-base",
             "NLI verifier for hallucination detection on every cited claim. Chosen over rule-based matching to capture paraphrase. Trade-off: 700 MB lazy-loaded model adds cold-start latency."),
            ("Docling",
             "Converts regulatory PDFs and DOCX to structured Markdown preserving layout. Selected over raw PyMuPDF because legal citations require structure. Challenge: an ONNX memory leak forced per-file subprocess isolation."),
        ],
    ),
    (
        "Retrieval and Document Processing",
        [
            ("LangChain Text Splitters",
             "Header-aware Markdown splitter with token-budget recursive fallback. Chosen over fixed-size chunking because legal text has explicit hierarchy. Challenge: some regulations deviate from standard headers."),
            ("tiktoken",
             "Counts tokens against the embedder’s 512-token budget. Chosen over native WordPiece for CPU speed; approximates within 10–20 per cent. Limitation: that gap forced sub-budget chunking."),
            ("Reciprocal Rank Fusion",
             "Merges dense-vector and BM25 lists. Selected over weighted-score fusion because it is parameter-free across very different score distributions. Limitation: cannot weight one source higher."),
        ],
    ),
    (
        "LLM Runtime and Reasoning Workflows",
        [
            ("OpenRouter (Claude Haiku 4.5)",
             "Primary LLM for comparison, mapping, and gap-analysis workflows. Chosen over a direct vendor SDK for vendor/model swappability via an OpenAI-compatible endpoint. Limitation: third-party network hop on every call."),
            ("Ollama (llama3.2:1b)",
             "Automatic local fallback when OpenRouter fails. Chosen for offline operation that a banking client demands. Trade-off: 1B parameters means lower-quality output in degraded mode."),
            ("LangGraph",
             "Orchestrates Prepare → Draft → Verify → Correct → Finalize as a state machine. Selected over LangChain agents for transparent, auditable steps. Challenge: steeper learning curve than a sequential pipeline."),
            ("LangChain + Pydantic v2",
             "Provides prompt templates, output parsers (OutputFixingParser), and schema-strict validation of LLM JSON. Chosen because hand-rolling these is fragile. Limitation: ecosystem churn forced version pinning."),
        ],
    ),
    (
        "Authentication, Security, and Compliance",
        [
            ("django.contrib.auth",
             "User model, password hashing, and decorators. Chosen over Auth0 or Okta because regulatory data must stay in-org. Limitation: minimal default model required a custom profile for roles and audit metadata."),
            ("django-otp + two-factor",
             "Mandatory TOTP MFA including the admin panel, with qrcode for enrolment. Chosen over SMS due to SIM-swap risk. Challenge: enrolment enforced via custom middleware."),
            ("django-axes",
             "Locks accounts after five failed attempts. Selected over a hand-rolled solution for backend integration and admin unlock UI. Trade-off: shared-NAT users can be denied service."),
            ("django-csp",
             "Strict CSP header allowlisting only used CDNs. Preferred over output escaping alone for defence-in-depth. Challenge: Alpine.js requires unsafe-inline and unsafe-eval, permitted carefully."),
            ("WhiteNoise + Custom Middleware",
             "Hashed static-file serving, idle timeout, force password change, and optional geofence. Chosen because no off-the-shelf package combined these with audit-log integration. Challenge: middleware ordering is fragile."),
        ],
    ),
    (
        "Development Environment, Tooling, and Evaluation",
        [
            ("pip + requirements.txt",
             "Python package management at project root. Preferred over Poetry or uv for examiner familiarity. Limitation: does not lock transitive versions by default."),
            ("Python venv (.venv)",
             "Isolates ML dependencies via Windows Scripts/Activate.ps1. Chosen because PyTorch and Transformers are version-sensitive enough to justify isolation. Limitation: Windows layout differs from POSIX bin/."),
            ("Git + GitHub",
             "Version control on a private GitHub remote. Universal expectation for a software-engineering thesis. Limitation: no GitHub Actions CI yet, so all testing is manual."),
            ("npm (Tailwind only)",
             "Runs the Tailwind v4 CLI to compile output.css. Unavoidable once Tailwind v4 was chosen but constrained to CSS only. Limitation: extra toolchain installation step."),
            ("pytest + RAGAS",
             "pytest for unit and smoke tests; RAGAS for LLM-as-judge faithfulness and relevancy. Chosen because no labelled cross-jurisdictional ground truth exists. Limitation: RAGAS reflects judge-model bias."),
            ("Custom Retrieval Eval + HF Cache",
             "Custom hit-rate@k, MRR, and citation harness over 24 queries; HF cache redirected to a D: drive folder. Built because no benchmark covers PDPL, DPDPA, and DPPR jointly. Limitation: small, developer-authored test set."),
        ],
    ),
]


CHALLENGES_HEADING = "Cross-Cutting Implementation Challenges"

CHALLENGES_PARAGRAPH = (
    "Several challenges spanned multiple components of the system. The toolchain "
    "is Windows-first, which limits portability without WSL adaptation. First-run "
    "setup requires roughly 5.5 GB of dependencies and model weights, slowing the "
    "on-ramp for examiners. There is no continuous-integration pipeline, so all "
    "testing is currently manual and is flagged as future work. LLM determinism is "
    "bounded by capping temperature at 0.3 and grounding every claim in citations "
    "verified by an NLI entailment step, since residual non-determinism is "
    "unavoidable. Python 3.14 is bleeding-edge, with some ML wheels (notably "
    "PyTorch) unavailable as pre-built binaries at development time. Finally, both "
    "RAGAS and the custom retrieval harness rely on developer-authored test sets, "
    "so any scaling claim should be supplemented with reviewer-validated evaluation."
)


def _set_cell_borders(cell) -> None:
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        border = OxmlElement(f"w:{edge}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:color"), "808080")
        tc_borders.append(border)
    tc_pr.append(tc_borders)


def _count_table_words() -> int:
    total = 0
    for _, rows in CATEGORIES:
        for _, desc in rows:
            total += len(desc.split())
    return total


def build_document() -> Document:
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    doc.add_heading(SECTION_HEADING, level=1)
    intro = doc.add_paragraph(INTRO_PARAGRAPH)
    intro.paragraph_format.space_after = Pt(12)

    table_number = 1

    for heading, rows in CATEGORIES:
        doc.add_heading(heading, level=2)

        table = doc.add_table(rows=len(rows), cols=3)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False

        col_widths = [Cm(2.0), Cm(4.5), Cm(11.0)]
        for row in table.rows:
            for idx, cell in enumerate(row.cells):
                cell.width = col_widths[idx]

        for row_idx, (tech_name, description) in enumerate(rows):
            row = table.rows[row_idx]
            logo_cell, name_cell, desc_cell = row.cells

            for cell in (logo_cell, name_cell, desc_cell):
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                _set_cell_borders(cell)

            logo_para = logo_cell.paragraphs[0]
            logo_run = logo_para.add_run("[logo]")
            logo_run.italic = True
            logo_run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
            logo_run.font.size = Pt(9)

            name_para = name_cell.paragraphs[0]
            name_run = name_para.add_run(tech_name)
            name_run.bold = True

            desc_para = desc_cell.paragraphs[0]
            desc_para.add_run(description)

        caption = doc.add_paragraph()
        caption.paragraph_format.space_before = Pt(6)
        caption.paragraph_format.space_after = Pt(18)
        caption_run = caption.add_run(
            f"Table {table_number}. Project Technology - {heading}"
        )
        caption_run.italic = True
        caption_run.font.size = Pt(10)

        table_number += 1

    doc.add_heading(CHALLENGES_HEADING, level=2)
    doc.add_paragraph(CHALLENGES_PARAGRAPH)

    return doc


def main() -> None:
    word_count = _count_table_words()
    print(f"Total words across all table description cells: {word_count}")
    doc = build_document()
    doc.save(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
