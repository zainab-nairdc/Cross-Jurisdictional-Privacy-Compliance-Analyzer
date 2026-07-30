"""Arabic legal chunking — one chunk per article, plus per-term definitions.

Generalized from the sandbox (which matched only "مادة N" with Western digits
in Bahrain's PDPL). This version handles the variation across GCC laws:

  - article marker:  "مادة" OR "المادة", with or without parentheses,
                     Western (4) or Arabic-Indic (٤) digits
  - hierarchy:       nearest الباب (part) / الفصل (chapter) above the article
  - definitions:     an article whose title looks like تعاريف/تعريفات is split
                     into one chunk per defined term when a "term : meaning"
                     pattern is present; otherwise it stays a single chunk

Robust by design: if no article headings are found at all, the whole document
is returned as one chunk so nothing is silently dropped — the caller can see a
1-chunk result and know the article regex didn't match this doc's format.
"""
import re

from .normalize import western_digits

# An article heading line — starts with مادة / المادة. The number may be digits
# ("المادة (5)", Qatar) OR an Arabic ordinal word ("المادة الأولى", Saudi/Bahrain),
# so we match the heading by its marker and derive the number positionally.
_ARTICLE_RE = re.compile(r"(?m)^\s*(?:ال)?مادة\b[^\n]*")
_ARTICLE_DIGITS_RE = re.compile(r"(\d(?:[ ]?\d)*)")
_PART_RE    = re.compile(r"(?m)^\s*(الباب\s+[^\n]{0,40})")
_SECTION_RE = re.compile(r"(?m)^\s*(الفصل\s+[^\n]{0,40})")

# titles that mark a definitions article
_DEFINITIONS_TITLE = re.compile(r"تعا?ري?ف")

# a "term : meaning" line (Arabic full-width or Latin colon)
_DEF_LINE = re.compile(r"^\s*(.+?)\s*[:：]\s*(.+)$")


def _last(pattern, text_before):
    m = list(pattern.finditer(text_before))
    return m[-1].group(1).strip() if m else None


def _split_definitions(article: dict) -> list[dict]:
    """Split a definitions article into one chunk per term. Falls back to a
    single article chunk if the term:meaning pattern isn't found."""
    defs = []
    for line in article["text"].splitlines():
        m = _DEF_LINE.match(line)
        if m and len(m.group(1)) <= 40:   # a term label is short
            term, meaning = m.group(1).strip(), m.group(2).strip()
            defs.append({
                **article,
                "chunk_type": "definition",
                "term": term,
                "text": f"{term}: {meaning}",
            })
    return defs


def chunk_arabic(text: str, source: str = "", law_name: str = "") -> list[dict]:
    """Turn normalized Arabic law text into a list of chunk dicts."""
    text = western_digits(text or "")
    matches = list(_ARTICLE_RE.finditer(text))

    if not matches:
        # No article headings recognised — don't lose the document. Return it
        # whole so the operator sees a 1-chunk result and knows to check the
        # extraction / article format for this doc.
        body = text.strip()
        return [{
            "chunk_type": "article", "article_number": None, "article_title": "",
            "part": None, "section": None, "term": None,
            "text": body, "source": source, "law_name": law_name,
        }] if body else []

    # Legal articles run 1..N in order. If the document looks cleanly sequential
    # (heading count is close to the highest number seen), trust the document
    # POSITION over the OCR'd digit — this repairs OCR number errors in one shot
    # (misreads like 6->8/16->18 and splits like 11->"1 1"). If it doesn't look
    # sequential (missed/false headings), fall back to the OCR'd numbers.
    ocr_nums = []
    for m in matches:
        dm = _ARTICLE_DIGITS_RE.search(m.group(0))
        ocr_nums.append(int(dm.group(1).replace(" ", "")) if dm else None)
    digits = [n for n in ocr_nums if n is not None]
    # Trust POSITION when the doc looks sequential OR when headings use ordinal
    # words (no digits to trust) — e.g. Saudi's "المادة الأولى/الثانية".
    use_positional = len(matches) >= 5 and (not digits or max(digits) <= len(matches) + 2)

    chunks: list[dict] = []
    for i, m in enumerate(matches):
        number = (i + 1) if use_positional else (ocr_nums[i] or (i + 1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        # title = first non-empty line after the heading line
        lines = [ln.strip() for ln in body.splitlines()]
        title = next((ln for ln in lines[1:] if ln), "")

        before = text[:start]
        article = {
            "chunk_type": "article",
            "part": _last(_PART_RE, before),
            "section": _last(_SECTION_RE, before),
            "article_number": number,
            "article_title": title,
            "term": None,
            "text": body,
            "source": source,
            "law_name": law_name,
        }

        # Definitions detection is CONTENT-based, not title-based: an article
        # with several "term: meaning" lines IS the definitions article, even
        # when its heading is a plain intro sentence rather than "تعاريف".
        split = _split_definitions(article)
        if len(split) >= 4 or (_DEFINITIONS_TITLE.search(title) and split):
            chunks.extend(split)
        else:
            chunks.append(article)

    return chunks


# A clause marker inside an article body: a line starting with a number
# (Western or Arabic-Indic) or an Arabic ordinal letter, then - ) . or ：
_CLAUSE_RE = re.compile(r"(?m)^\s*(?:[0-9٠-٩]{1,2}|[أ-ي])\s*[-).．:：]\s+")


def restrategize(chunks: list[dict], strategy: str) -> list[dict]:
    """Reshape the article/definition chunks produced by ``chunk_arabic`` to
    match a user-chosen chunking strategy (guided-upload Screen 6). This runs on
    the CACHED chunks at finalize time — no re-extraction / re-OCR.

      auto / article  → unchanged (one node per article + per-term definitions)
      section         → merge every node under the same part+section into one
      clause          → split each article body on its clause markers

    Any strategy that would yield nothing usable falls back to the input, so a
    document is never silently emptied.
    """
    if strategy in (None, "", "auto", "article"):
        return chunks

    if strategy == "section":
        from collections import OrderedDict
        groups: "OrderedDict[tuple, list]" = OrderedDict()
        for c in chunks:
            key = (c.get("part") or "", c.get("section") or "")
            groups.setdefault(key, []).append(c)
        merged = []
        for (part, section), members in groups.items():
            body = "\n\n".join(m["text"] for m in members)
            merged.append({
                "chunk_type": "section",
                "part": part or None,
                "section": section or None,
                "article_number": None,
                "article_title": section or part or (members[0].get("article_title") or ""),
                "term": None,
                "text": body,
                "source": members[0].get("source"),
                "law_name": members[0].get("law_name"),
            })
        return merged or chunks

    if strategy == "clause":
        out = []
        for c in chunks:
            if c.get("chunk_type") != "article":
                out.append(c)              # definitions are already fine-grained
                continue
            body = c["text"]
            marks = list(_CLAUSE_RE.finditer(body))
            if len(marks) < 2:
                out.append(c)              # not clause-structured — keep whole
                continue
            # keep the heading/title text (before the first clause) with clause 1
            for j, mk in enumerate(marks):
                s = mk.start()
                e = marks[j + 1].start() if j + 1 < len(marks) else len(body)
                seg = body[:e] if j == 0 else body[s:e]
                out.append({**c, "chunk_type": "clause",
                            "article_title": c.get("article_title") or "",
                            "text": seg.strip()})
        return out or chunks

    return chunks


def embed_text(c: dict) -> str:
    """Text handed to the embedder: prepend the article's context (part /
    section / title / term) so a query can match the heading, not just the
    body wording. Mirrors the main pipeline's Jurisdiction/Citation prefix."""
    header = " ".join(filter(None, [
        c.get("part"), c.get("section"), c.get("article_title"), c.get("term"),
    ]))
    return f"{header}\n\n{c['text']}".strip()
