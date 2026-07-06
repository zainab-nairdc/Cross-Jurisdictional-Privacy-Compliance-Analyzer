import os
from pathlib import Path

# Redirect HuggingFace model cache. Defaults to <project_root>/hf_cache so it
# works cross-platform; override by setting HF_HOME in the environment before
# launching (e.g. point it at a fast drive: HF_HOME=D:\hf_cache).
_default_hf_cache = str(Path(__file__).resolve().parent / "hf_cache")
os.environ.setdefault("HF_HOME",            _default_hf_cache)
os.environ.setdefault("TRANSFORMERS_CACHE", str(Path(_default_hf_cache) / "transformers"))


# paths  
BASE_DIR   = Path(__file__).resolve().parent # project root 
DATA_DIR   = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_data"

REGULATION_DIRS = {
    "bahrain": DATA_DIR / "regulations" / "bahrain",
    "india":   DATA_DIR / "regulations" / "india",
    "kuwait":  DATA_DIR / "regulations" / "kuwait",
}

INTERNAL_POLICIES_DIR = DATA_DIR / "internal_policies"
METADATA_FILE         = DATA_DIR / "metadata.csv"

# chromadb - collection name *** maybe i should create another collection?? 
CHROMA_COLLECTION = "regulations"

# embedding model
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
# i will switch to large when GPU available

# BGE is an asymmetric embedder: queries need a different prefix than
# documents. The doc prefix is built inside ingestion/embedder.py
# (Jurisdiction/Citation/Content). The query prefix below is what the
# retriever feeds into HuggingFaceEmbedding's query_instruction so
# llamaindex applies it automatically when embedding queries.
#
# If you swap EMBED_MODEL to a non-BGE model (e.g. text-embedding-3-small),
# update this prefix too — wrong prefix = silently degraded retrieval.
EMBED_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# ollama - local llm 
OLLAMA_URL   = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:1b"

# chunking — token-based budgets enforced by tiktoken (cl100k_base) in chunker.py.
# 512 matches the bge-small-en-v1.5 max input. cl100k_base tokenizes English ~10-20%
# differently from BGE's WordPiece; lower CHUNK_TOKENS if you see truncation warnings.
CHUNK_TOKENS         = 512
CHUNK_OVERLAP_TOKENS = 60

# jurisdiction name normalisation — single source of truth used by retriever
# and bm25_store. add new jurisdictions here only; no other file needs updating.
JURISDICTION_NORM: dict[str, str] = {
    "bahrain": "Bahrain",
    "india":   "India",
    "kuwait":  "Kuwait",
    # ingestion stores BBK chunks with jurisdiction='Bbk' (titlecase). the
    # retriever filter has to match that literal, otherwise hybrid_search
    # with jurisdiction='BBK' returns zero rows even when 147 policy
    # chunks exist in the index.
    "bbk":     "Bbk",
}