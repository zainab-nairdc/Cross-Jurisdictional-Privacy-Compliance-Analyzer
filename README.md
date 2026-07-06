# Cross-Jurisdictional Privacy Compliance Analyzer — PoC

An AI-assisted compliance analysis platform that ingests privacy/data-protection
regulations from multiple jurisdictions (Bahrain, India, Kuwait) plus internal
policies, and helps legal/compliance teams **compare regulations**, **map
policies to obligations**, **identify gaps**, and **generate draft reports** —
all grounded in retrieved source text with citations.

This is a proof-of-concept build scoped to the feasibility document: plain
username/password login (no role-based access, no MFA), running fully local
against **Ollama**.

## Features
- **Multi-jurisdiction ingestion** — regulations + internal policies, chunked and indexed
- **Regulation-to-regulation comparison** with side-by-side citations
- **Policy → obligation mapping** with coverage indicators (Covered / Partial / Requires Review / Not Covered)
- **Gap analysis & reporting** with exportable reports
- **Reviewer validation workflow** (Draft → Reviewed → Approved) with audit trail
- **Copilot** Q&A grounded in the indexed corpus
- **Analytics** and **History/Audit** dashboards

## Architecture
- **Retrieval layer** — hybrid search (ChromaDB dense + SQLite FTS5 BM25) over chunked clauses
- **Reasoning layer** — LangChain/LangGraph structured LLM workflows; **Ollama (`llama3.2:1b`) is the primary LLM** (OpenRouter used only if `OPENROUTER_API_KEY` is set)
- **Web app** — Django 5 + HTMX + Tailwind, Django Channels for ingestion progress

## Requirements
- Python 3.12–3.14, Node.js (for Tailwind), and [Ollama](https://ollama.com)

## Setup

```bash
# 1. Create a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

# 2. Install dependencies
pip install -r cjpca/requirements.txt      # Django web app
pip install -r requirements.txt            # RAG pipeline (chromadb, llama-index, torch, ...)
pip install langchain-classic langchain-chroma langchain-community langchain-huggingface

# 3. Pull the local LLM
ollama pull llama3.2:1b

# 4. (Optional) copy the env template
cp .env.example .env

# 5. Database
cd cjpca
python manage.py migrate

# 6. Ingest the bundled corpus into ChromaDB + BM25
python manage.py full_ingest --apply --skip-convert

# 7. Create a login and run the server
python manage.py createsuperuser
python manage.py runserver
```

Then open http://127.0.0.1:8000 and sign in.

## Notes
- `.env`, `.venv/`, `node_modules/`, `chroma_data/`, `hf_cache/`, and `db.sqlite3`
  are gitignored — each machine builds its own.
- The bundled `data/processed/*.md` are pre-converted document text, so a full
  ingest does **not** require `docling`. Install `docling` only if you want to
  ingest brand-new PDFs/DOCX from scratch.
