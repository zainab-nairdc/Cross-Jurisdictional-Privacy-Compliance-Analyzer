# Cross-Jurisdictional Privacy Compliance Analyzer — PoC

An AI-assisted compliance analysis platform that ingests privacy / data-protection
regulations from multiple jurisdictions (Bahrain, India, Kuwait) plus internal
policies, and helps legal / compliance teams **compare regulations**, **map
policies to obligations**, **identify gaps**, and **generate draft reports** —
all grounded in retrieved source text with citations.

This proof-of-concept is scoped to the feasibility document: plain
username / password login (no role-based access, no MFA), running **fully local
against [Ollama](https://ollama.com)** — no API keys or internet required.

---

## Features
- **Multi-jurisdiction ingestion** — regulations + internal policies, chunked and indexed
- **Regulation-to-regulation comparison** with side-by-side citations
- **Policy → obligation mapping** with coverage indicators (Covered / Partial / Requires Review / Not Covered)
- **Gap analysis & reporting** with exportable reports (PDF / Excel)
- **Reviewer validation workflow** (Draft → Reviewed → Approved) with audit trail
- **Copilot** — grounded Q&A over the indexed corpus
- **Analytics** and **History / Audit** dashboards

## Architecture
| Layer | Tech |
|-------|------|
| **Retrieval** | Hybrid search — ChromaDB (dense vectors) + SQLite FTS5 (BM25 keyword), reranked |
| **Reasoning** | LangChain / LangGraph structured workflows. **Ollama `llama3.2:1b` is the primary LLM** (OpenRouter used only if `OPENROUTER_API_KEY` is set) |
| **Embeddings** | `BAAI/bge-small-en-v1.5` (downloaded on first run) |
| **Web app** | Django 5 + HTMX + Tailwind, Django Channels |

---

## Prerequisites
- **Python 3.12–3.14**
- **[Ollama](https://ollama.com/download)** (for the local LLM)
- **Node.js** (only if you want to recompile Tailwind CSS; a prebuilt `output.css` is committed)
- ~8 GB free disk (PyTorch, models, vector store)

---

## Setup — from scratch to running

> Commands below are **Windows PowerShell**. On macOS / Linux, swap
> `.venv\Scripts\activate` for `source .venv/bin/activate`.

### 1. Clone
```powershell
git clone https://github.com/zainabintech/cjpca-poc.git
cd cjpca-poc
```

### 2. Create & activate a virtual environment
```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

### 3. Install Python dependencies
```powershell
# Django web app
pip install -r cjpca\requirements.txt

# RAG pipeline (vector store, embeddings, PyTorch, parsers, reporting)
pip install torch chromadb llama-index-core llama-index-vector-stores-chroma `
            llama-index-embeddings-huggingface sentence-transformers rank-bm25 `
            langchain-text-splitters tiktoken pymupdf python-docx beautifulsoup4 `
            pandas openpyxl reportlab pydantic-settings python-dotenv

# LangChain integrations used by the reasoning + indexing layers
pip install langchain-classic langchain-chroma langchain-community langchain-huggingface
```

### 4. Install and start Ollama, then pull the model
Install Ollama from https://ollama.com/download (or `winget install Ollama.Ollama`).
It runs as a background service on `http://localhost:11434`. Then:
```powershell
ollama pull llama3.2:1b
```

### 5. Environment file (optional)
```powershell
copy .env.example .env
```
No key is needed — the app runs on local Ollama. (To add OpenRouter as a cloud
fallback, uncomment `OPENROUTER_API_KEY` in `.env` and set a real key.)

### 6. Create the database
```powershell
cd cjpca
python manage.py migrate
```

### 7. Ingest the bundled corpus into ChromaDB + BM25
```powershell
python manage.py full_ingest --apply --skip-convert
```
This reads the pre-converted markdown in `data/processed/`, chunks, embeds, and
indexes all 43 documents (~1,200 chunks). First run downloads the embedding
model (~130 MB). Takes a few minutes on CPU.
> `--skip-convert` avoids needing `docling`. Install `docling` only if you want
> to ingest brand-new PDFs / DOCX from scratch.

### 8. Create a login
```powershell
python manage.py createsuperuser
```
(Every logged-in user has full access — there are no roles in this PoC.)

### 9. Run the server
```powershell
python manage.py runserver
```
Open **http://127.0.0.1:8000** and sign in.

---

## Using the system (end-to-end workflow)
1. **Library → Regulations / Internal Policies** — confirm the corpus is indexed (upload more docs here if needed).
2. **Comparison** — pick Regulation A vs Regulation B (e.g. Bahrain PDPL vs India DPDP), run it, and review the side-by-side obligations with citations.
3. **Policy Mapping** — pick an internal policy, map it against a regulation's obligations, and inspect coverage + gaps.
4. **Review & Validate** — accept / reject / modify the generated mappings (Draft → Reviewed → Approved); every action is recorded in the audit trail.
5. **Gap Analysis & Reporting** — review the gap register and export a report (PDF / Excel).
6. **Copilot** — ask grounded questions about the indexed corpus.
7. **Analytics / History** — dashboards and the full audit log.

---

## Notes & troubleshooting
- **Ollama is the primary LLM.** If a response is slow, that's the 1B model running on CPU; you can pull a larger model (e.g. `ollama pull llama3.2:3b`) and set `fallback_model` in `reasoning/config.py`.
- **`ModuleNotFoundError: langchain_chroma`** → you missed the `langchain-chroma` install in step 3.
- **`Docling not installed`** → make sure you passed `--skip-convert` (step 7); the bundled markdown doesn't need docling.
- **Gitignored / rebuilt per machine:** `.env`, `.venv/`, `node_modules/`, `chroma_data/`, `hf_cache/`, `db.sqlite3`. Everyone clones and runs steps 2–8 to rebuild them.
- **(Optional) recompile Tailwind:** `cd cjpca && npm install && npx tailwindcss -i static/css/tailwind.css -o static/css/output.css`
