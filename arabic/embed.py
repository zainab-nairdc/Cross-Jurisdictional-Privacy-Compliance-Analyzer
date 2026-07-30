"""Embeddings via Ollama's bge-m3 (multilingual, 1024-dim).

We use Ollama rather than sentence-transformers so there's no 2.3 GB
HuggingFace download — the `bge-m3` model is already pulled locally, and this
keeps the whole Arabic stack (embed + answer) on one local runtime with no API
keys. Same model family the sandbox validated for cross-lingual retrieval, so
an English query still finds Arabic chunks.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import OLLAMA_URL

import ollama

MODEL = "bge-m3"

_client: "ollama.Client | None" = None


def _get_client() -> "ollama.Client":
    global _client
    if _client is None:
        _client = ollama.Client(host=OLLAMA_URL)
    return _client


def _embed_one(text: str) -> list[float]:
    """Single embedding. Handles both the newer `embed` and older `embeddings`
    Ollama client APIs so it works across versions."""
    client = _get_client()
    text = text if text.strip() else " "
    try:
        r = client.embed(model=MODEL, input=text)
        # newer client returns {"embeddings": [[...]]}
        return list(r["embeddings"][0])
    except (AttributeError, KeyError, TypeError):
        r = client.embeddings(model=MODEL, prompt=text)
        return list(r["embedding"])


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of documents. Serial calls — fine for the small corpora
    (tens to low-hundreds of chunks) this pipeline handles."""
    return [_embed_one(t) for t in texts]


def embed_query(query: str) -> list[float]:
    """bge-m3 is symmetric enough that queries and documents use the same
    encoding — no separate query instruction prefix (unlike bge-small-en)."""
    return _embed_one(query)


if __name__ == "__main__":
    v = embed_query("ما هي العقوبات؟")
    print("dim:", len(v), "| first 5:", [round(x, 4) for x in v[:5]])
