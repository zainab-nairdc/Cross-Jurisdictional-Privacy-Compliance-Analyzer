"""End-to-end smoke test for the new LangChain-Chroma indexer.

Picks one already-processed markdown file (so we skip Docling), runs it through
chunker -> embedder -> indexer, then queries Chroma directly to verify the
chunks landed with correct metadata.

Run from project root:
    .venv\\Scripts\\python.exe -m tests.smoke_indexer
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import METADATA_FILE
from ingestion.chunker  import chunk_document
from ingestion.embedder import get_model, embed_chunks
from ingestion.indexer  import get_vectorstore, index_chunks


TARGET_MD = ROOT / "data" / "processed" / "bahrain" / \
            "Bahrain_PDPA_Order_43_2022_Technical_Organisational_Measures.md"


def _load_meta(stem: str) -> dict:
    df = pd.read_csv(METADATA_FILE, dtype=str).fillna("")
    row = df[df["Document Title"].str.strip().str.lower() == stem.lower()]
    if row.empty:
        raise SystemExit(f"no metadata row for {stem}")
    return row.iloc[0].to_dict()


def main() -> None:
    print("=" * 60)
    print("  SMOKE TEST: indexer.py (LangChain-Chroma wrapper)")
    print("=" * 60)

    assert TARGET_MD.exists(), f"missing: {TARGET_MD}"
    text = TARGET_MD.read_text(encoding="utf-8")
    meta = _load_meta(TARGET_MD.stem)
    print(f"\n[1/5] loaded {TARGET_MD.name} ({len(text):,} chars)")
    print(f"      jurisdiction={meta['Jurisdiction']!r}, doc_type={meta['Document Type']!r}")

    chunks = chunk_document(text, meta)
    leaves  = [c for c in chunks if not c.get("embed_skip", False)]
    parents = [c for c in chunks if c.get("embed_skip", False)]
    print(f"\n[2/5] chunked: {len(leaves)} leaves, {len(parents)} parents")
    assert leaves, "chunker returned zero leaves"

    sample = leaves[0]
    for k in ("node_id", "chunk_id", "content", "jurisdiction", "hierarchy_path"):
        assert k in sample, f"chunk missing key: {k}"
    print(f"      sample chunk_id   = {sample['chunk_id']}")
    print(f"      sample hierarchy  = {sample['hierarchy_path']}")

    print(f"\n[3/5] embedding {len(leaves)} leaves...")
    model = get_model()
    embeddings = embed_chunks(leaves, model)
    assert len(embeddings) == len(leaves)
    assert len(embeddings[0]) == 384, f"BGE-small should yield 384-dim, got {len(embeddings[0])}"
    print(f"      vector dim = {len(embeddings[0])}, count = {len(embeddings)}")

    print("\n[4/5] indexing into ChromaDB...")
    vs = get_vectorstore()
    before = vs._collection.count()
    index_chunks(leaves, embeddings)
    after = vs._collection.count()
    print(f"      collection count: {before} -> {after}")

    print("\n[5/5] verifying round-trip via Chroma .get() ...")
    fetched = vs._collection.get(
        ids=[leaves[0]["node_id"]],
        include=["documents", "metadatas", "embeddings"],
    )
    assert fetched["ids"], "round-trip fetch returned no ids"
    md = fetched["metadatas"][0]
    print(f"      fetched id          = {fetched['ids'][0]}")
    print(f"      fetched document    = {fetched['documents'][0][:80]!r}...")
    print(f"      fetched jurisdiction= {md.get('jurisdiction')!r}")
    print(f"      fetched chunk_type  = {md.get('chunk_type')!r}")
    print(f"      fetched embed dim   = {len(fetched['embeddings'][0])}")

    assert md.get("jurisdiction") == "Bahrain", "jurisdiction did not round-trip"

    print("\n" + "=" * 60)
    print("  SMOKE TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
