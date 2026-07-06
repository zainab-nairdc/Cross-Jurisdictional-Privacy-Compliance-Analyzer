"""Dump chunks to JSONL for human inspection.

Runs the chunker on one markdown file (or every markdown under data/processed)
and writes the resulting chunks — including content, refs, parent-child links,
and token counts — to a JSONL file under data/chunks_inspect/.

Usage:
    # one file
    .venv\\Scripts\\python.exe -m scripts.dump_chunks data/processed/bahrain/Bahrain_PDPL_Law_30_2018.md

    # everything in data/processed
    .venv\\Scripts\\python.exe -m scripts.dump_chunks --all
"""
import sys
import json
import argparse
import tiktoken
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from ingestion.chunker import chunk_document

_tokenizer = tiktoken.get_encoding("cl100k_base")
def _count_tokens(text: str) -> int:
    return len(_tokenizer.encode(text))

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
OUTPUT_DIR    = Path(__file__).resolve().parent.parent / "data" / "chunks_inspect"


def _stub_meta(md_path: Path) -> dict:
    """Best-guess metadata from the file's location under data/processed/<jur>/."""
    parts = md_path.parts
    jur = parts[-2] if len(parts) >= 2 else "Unknown"
    is_policy = jur.lower() == "bbk"
    return {
        "Document Title":            md_path.stem,
        "Regulation Name + Version": md_path.stem,
        "Document Type":             "Internal Policy" if is_policy else "Law",
        "Jurisdiction":              jur.capitalize(),
        "Issuing Authority":         "",
        "Effective Date":            "",
        "Publication Date":          "",
        "Last Updated":              "",
        "Language":                  "English",
        "Scope Summary":             "",
        "Source URL":                "",
    }


def dump_one(md_path: Path) -> Path:
    text   = md_path.read_text(encoding="utf-8")
    meta   = _stub_meta(md_path)
    chunks = chunk_document(text, meta)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{md_path.stem}.chunks.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            row = {**c, "tokens": _count_tokens(c["content"])}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    parents = sum(1 for c in chunks if c["chunk_total"] == -1)
    leaves  = len(chunks) - parents
    over_budget = sum(1 for c in chunks if _count_tokens(c["content"]) > 512)
    print(
        f"  {md_path.name:60} -> {len(chunks):4} chunks "
        f"(parents={parents:3}, leaves={leaves:4}, >512 tok={over_budget})"
    )
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="markdown file to dump")
    ap.add_argument("--all", action="store_true", help="dump every .md under data/processed")
    args = ap.parse_args()

    if args.all:
        files = sorted(PROCESSED_DIR.rglob("*.md"))
        print(f"Dumping {len(files)} markdown files -> {OUTPUT_DIR}\n")
        for f in files:
            dump_one(f)
    elif args.path:
        out = dump_one(Path(args.path))
        print(f"\nWrote: {out}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
