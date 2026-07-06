"""turns chunks into vectors using bge.

the trick here: we don't just embed the raw text. we glue a little legal
context on top first — the jurisdiction and the citation path. that way
the same word "consent" in bahrain's pdpl and india's dpdp end up as
different vectors, which is exactly what we want.

documents go through this file. queries get a different prefix and that
lives in retriever.py — not here.
"""
import os
import sys
import torch
from pathlib import Path
from sentence_transformers import SentenceTransformer

# the dev laptop has 4 physical cores. 4 threads gives the best embedding
# speed without starving anything else running on the box.
torch.set_num_threads(4)

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import EMBED_MODEL


_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """load the bge model once, then hand back the same instance every time.
    loading it from disk takes a few seconds, so we definitely don't want
    to do it per document."""
    global _model
    if _model is None:
        print(f"Loading embedding model: {EMBED_MODEL}")
        _model = SentenceTransformer(EMBED_MODEL, cache_folder=os.environ.get("HF_HOME"))
        print("  Model loaded.")
    return _model


def embed_text(chunk: dict) -> str:
    """build the actual string we'll feed to the embedder.

    it looks like this:

        Jurisdiction: Bahrain
        Citation: PDPA Ministerial Order 43/2022 > Article (4)

        {the chunk body goes here}

    the labels tell the embedder "this is the country, this is the citation,
    this is the content" — really helpful since legal text talks about itself
    a lot.

    if the citation path is missing (rare, only happens for unstructured
    docs), we fall back to whatever we have. if jurisdiction is missing,
    we use "Unknown" rather than dropping the prefix — keeping the prefix
    shape consistent matters more than having a perfect value.
    """
    juris   = chunk.get("jurisdiction", "").strip() or "Unknown"
    citation = (
        chunk.get("hierarchy_path", "").strip()
        or chunk.get("article_ref", "").strip()
        or chunk.get("section_title", "").strip()
        or chunk.get("doc_title", "").strip()
        or "(uncited)"
    )
    content = chunk.get("content", "").strip()
    return (
        f"Jurisdiction: {juris}\n"
        f"Citation: {citation}\n\n"
        f"{content}"
    )


def embed_chunks(chunks: list[dict], st_model: SentenceTransformer) -> list[list[float]]:
    """take a batch of chunks, return one vector per chunk.
    the vectors are length-1 (normalized), so cosine similarity is just a
    dot product downstream."""
    if not chunks:
        return []
    texts = [embed_text(c) for c in chunks]
    embeddings = st_model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return [e.tolist() for e in embeddings]
