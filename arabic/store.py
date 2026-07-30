"""Isolated Chroma collection for Arabic chunks.

Lives in the SAME on-disk store as the main index (config.CHROMA_DIR) but in a
separate collection, "regulations_ar", so the 1024-dim bge-m3 vectors never
collide with the main 384-dim bge-small-en collection. Nothing here touches the
English pipeline.

Note: run ingestion when the Django dev server isn't also writing — Chroma's
SQLite backend can lock if two processes write the same directory at once.
Reads are fine concurrently.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import CHROMA_DIR

import chromadb

COLLECTION = "regulations_ar"

_client: "chromadb.PersistentClient | None" = None


def _get_client() -> "chromadb.PersistentClient":
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def _collection():
    return _get_client().get_or_create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"},
    )


def _scalar_meta(meta: dict) -> dict:
    """Chroma metadata must be str/int/float/bool. Coerce None -> "" and any
    other type -> str, mirroring the main indexer's sanitizer."""
    out = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif v is None:
            out[k] = ""
        else:
            out[k] = str(v)
    return out


def delete_source(source: str) -> None:
    """Remove a document's chunks before re-ingesting it — Chroma upsert only
    overwrites by id, so shifted chunk boundaries would otherwise leave orphans
    (the exact bug we hit on the English side)."""
    if not source:
        return
    try:
        _collection().delete(where={"source": source})
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup
        print(f"[arabic.store] delete_source({source!r}) note: {exc}")


def add(ids, embeddings, documents, metadatas) -> None:
    _collection().upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=[_scalar_meta(m) for m in metadatas],
    )


def query(embedding, k: int = 5, source: str | None = None) -> list[dict]:
    """Return the top-k nearest chunks as flat dicts (metadata + text + score)."""
    where = {"source": source} if source else None
    res = _collection().query(
        query_embeddings=[embedding], n_results=k, where=where,
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append({**meta, "text": doc, "score": 1.0 - float(dist)})
    return hits


def get_chunks(source: str) -> list[dict]:
    """Return all chunks for a document, in article order — for the doc viewer."""
    if not source:
        return []
    res = _collection().get(where={"source": source}, include=["documents", "metadatas"])
    rows = [{**m, "text": d} for d, m in zip(res.get("documents", []), res.get("metadatas", []))]
    rows.sort(key=lambda r: (r.get("article_number") if isinstance(r.get("article_number"), int) else 9999))
    return rows


def count(source: str | None = None) -> int:
    try:
        if source:
            return len(_collection().get(where={"source": source}).get("ids", []))
        return _collection().count()
    except Exception:
        return 0
