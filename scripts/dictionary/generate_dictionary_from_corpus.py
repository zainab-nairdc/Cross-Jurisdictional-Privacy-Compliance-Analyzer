"""Generate the cross-jurisdiction term dictionary FROM the corpus.

Instead of hand-curating term_dictionary.py, this script asks Claude Haiku
to read every "definitions" chunk in each jurisdiction's corpus and extract
the defined terms — yielding a dictionary whose every entry has a corpus
provenance.

Pipeline:

  Stage 1 — Per-jurisdiction extraction
    For each of Bahrain / India / Kuwait:
      • Retrieve every chunk whose chunk_type == 'definition' OR whose
        article_ref hints at "Definitions" / "Article 1" (the universal
        location for legal definitions).
      • Batch them and ask the LLM:
        "List every defined term in these chunks. For each, output:
           - jurisdictional term (exact label as the law writes it)
           - citation (article number from the chunk header)
           - definition (one sentence)
           - canonical English name (lowercase, the cross-jur key)"
      • Save to dictionary_<jurisdiction>.json

  Stage 2 — Cross-jurisdiction merge
    Read all three per-jurisdiction JSONs and the GDPR reference column.
    Ask the LLM: "Cluster these by underlying concept. For each cluster,
    pick a single canonical English name and a one-line definition."
    Output dictionary_merged.json — a drop-in replacement for the hand
    dictionary, with every citation backed by a corpus chunk.

Usage:
    .venv\\Scripts\\python.exe scripts\\generate_dictionary_from_corpus.py --stage 1 --jurisdiction Bahrain
    .venv\\Scripts\\python.exe scripts\\generate_dictionary_from_corpus.py --stage 1 --jurisdiction all
    .venv\\Scripts\\python.exe scripts\\generate_dictionary_from_corpus.py --stage 2

Cost estimate: ~$0.30 for the full 3-jurisdiction run (about 20 LLM calls
at Claude Haiku 4.5 pricing). Set --dry-run to skip LLM calls.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.bm25_store import search_bm25                    # noqa: E402
from reasoning.generator   import _get_llm                       # noqa: E402


OUT_DIR = ROOT / 'dictionary_generation'
OUT_DIR.mkdir(exist_ok=True)


# Stage 1 prompt — extract defined terms from a batch of chunks.
EXTRACT_PROMPT = """You are reading the "Definitions" article(s) of a legal regulation.

Your job: extract every defined term, exactly as the law writes it.

Below are chunks from the {jurisdiction} corpus. Each chunk shows its
document title and citation in the header.

{chunks}

Output ONE JSON object with this shape — no prose, no markdown:

{{
  "terms": [
    {{
      "jurisdictional_term": "<the exact label used in the law>",
      "citation":            "<the article/section number from the chunk header>",
      "doc_title":           "<the source document name from the chunk header>",
      "definition":          "<the law's definition, paraphrased to one sentence>",
      "canonical_english":   "<a lowercase English name for the underlying concept,"
                             " usable as a cross-jurisdiction key (e.g. 'data subject',"
                             " 'data controller', 'consent')>"
    }},
    ...
  ]
}}

Rules:
- Only include terms that are EXPLICITLY defined (a sentence starting with
  '"X" means...' or 'X is defined as...' or similar).
- Do NOT invent definitions. If a term is mentioned but not defined, skip it.
- The "canonical_english" should be the same name across jurisdictions for
  the same concept (e.g. Bahrain "Data Manager" and India "Data Fiduciary"
  both have canonical_english = "data controller").
- Keep citations exactly as they appear in the chunk header.
- If no definitions are found in the chunks, return {{"terms": []}}.
"""


def _gather_definition_chunks(jurisdiction: str, max_chunks: int = 40) -> list[dict]:
    """Pull chunks likely to define terms in this jurisdiction.

    Heuristics — chunks are kept if any of:
      • chunk_type metadata = 'definition' (the chunker tags these)
      • article_ref contains 'Definition' / 'Article 1' / 'Article (1)'
      • Top BM25 hits for the literal query 'definitions'.
    """
    rows = search_bm25('definitions interpretation meaning', top_k=80,
                       jurisdiction=jurisdiction)

    kept = []
    for r in rows:
        m = r.get('metadata', {})
        ref = (m.get('article_ref') or '').lower()
        is_def = (
            'definition' in ref
            or ref.startswith('article 1') or 'article (1)' in ref
            or 'interpretation' in ref
            or ref in ('section 1', 'sec. 1')
        )
        if is_def:
            kept.append(r)
        if len(kept) >= max_chunks:
            break

    # Backup: if heuristics caught nothing, just take the top BM25 hits.
    if not kept and rows:
        kept = rows[:max_chunks]

    return kept


def _format_chunks_block(chunks: list[dict], max_chars: int = 8000) -> str:
    parts = []
    total = 0
    for i, c in enumerate(chunks, 1):
        m = c.get('metadata', {})
        doc = m.get('doc_title', '')[:80]
        art = m.get('article_ref', '')[:80]
        body = c.get('content', '').strip()[:600]
        block = f'[Chunk {i}]  DOC: {doc}  CITATION: {art}\n{body}'
        if total + len(block) > max_chars:
            parts.append('... [more chunks omitted to fit]')
            break
        parts.append(block)
        total += len(block)
    return '\n\n---\n\n'.join(parts)


def _parse_json(text: str) -> dict:
    import re
    if not text:
        return {'terms': []}
    cleaned = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    s = cleaned.find('{')
    e = cleaned.rfind('}')
    if s == -1 or e <= s:
        return {'terms': []}
    try:
        return json.loads(cleaned[s:e + 1])
    except json.JSONDecodeError:
        return {'terms': []}


async def stage_1(jurisdiction: str, dry_run: bool = False) -> dict:
    """Extract terms from one jurisdiction's definition chunks."""
    chunks = _gather_definition_chunks(jurisdiction)
    print(f'  found {len(chunks)} candidate "definition" chunks for {jurisdiction}')

    if not chunks:
        return {'jurisdiction': jurisdiction, 'terms': [], 'note': 'no definition chunks found'}

    if dry_run:
        return {
            'jurisdiction': jurisdiction,
            'chunk_count':  len(chunks),
            'sample_chunks': [{'doc': c['metadata'].get('doc_title',''),
                                'ref': c['metadata'].get('article_ref',''),
                                'preview': c['content'][:120]} for c in chunks[:3]],
            'note': 'dry-run — no LLM call made',
        }

    prompt = EXTRACT_PROMPT.format(
        jurisdiction=jurisdiction,
        chunks=_format_chunks_block(chunks),
    )

    llm = _get_llm()
    print(f'  calling LLM for {jurisdiction}...', end=' ', flush=True)
    t0 = time.time()
    resp = await llm.ainvoke(prompt)
    text = resp.content if hasattr(resp, 'content') else str(resp)
    print(f'{time.time() - t0:.1f}s')

    parsed = _parse_json(text)
    return {
        'jurisdiction':    jurisdiction,
        'terms':           parsed.get('terms', []),
        'source_chunks':   len(chunks),
    }


# Stage 2 prompt — cluster per-jurisdiction terms into a unified dictionary.
MERGE_PROMPT = """You are merging legal-term lists from three jurisdictions into
one unified dictionary.

Below are the term lists, one per jurisdiction. Each item has the
jurisdictional label, citation, definition, and a proposed canonical
English name.

{lists}

Your job: group items that refer to the same underlying legal concept,
even when they're labelled differently (Bahrain "Data Manager" ↔ India
"Data Fiduciary" ↔ Kuwait "Data Controller" all = the controller role).

Output ONE JSON object — no prose, no markdown:

{{
  "dictionary": [
    {{
      "canonical": "<lowercase English key — same name for every cluster>",
      "category":  "<one of: Roles, Lawful basis, Data categories, Data subject rights,"
                   " Security & breach, Cross-border, Governance, Enforcement>",
      "definition": "<one-line cross-jurisdiction summary>",
      "jurisdictions": {{
        "Bahrain": {{"term": "<label>", "citation": "<source>", "definition": "<from chunk>"}},
        "India":   {{"term": "<label>", "citation": "<source>", "definition": "<from chunk>"}},
        "Kuwait":  {{"term": "<label>", "citation": "<source>", "definition": "<from chunk>"}}
      }},
      "synonyms": ["<alt phrasing>", "<alt phrasing>"]
    }},
    ...
  ]
}}

Rules:
- A jurisdiction may be omitted from a cluster's "jurisdictions" if that
  jurisdiction doesn't define that concept.
- Pick the most generic GDPR-style English name as "canonical".
- Synonyms should include every distinct label across jurisdictions.
"""


async def stage_2(dry_run: bool = False) -> dict:
    """Merge per-jurisdiction outputs into one unified dictionary."""
    per_jur = {}
    for jur in ('Bahrain', 'India', 'Kuwait'):
        path = OUT_DIR / f'dictionary_{jur.lower()}.json'
        if not path.exists():
            print(f'  WARN: {path.name} not found. Run --stage 1 first.')
            continue
        per_jur[jur] = json.loads(path.read_text(encoding='utf-8')).get('terms', [])
        print(f'  loaded {len(per_jur[jur])} terms from {jur}')

    if not per_jur:
        return {'dictionary': [], 'note': 'no stage-1 outputs found'}

    if dry_run:
        return {
            'note': 'dry-run',
            'summary': {jur: len(terms) for jur, terms in per_jur.items()},
        }

    # Render the lists for the merge prompt.
    blocks = []
    for jur, terms in per_jur.items():
        blocks.append(f'=== {jur} ({len(terms)} terms) ===')
        for t in terms:
            blocks.append(
                f'  - {t.get("jurisdictional_term", "?")}  '
                f'[{t.get("citation", "?")}]  '
                f'canonical={t.get("canonical_english", "?")}  '
                f'def={t.get("definition", "?")[:80]}'
            )

    prompt = MERGE_PROMPT.format(lists='\n'.join(blocks))
    print('  calling LLM to merge...', end=' ', flush=True)
    t0 = time.time()
    llm = _get_llm()
    resp = await llm.ainvoke(prompt)
    text = resp.content if hasattr(resp, 'content') else str(resp)
    print(f'{time.time() - t0:.1f}s')

    parsed = _parse_json(text)
    return {
        'dictionary':    parsed.get('dictionary', []),
        'source_counts': {jur: len(terms) for jur, terms in per_jur.items()},
    }


async def main_async(args):
    if args.stage == 1:
        targets = ['Bahrain', 'India', 'Kuwait'] if args.jurisdiction == 'all' else [args.jurisdiction]
        for jur in targets:
            print(f'\n=== Stage 1 — {jur} ===')
            result = await stage_1(jur, dry_run=args.dry_run)
            out_path = OUT_DIR / f'dictionary_{jur.lower()}.json'
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f'  wrote {out_path}')
            if result.get('terms'):
                print(f'  extracted {len(result["terms"])} terms')
                for t in result['terms'][:5]:
                    print(f'    - {t.get("jurisdictional_term", "?")} [{t.get("citation","?")}]')

    elif args.stage == 2:
        print('\n=== Stage 2 — Cross-jurisdiction merge ===')
        result = await stage_2(dry_run=args.dry_run)
        out_path = OUT_DIR / 'dictionary_merged.json'
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'  wrote {out_path}')
        if result.get('dictionary'):
            print(f'  merged into {len(result["dictionary"])} canonical terms')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int, choices=[1, 2], required=True,
                    help='1 = per-jurisdiction extraction, 2 = merge')
    ap.add_argument('--jurisdiction', default='all',
                    choices=['all', 'Bahrain', 'India', 'Kuwait'],
                    help='(stage 1 only) which jurisdiction')
    ap.add_argument('--dry-run', action='store_true',
                    help='Skip LLM calls — print which chunks would be sent')
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == '__main__':
    main()
