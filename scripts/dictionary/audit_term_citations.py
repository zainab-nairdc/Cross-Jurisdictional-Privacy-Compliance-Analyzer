"""Verify every citation in reasoning/term_dictionary.py against the corpus.

For each (term, jurisdiction, citation) triple, this script:
  1. Parses the citation into (jurisdiction, source_doc_hint, article_number).
  2. Searches the BM25 index for chunks matching the article in that
     jurisdiction.
  3. Checks whether ANY matching chunk actually mentions the term (or one
     of its synonyms).

Output: pass / fail / not-found per entry, with the actual chunk text where
relevant so the human reader can verify the citation.

Run from project root:
    .venv\\Scripts\\python.exe scripts\\audit_term_citations.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reasoning.term_dictionary import TERMS
from retrieval.bm25_store import search_bm25


_JUR_NORM = {
    'Bahrain': 'Bahrain',
    'India':   'India',
    'Kuwait':  'Kuwait',
}

# Skip GDPR_ref — it's a reference column, no corpus to validate against.
SKIP_JURISDICTIONS = {'GDPR_ref'}


def parse_article(citation: str) -> list[str]:
    """Extract article numbers from a citation string.

    Examples:
      'PDPL Art. 14'             -> ['14']
      'PDPL Art. 14; Order 44/2022' -> ['14']
      'DPDPA s. 8(6)'            -> ['8', '8(6)']
      'DPPR Art. 11'             -> ['11']
      'GDPR Art. 6(1)(a), Art. 7' -> ['6(1)(a)', '7', '6', '6(1)']
    """
    nums = []
    # Match "Art. N" / "Article N" / "s. N" / "Section N" / "sec. N"
    for m in re.finditer(r'(?:Art(?:icle)?|s|Sec(?:tion)?)\.?\s*(\d+(?:\([^)]+\))*)', citation, re.IGNORECASE):
        full = m.group(1)
        nums.append(full)
        # also the bare number
        bare = re.match(r'(\d+)', full)
        if bare and bare.group(1) != full:
            nums.append(bare.group(1))
    return list(dict.fromkeys(nums))   # dedupe preserving order


def find_matching_chunks(jur: str, article_nums: list[str], term: str, synonyms: list[str]) -> tuple[bool, str, str]:
    """Look for a chunk in this jurisdiction whose article_ref matches one of
    the article numbers AND whose content mentions the term or a synonym.

    Returns (matched, evidence_doc, evidence_snippet).
    """
    if not article_nums:
        return False, '', ''

    # Search broadly first — give BM25 the term itself so we get topically
    # relevant chunks, then filter to ones whose article_ref matches.
    query = term + ' ' + ' '.join(synonyms[:3])
    rows = search_bm25(query, top_k=40, jurisdiction=_JUR_NORM.get(jur, jur))

    if not rows:
        return False, '', ''

    # Pre-normalise term + synonyms for substring match
    term_norm = term.lower()
    syn_norms = [s.lower() for s in synonyms]

    for r in rows:
        m = r.get('metadata', {})
        ref = (m.get('article_ref') or '').lower()
        content = (r.get('content') or '').lower()

        # Does the article_ref string contain any of our target numbers?
        matched_article = False
        for num in article_nums:
            # We want the FULL number to appear with a non-digit boundary
            pattern = rf'(?:^|\D){re.escape(num)}(?:\D|$)'
            if re.search(pattern, ref):
                matched_article = True
                break

        if not matched_article:
            continue

        # The article matches — does the term appear in the body?
        if term_norm in content:
            return True, m.get('doc_title', ''), r['content'][:240]
        for s in syn_norms:
            if s and len(s) > 3 and s in content:
                return True, m.get('doc_title', ''), r['content'][:240]

    return False, '', ''


def main():
    print('=' * 72)
    print('  Term Dictionary Citation Audit')
    print('=' * 72)

    total = 0
    verified = 0
    failed = []

    for canonical, entry in TERMS.items():
        jurs = entry.get('jurisdictions', {})
        synonyms = entry.get('synonyms', [])
        for jur_key, jur_info in jurs.items():
            if jur_key in SKIP_JURISDICTIONS:
                continue
            total += 1
            citation = jur_info.get('citation', '')
            jur_term = jur_info.get('term', canonical)
            article_nums = parse_article(citation)

            ok, doc, snippet = find_matching_chunks(
                jur_key, article_nums, jur_term, synonyms,
            )
            if ok:
                verified += 1
            else:
                failed.append({
                    'canonical':    canonical,
                    'jur':          jur_key,
                    'jur_term':     jur_term,
                    'citation':     citation,
                    'article_nums': article_nums,
                })

    print()
    print(f'Verified: {verified}/{total}')
    print(f'Failed:   {len(failed)}/{total}')
    print()

    if failed:
        print('=' * 72)
        print('  FAILED ENTRIES (citation does not match corpus)')
        print('=' * 72)
        for f in failed:
            print()
            print(f'  {f["canonical"]!r}  /  {f["jur"]}')
            print(f'    label:        {f["jur_term"]}')
            print(f'    citation:     {f["citation"]}')
            print(f'    parsed nums:  {f["article_nums"]}')


if __name__ == '__main__':
    main()
