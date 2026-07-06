"""LLM-assisted verifier for the cross-jurisdiction term dictionary.

For each (term, jurisdiction) entry in reasoning/term_dictionary.py:

  1. Retrieve candidate chunks from the *entire* corpus of that jurisdiction
     (not just one doc — Kuwait has DPPR + CBK + CITRA + Cybercrime Law +
     Electronic Transactions Law, etc.; all are searched).
  2. Ask Claude Haiku 4.5 (via OpenRouter — the same LLM the rest of the
     system uses) to decide whether the dictionary's claimed citation is
     actually correct, and if not, what the real location is.
  3. Write a structured report to dictionary_verification_report.json so
     the human reviewer can decide what to apply.

This script does NOT auto-patch the dictionary. Citations are too consequential
to change without a human eye. The output is a report you read and act on.

Run from project root:
    .venv\\Scripts\\python.exe scripts\\verify_dictionary_llm.py
    .venv\\Scripts\\python.exe scripts\\verify_dictionary_llm.py --limit 10  # test on 10 first
    .venv\\Scripts\\python.exe scripts\\verify_dictionary_llm.py --only-failed
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

from reasoning.term_dictionary import TERMS                  # noqa: E402
from retrieval.retriever      import hybrid_search           # noqa: E402
from reasoning.generator      import _get_llm                # noqa: E402


# Skip the GDPR reference column — it's not in our corpus.
SKIP_JURISDICTIONS = {'GDPR_ref'}


VERIFY_PROMPT = """You are auditing a legal-citation dictionary entry.

CANONICAL TERM: {term}
DEFINITION: {definition}

CLAIMED LOCATION:
  Jurisdiction: {jurisdiction}
  Citation label: {claimed_label}
  Jurisdiction-specific term: {jur_term}

Below are candidate chunks retrieved from the {jurisdiction} corpus.
Each chunk header shows the actual document title + citation.

{chunks}

Your task — decide whether the claimed citation is correct, and if not,
what the real location is. Respond with ONE JSON object only, no prose:

{{
  "verdict": "verified" | "corrected" | "no_match",
  "best_chunk_index": <integer chunk number from above, or null>,
  "actual_doc_title": "<from the chunk header, or empty string>",
  "actual_citation": "<from the chunk header — the part after 'CITATION:', or empty>",
  "evidence_quote": "<20-60 char verbatim quote from the matched chunk, or empty>",
  "note": "<one sentence explaining your verdict>"
}}

Rules:
- "verified": the claimed citation broadly matches one of the chunks
  (same article number OR same document AND the chunk discusses the term).
- "corrected": the term IS in this jurisdiction but at a different
  citation — fill in the real one.
- "no_match": no chunk above discusses this concept at all.

Be strict. If you cannot find clear evidence, say "no_match" rather
than guessing."""


def _format_chunks_for_prompt(nodes, max_chars=2000) -> str:
    """Render retrieval nodes as a numbered block the LLM can reference."""
    lines = []
    total = 0
    for i, n in enumerate(nodes, 1):
        m = n.node.metadata
        doc   = m.get('doc_title', '')[:80]
        art   = m.get('article_ref', '')[:80]
        body  = n.node.get_content().strip()[:400]
        block = f'[Chunk {i}]  DOC: {doc}  CITATION: {art}\n{body}'
        if total + len(block) > max_chars:
            lines.append('... [truncated]')
            break
        lines.append(block)
        total += len(block)
    return '\n\n---\n\n'.join(lines)


def _parse_json_response(text: str) -> dict:
    """Tolerant JSON extractor — handles markdown fences and trailing prose."""
    import re
    if not text:
        return {'verdict': 'no_match', 'note': 'empty LLM response'}
    cleaned = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    # Find outermost { ... }
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end <= start:
        return {'verdict': 'no_match', 'note': f'no JSON in response: {text[:120]}'}
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        return {'verdict': 'no_match', 'note': f'JSON parse error: {e}'}


async def verify_entry(canonical: str, jurisdiction: str, info: dict, definition: str) -> dict:
    """Verify one (term, jurisdiction) entry."""
    synonyms = info.get('synonyms_local', []) or []
    jur_term = info.get('term', canonical)
    claimed  = info.get('citation', '')

    # Retrieve from the WHOLE jurisdiction corpus (all docs, not just one).
    query = f'{jur_term} {canonical} ' + ' '.join(synonyms[:3])
    nodes = hybrid_search(query, top_k=8, jurisdiction=jurisdiction,
                          rerank=True, expand_synonyms=True)

    if not nodes:
        return {
            'canonical':     canonical,
            'jurisdiction':  jurisdiction,
            'claimed':       claimed,
            'verdict':       'no_match',
            'note':          'no chunks retrieved at all',
        }

    chunks_block = _format_chunks_for_prompt(nodes)
    prompt = VERIFY_PROMPT.format(
        term=canonical,
        definition=definition,
        jurisdiction=jurisdiction,
        claimed_label=claimed,
        jur_term=jur_term,
        chunks=chunks_block,
    )

    llm = _get_llm()
    try:
        resp = await llm.ainvoke(prompt)
        text = resp.content if hasattr(resp, 'content') else str(resp)
    except Exception as e:
        return {
            'canonical':     canonical,
            'jurisdiction':  jurisdiction,
            'claimed':       claimed,
            'verdict':       'error',
            'note':          f'LLM call failed: {type(e).__name__}: {str(e)[:120]}',
        }

    parsed = _parse_json_response(text)
    return {
        'canonical':         canonical,
        'jurisdiction':      jurisdiction,
        'claimed':           claimed,
        'jur_term':          jur_term,
        'verdict':           parsed.get('verdict', 'no_match'),
        'actual_doc_title':  parsed.get('actual_doc_title', ''),
        'actual_citation':   parsed.get('actual_citation', ''),
        'evidence_quote':    parsed.get('evidence_quote', ''),
        'note':              parsed.get('note', ''),
    }


async def main_async(args):
    # Build the work list.
    work: list[tuple[str, str, dict, str]] = []
    for canonical, entry in TERMS.items():
        synonyms = entry.get('synonyms', [])
        definition = entry.get('definition', '')
        for jur, info in entry.get('jurisdictions', {}).items():
            if jur in SKIP_JURISDICTIONS:
                continue
            # Attach the canonical's synonyms onto info so the verifier can use them.
            info_with_synonyms = dict(info)
            info_with_synonyms['synonyms_local'] = synonyms
            work.append((canonical, jur, info_with_synonyms, definition))

    if args.limit:
        work = work[:args.limit]

    print(f'Verifying {len(work)} dictionary entries via Claude Haiku 4.5...')
    print()

    results = []
    t0 = time.time()
    for i, (canonical, jur, info, definition) in enumerate(work, 1):
        print(f'  [{i:3d}/{len(work)}] {canonical!r} / {jur}... ', end='', flush=True)
        result = await verify_entry(canonical, jur, info, definition)
        results.append(result)
        verdict = result.get('verdict', '?')
        actual  = result.get('actual_citation', '')
        if verdict == 'verified':
            print('OK')
        elif verdict == 'corrected':
            print(f'CORRECT  (-> {actual})')
        elif verdict == 'no_match':
            print('NO MATCH')
        else:
            print(verdict.upper())

    dt = time.time() - t0
    out_dir = Path(__file__).resolve().parent / 'output'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'dictionary_verification_report.json'
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')

    # Summary
    by_verdict: dict[str, int] = {}
    for r in results:
        v = r.get('verdict', '?')
        by_verdict[v] = by_verdict.get(v, 0) + 1

    print()
    print('=' * 60)
    print(f'  Completed in {dt:.1f}s ({dt / len(work):.1f}s per entry)')
    print('=' * 60)
    for v, n in sorted(by_verdict.items(), key=lambda x: -x[1]):
        print(f'  {v:12s} {n}')
    print()
    print(f'Full report written to: {out_path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None,
                    help='Verify only the first N entries (for quick testing)')
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == '__main__':
    main()
