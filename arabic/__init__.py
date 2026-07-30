"""Isolated Arabic-language RAG pipeline for CJPCA.

Kept deliberately separate from the main English pipeline (ingestion/,
retrieval/): Arabic needs a multilingual embedder (bge-m3, 1024-dim) which is
dimension-incompatible with the main bge-small-en (384-dim) Chroma collection.
So this package writes to its OWN Chroma collection ("regulations_ar") and
reuses only shared infrastructure: config.CHROMA_DIR, config.OLLAMA_URL, and
the local Ollama models (bge-m3 for embeddings, qwen2.5:7b for answers).

Flow:  extract (PyMuPDF) -> normalize -> chunk (article/definition) ->
       embed (bge-m3 via Ollama) -> store (Chroma) -> query (English in,
       Arabic retrieved, English answer out with article citations).
"""
