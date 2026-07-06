"""generate synthetic q-a pairs for retrieval evaluation.

approach: sample chunks (stratified by jurisdiction so every regulation
gets covered), feed each one to ollama with a prompt that asks for one
question an analyst would ask to find that exact text. write to
tests/synthetic_qa.json so eval_retrievers.py can pick it up.

each entry has the question, the chunk_id it was generated from (used as
the ground-truth target during eval), the jurisdiction, and a snippet of
the source text for debugging.

run from project root:
    .venv\\Scripts\\python.exe -X utf8 -m scripts.generate_eval_dataset
    .venv\\Scripts\\python.exe -X utf8 -m scripts.generate_eval_dataset --n 60
    .venv\\Scripts\\python.exe -X utf8 -m scripts.generate_eval_dataset --model llama3.2:1b
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CHUNKS_DIR  = ROOT / "data" / "chunks_inspect"
OUTPUT_PATH = ROOT / "tests" / "synthetic_qa.json"

OLLAMA_URL   = "http://localhost:11434"

# the prompt was tuned to keep llama3.2 from drifting into preamble or
# multi-question output. one short question, no quotes, no rephrasing.
_PROMPT_TEMPLATE = """You are helping build a retrieval test set for legal compliance documents.

Given the following text, write ONE specific question that a compliance analyst would ask to find this exact passage. The question must:
- be answerable using only this text
- mention concrete subjects from the text (named law / article number / specific obligation)
- be 8 to 20 words long
- end with a question mark
- contain NO quotes, NO bullets, NO preamble like "Here is your question"

TEXT:
\"\"\"
{content}
\"\"\"

Question:"""


def _load_eligible_chunks() -> list[dict]:
    """walk chunks_inspect, return leaf chunks (skip parents) with enough text."""
    chunks: list[dict] = []
    for f in sorted(CHUNKS_DIR.glob("*.chunks.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("embed_skip"):
                continue
            content = row.get("content", "").strip()
            if len(content) < 200:    # skip tiny chunks — questions get vague
                continue
            chunks.append(row)
    return chunks


def _stratified_sample(chunks: list[dict], n: int, seed: int = 42) -> list[dict]:
    """sample n chunks but keep all four jurisdictions represented."""
    by_jur: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        by_jur[c.get("jurisdiction", "Unknown")].append(c)

    rng = random.Random(seed)
    quota = max(1, n // max(len(by_jur), 1))
    picked: list[dict] = []
    for jur, group in by_jur.items():
        rng.shuffle(group)
        picked.extend(group[:quota])

    # fill remainder by random across whatever's left
    rest = [c for c in chunks if c not in picked]
    rng.shuffle(rest)
    picked.extend(rest[: max(0, n - len(picked))])
    return picked[:n]


def _ask_ollama(prompt: str, model: str, timeout: int = 60) -> str:
    """one-shot ollama call. returns the model's text or '' on failure."""
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.4,    # mild variety, mostly faithful
                    "num_predict": 80,     # questions are short
                },
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        return f"__ERROR__ {e}"


def _clean_question(text: str) -> str:
    """strip quotes, leading bullets, and llama's occasional preamble."""
    text = text.strip()
    # drop any leading "Question:" / "Here's a question:" etc
    for pre in ("Question:", "Here is", "Here's", "A:", "Q:"):
        if text.lower().startswith(pre.lower()):
            text = text[len(pre):].lstrip(": -")
    # strip surrounding quotes
    text = text.strip('"\'').strip()
    # collapse multi-line into the first line (in case the model added a rationale)
    text = text.split("\n", 1)[0].strip()
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n",     type=int, default=30, help="how many q-a pairs to generate")
    ap.add_argument("--model", default="llama3.2:latest", help="ollama model name")
    ap.add_argument("--seed",  type=int, default=42)
    args = ap.parse_args()

    print("=" * 70)
    print(f"  generating {args.n} synthetic q-a pairs via ollama ({args.model})")
    print("=" * 70)

    all_chunks = _load_eligible_chunks()
    print(f"\n  eligible chunks: {len(all_chunks)}")
    sample = _stratified_sample(all_chunks, args.n, seed=args.seed)
    by_jur: dict[str, int] = defaultdict(int)
    for c in sample:
        by_jur[c.get("jurisdiction", "?")] += 1
    print(f"  sampled {len(sample)} (jurisdiction mix: {dict(by_jur)})")

    out: list[dict] = []
    t0 = time.time()
    for i, c in enumerate(sample, 1):
        prompt = _PROMPT_TEMPLATE.format(content=c["content"][:1200])
        raw    = _ask_ollama(prompt, args.model)
        if raw.startswith("__ERROR__"):
            print(f"  [{i:3}/{len(sample)}] ERR: {raw}")
            continue
        question = _clean_question(raw)
        if not question.endswith("?") or len(question) < 20:
            print(f"  [{i:3}/{len(sample)}] SKIP malformed: {question[:60]!r}")
            continue
        out.append({
            "query":             question,
            "expected_chunk_id": c["chunk_id"],
            "expected_node_id":  c["node_id"],
            "jurisdiction":      c.get("jurisdiction", ""),
            "doc_title":         c.get("doc_title", ""),
            "snippet":           c["content"][:120].strip(),
        })
        elapsed = time.time() - t0
        rate    = (i / elapsed) if elapsed else 0
        print(f"  [{i:3}/{len(sample)}] {c.get('jurisdiction','?'):8}  {question[:80]}  ({rate:.1f}/s)")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 70)
    print(f"  wrote {len(out)} pairs to {OUTPUT_PATH}")
    print(f"  total time: {time.time() - t0:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
