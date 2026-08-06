"""splits a markdown document into chunks we can embed and search.

the rules are:
  - we trust the markdown headers (#, ##, ###, ####) to tell us the
    document's structure. one section per header.
  - every chunk we produce is under CHUNK_TOKENS (default 512) so it
    fits in the embedder.
  - if a section is too big, we keep the whole thing as a "parent"
    (saved separately for context, not embedded) and split it into
    smaller "children" that we DO embed. the children remember their
    parent so retrieval can pull the full context back if needed.

the output is a list of dicts that the embedder, indexer, and bm25 store
all share.
"""
import re
import sys
import hashlib
import tiktoken
from pathlib import Path
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import CHUNK_TOKENS, CHUNK_OVERLAP_TOKENS


_tokenizer = tiktoken.get_encoding("cl100k_base")

_md_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")],
    # strip_headers=True keeps just the body of each section, not the
    # "## Article 4" line itself. we already capture the header in the
    # section_title and hierarchy_path fields, and the embedder repeats
    # it in its citation prefix — putting it inside the body too would just
    # be noise. it also stops parent headers from leaking down into child
    # chunks when there's an empty section between them.
    strip_headers=True,
)

_recursive_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base",
    chunk_size=CHUNK_TOKENS,
    chunk_overlap=CHUNK_OVERLAP_TOKENS,
    separators=["\n\n", "\n", ". ", "? ", "! ", "; ", " ", ""],
    keep_separator=True,
)

# words that mean "this is a binding rule" — we tag chunks containing them
# so retrieval can prefer obligations over background text.
_OBLIGATION_RE = re.compile(
    r'\b(?:shall|must|required to|mandatory|prohibited|may not|shall not|is required)\b',
    re.IGNORECASE,
)

# phrases that show up in the preamble / opening of a law (the "whereas..."
# part). this is background, not actual rules, so we mark these chunks as
# preamble and keep them out of obligation matches.
_PREAMBLE_RE = re.compile(
    r'\b(?:after\s+reviewing|having\s+perused|whereas|and\s+whereas|'
    r'be\s+it\s+enacted|the\s+following\s+has\s+been\s+decided)',
    re.IGNORECASE,
)


# docling sometimes fuses a chapter heading and its article heading into one
# line, so the section label comes through as e.g. "Chapter Seven Penalties
# Article (23)" instead of "Article (23)". When an "Article (N)" token is
# present, that IS the canonical label — collapse to it. Headings with no
# article token (preamble, definitions lead-ins) are left untouched.
_ARTICLE_REF_RE = re.compile(r"\bArticle\s*\(?\s*(\d+)\s*\)?", re.IGNORECASE)


def _canonical_ref(title: str) -> str:
    """Reduce a chapter-prefixed heading to its bare 'Article (N)' label."""
    m = _ARTICLE_REF_RE.search(title or "")
    return f"Article ({m.group(1)})" if m else title


def _node_id(doc_title: str, chunk_id: str, index: int) -> str:
    """build a stable id for a chunk by hashing its inputs.
    same inputs always give the same hash, so re-running ingestion just
    overwrites the old row instead of creating a duplicate."""
    return hashlib.md5(f"{doc_title.lower()}::{chunk_id}::{index}".encode()).hexdigest()


def _slug(title: str, hash_input: str) -> str:
    """make a short, readable id-fragment from a section title.
    the first 30 chars of the cleaned title, plus a 6-char hash of the full
    hierarchy path. the hash is what keeps two "Article 4" sections under
    different chapters from colliding."""
    base = re.sub(r'[^A-Za-z0-9_]+', '_', title).strip('_')[:30] or "section"
    suffix = hashlib.md5(hash_input.encode("utf-8")).hexdigest()[:6]
    return f"{base}_{suffix}"


def _make_chunk(text, meta, chunk_id, index, total, *,
                section_level, parent_chunk_id="", hierarchy_path="",
                section_title="", embed_skip=False) -> dict:
    """assemble the dict that represents one chunk.
    every other file in the pipeline (embedder, indexer, bm25) reads from
    the same shape, so this is the single source of truth for what a chunk
    looks like."""
    doc_title       = str(meta.get("Document Title", "")).strip()
    regulation_name = str(meta.get("Regulation Name + Version", "")).strip()

    # stick the regulation name on the front of the breadcrumb. some docs are
    # flat — just articles, no chapters — and without this they'd lose any
    # sense of which law they came from. result looks like:
    # "PDPA Ministerial Order 51/2022 > Article (3)"
    if regulation_name and not hierarchy_path.startswith(regulation_name):
        full_path = f"{regulation_name} > {hierarchy_path}" if hierarchy_path else regulation_name
    else:
        full_path = hierarchy_path

    chunk_type = _classify(text, section_title)
    # A preamble/enacting chunk whose "heading" is really page furniture (the
    # repeating "N Law No. …" gazette header docling promoted to a heading)
    # makes an ugly citation label. When the chunk is preamble and its heading
    # carries no "Article (N)" token, show it as "Preamble" instead.
    display_ref = section_title
    if chunk_type == "preamble" and not _ARTICLE_REF_RE.search(section_title or ""):
        display_ref = "Preamble"

    return {
        "content":           text,
        "node_id":           _node_id(doc_title, chunk_id, index),
        "article_ref":       display_ref,
        "section_title":     display_ref,
        "hierarchy_path":    full_path,
        "chunk_id":          chunk_id,
        "section_level":     section_level,
        "chunk_index":       index,
        "chunk_total":       total,
        "parent_chunk_id":   parent_chunk_id,
        "embed_skip":        embed_skip,
        "is_obligation":     bool(_OBLIGATION_RE.search(text)),
        "chunk_type":        chunk_type,
        "jurisdiction":      str(meta.get("Jurisdiction", "")).strip(),
        "regulation_name":   regulation_name,
        "doc_title":         doc_title,
        "doc_type":          str(meta.get("Document Type", "")).strip(),
        "issuing_authority": str(meta.get("Issuing Authority", "")).strip(),
        "effective_date":    str(meta.get("Effective Date", "")).strip(),
        "publication_date":  str(meta.get("Publication Date", "")).strip(),
        "last_updated":      str(meta.get("Last Updated", "")).strip(),
        "language":          str(meta.get("Language", "English")).strip(),
        "scope_summary":     str(meta.get("Scope Summary", "")).strip(),
        "key_topics":        str(meta.get("Key Topics", "")).strip(),
        "source_url":        str(meta.get("Source URL", "")).strip(),
    }


_MIN_BODY_TOKENS = 5   # anything shorter than 5 tokens is basically just a heading


def _has_real_body(content: str) -> bool:
    """check that a section actually has text in it.
    the markdown splitter creates a section for every heading, even if the
    body underneath is empty (e.g. "## Ministry of Justice" with nothing
    after it). we throw those away — they're not useful chunks."""
    return len(_tokenizer.encode(content.strip())) >= _MIN_BODY_TOKENS


_DOTTED_LEADER_RE = re.compile(r"\.{4,}\s*\d*\s*$")


def _is_toc_section(title: str, body: str) -> bool:
    """A table-of-contents / index section — dotted-leader lines ending in a page
    number ('Purpose of the Policy ......... 3'), usually under a 'Contents'
    heading. It's navigation, not substance: indexing it just pollutes retrieval
    (a query can match the TOC's title list instead of the real clause body)."""
    t = (title or "").strip().lower()
    if "table of contents" in t or t in ("contents", "contents clause", "index"):
        return True
    lines = [l for l in (body or "").splitlines() if l.strip()]
    if len(lines) >= 4:
        dotted = sum(1 for l in lines if _DOTTED_LEADER_RE.search(l))
        if dotted >= max(4, len(lines) * 0.5):
            return True
    return False


def _classify(text: str, section_title: str) -> str:
    """label what kind of chunk this is, so retrieval can weight it later.

    one of: 'definition', 'operative', 'preamble', 'general'.

    important: we check preamble BEFORE operative. preamble text often
    contains "shall" (e.g. "...by Law No. 30/2018, which shall come into
    force..."), but it's still not an actual rule — it's just intro text."""
    title_lc = section_title.lower()
    if "definition" in title_lc:
        return "definition"
    if _PREAMBLE_RE.search(text):
        return "preamble"
    if _OBLIGATION_RE.search(text):
        return "operative"
    return "general"


def _build(sections: list[tuple[str, str]], meta: dict) -> list[dict]:
    """walk through every section we got from the markdown splitter and
    turn each one into chunks.
    if a section fits under the token budget, it becomes one leaf chunk.
    if it's too big, we save the whole thing as a parent (not embedded)
    and split it into smaller children that we DO embed. children remember
    their parent so retrieval can pull the full section back later."""
    doc_title = str(meta.get("Document Title", "")).strip()
    chunks: list[dict] = []
    leaves: list[tuple] = []   # (text, title, hpath, level, parent_id, sec_idx)

    for i, (hpath, body) in enumerate(sections):
        if not body or not _has_real_body(body):
            continue
        title = (hpath.rsplit(">", 1)[-1].strip() if ">" in hpath else hpath.strip()) or f"Section_{i+1}"
        if _is_toc_section(title, body):
            continue                    # skip the table of contents — navigation, not content
        title = _canonical_ref(title)
        slug  = _slug(title, hpath or title)

        if len(_tokenizer.encode(body)) <= CHUNK_TOKENS:
            leaves.append((body, title, hpath, "article", "", i))
            continue

        # this section is too big to embed in one shot. save the whole
        # thing as a parent (we'll keep it around for context but not
        # embed it), then break it into smaller children we can embed.
        # each child carries the parent's id so we can find each other later.
        parent_cid = f"parent_{slug}_s{i}"
        parent_nid = _node_id(doc_title, parent_cid, i)
        chunks.append(_make_chunk(
            body, meta, parent_cid, i, -1,
            section_level="article", hierarchy_path=hpath,
            section_title=title, embed_skip=True,
        ))
        for sub in _recursive_splitter.split_text(body):
            sub = sub.strip()
            if sub:
                leaves.append((sub, title, hpath, "paragraph", parent_nid, i))

    counter: dict[int, int] = {}
    total = len(leaves)
    for i, (t, title, hpath, level, par, sec_idx) in enumerate(leaves):
        counter[sec_idx] = counter.get(sec_idx, 0) + 1
        cid = f"{_slug(title, hpath or title)}_s{sec_idx}_{counter[sec_idx]}"
        chunks.append(_make_chunk(
            t, meta, cid, i, total,
            section_level=level, parent_chunk_id=par,
            hierarchy_path=hpath, section_title=title,
        ))
    return chunks


def _build_unstructured(text: str, meta: dict) -> list[dict]:
    """fallback for when a doc has no markdown headers at all.
    we just split it on paragraph boundaries and number the chunks. not
    ideal — we lose the legal structure — but better than nothing."""
    pieces = [p.strip() for p in _recursive_splitter.split_text(text) if p.strip()]
    return [
        _make_chunk(
            t, meta, f"uc_{i+1}", i, len(pieces),
            section_level="paragraph",
            section_title=f"Unstructured_Chunk_{i+1}",
            hierarchy_path=f"Unstructured_Chunk_{i+1}",
        )
        for i, t in enumerate(pieces)
    ]


def chunk_document(text, meta: dict, raw_text: str | None = None) -> list[dict]:
    """the one function you call from outside.
    pass in the markdown text + the metadata dict for the document, get
    back a list of chunk dicts ready for the embedder.

    raw_text (optional) is the PDF's plain text layer. docling's markdown
    drops/garbles headings on some layouts (e.g. a policy whose clauses are
    'N.' on their own line — docling loses clause 5 and turns the table of
    contents into a chunk), but the raw text keeps them, so we detect the
    document's true clause structure from raw_text when the markdown-based
    splits come up short. Falls back to `text` when raw_text isn't given."""
    if hasattr(text, "text") and not isinstance(text, str):
        text = text.text
    if not isinstance(text, str) or not text.strip():
        return []
    struct_text = raw_text if (raw_text and raw_text.strip()) else text

    sections: list[tuple[str, str]] = []
    for d in _md_splitter.split_text(text):
        body = d.page_content.strip()
        if not body:
            continue
        crumbs = [d.metadata[k] for k in ("h1", "h2", "h3", "h4") if d.metadata.get(k)]
        sections.append((" > ".join(crumbs), body))

    # PRIMARY: article-based split (fast, no LLM). docling's markdown headers are
    # unreliable for legal PDFs — it collapsed all of GDPR into a few giant
    # "Section" blobs — so when the text has a clear Article/Section structure we
    # chunk by THAT, not by docling's headers. This is what makes per-article
    # retrieval and citations work. docling headers are only a fallback below.
    article_sections = _legal_article_split(text)
    md_ok = len(sections) >= 2 and any(h for h, _ in sections)
    if len(article_sections) >= 4:
        print(f"    [chunker] article-based: {len(article_sections)} sections "
              f"(markdown had {len(sections)})")
        return _build(article_sections, meta)

    # SECONDARY: the document's true clause structure, read from the raw text —
    # bare-numbered headings ('1.' on its own line, title on the next) that carry
    # no Article/Section keyword and that docling mangles. Preferred over docling
    # markdown so a policy indexes as clean, whole clauses with 'Clause N' refs
    # that match the structure preview, instead of TOC noise + fragmented bullets.
    # LLM-DETERMINED structure — the authority for every document that isn't an
    # exact keyword-Article law. The model names the heading convention (Article /
    # Section / Clause / bare-numbered) from the RAW text and we split on those
    # verbatim heading lines — the model never rewrites the legal text. docling's
    # markdown headers are unreliable (dropped headings, TOC-as-a-chunk, split
    # bullets), so they are now only a last-resort fallback.
    llm_sections = _sections_from_llm(struct_text)
    if len(llm_sections) >= 3:
        print(f"    [chunker] LLM structure-aware: {len(llm_sections)} sections")
        return _build(llm_sections, meta)

    # Offline-safe deterministic fallback: split clean bare-numbered clauses when
    # the LLM is unavailable but the document is clearly clause/numbered.
    numbered = _numbered_split(struct_text, _numbered_level_word(struct_text))
    if len(numbered) >= 4:
        print(f"    [chunker] clause-based: {len(numbered)} sections (raw text)")
        return _build(numbered, meta)

    if len(article_sections) >= 2:
        print(f"    [chunker] article-based: {len(article_sections)} sections")
        return _build(article_sections, meta)

    if md_ok:
        print(f"    [chunker] {len(sections)} sections (markdown fallback)")
        return _build(sections, meta)

    print(f"    [chunker] WARNING: no headings in {meta.get('Document Title','')!r}")
    return _build_unstructured(text, meta)


# Common legal division words that begin a heading line. Tried in order; the one
# with the most line-start matches wins. No LLM — deterministic and instant.
_LEGAL_PREFIXES = ("Article", "Section", "Clause", "Rule", "Regulation",
                   "المادة", "المــادة", "الماده")


def _longest_increasing(seq: list) -> list:
    """Longest strictly-increasing-by-value subsequence of [(pos, value)], kept
    in document order. O(n^2) — fine for the ~hundreds of headings in a law."""
    n = len(seq)
    if not n:
        return []
    dp = [1] * n
    par = [-1] * n
    for i in range(n):
        for j in range(i):
            if seq[j][1] < seq[i][1] and dp[j] + 1 > dp[i]:
                dp[i] = dp[j] + 1
                par[i] = j
    i = max(range(n), key=lambda k: dp[k])
    out = []
    while i != -1:
        out.append(seq[i])
        i = par[i]
    return out[::-1]


def _legal_article_split(text: str) -> list[tuple[str, str]]:
    """Split by the document's dominant legal heading (Article N / Section N /
    المادة N). Returns [(title, body)] or [] if no clear structure.

    For arabic-numbered headings it keeps only the real sequential run (1..N),
    which drops preamble cross-references (e.g. GDPR recitals citing 'Article 263
    TFEU') that would otherwise mis-anchor a chunk. Text before the first real
    article becomes a 'Preamble' chunk so recitals aren't lost."""
    best: list = []
    best_prefix = ""
    for prefix in _LEGAL_PREFIXES:
        # Allow leading markdown markers (#, *, >) that docling may prepend to a
        # heading, plus whitespace, before the prefix word.
        rgx = re.compile(
            rf"(?im)^[ \t#>*]*{re.escape(prefix)}[ \t]*\(?\s*([0-9٠-٩]+|[IVXLCM]+)\b"
        )
        ms = list(rgx.finditer(text))
        if len(ms) > len(best):
            best, best_prefix = ms, prefix
    if len(best) < 3:
        return []

    _AR = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    numeric = [(m.start(), int(m.group(1).translate(_AR)), m.group(1))
               for m in best if m.group(1).translate(_AR).isdigit()]

    if len(numeric) >= max(3, len(best) // 2):
        # Arabic-numbered law → keep the main increasing article run.
        kept = _longest_increasing([(p, v) for p, v, _ in numeric])
        pos_to_raw = {p: raw for p, _, raw in numeric}
        positions = [(p, pos_to_raw[p]) for p, _ in kept]
    else:
        # Roman / other → dedup by first occurrence of each label.
        positions = []
        seen: set = set()
        for m in best:
            k = m.group(1)
            if k in seen:
                continue
            seen.add(k)
            positions.append((m.start(), k))

    sections: list[tuple[str, str]] = []
    # Preamble: substantive text before the first real heading (recitals, etc.).
    if positions and positions[0][0] > 400:
        pre = text[: positions[0][0]].strip()
        if len(pre) > 400:
            sections.append(("Preamble", pre))
    for i, (start, num) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        block = text[start:end].strip()
        if block:
            sections.append((f"{best_prefix} {num}", block))
    return sections


def _numbered_level_word(text: str) -> str:
    """The word a document uses for its numbered divisions ('Clause', 'Section',
    'Article', 'Rule', 'Part'…), taken from a standalone heading word near the top
    (e.g. a Contents column header 'Clause'). Defaults to 'Section'."""
    head = text[:4000]
    for w in ("Clause", "Article", "Section", "Rule", "Regulation", "Part", "Paragraph", "Item"):
        if re.search(rf"(?im)^[ \t]*{w}s?[ \t]*$", head):
            return w
    return "Section"


def _numbered_split(text: str, level_word: str = "Section", cap: int = 400) -> list[tuple[str, str]]:
    """Split a document whose divisions are BARE numbered headings — 'N.' on its
    own line with the title on the next line — into (title, body) sections. This
    is the common policy / procedure format that carries no Article/Section
    keyword for _legal_article_split to catch, and that docling's markdown
    mangles. The table of contents lists the same 'N.' earlier, so we keep the
    LAST occurrence of each number (the body heading, not the TOC entry) and only
    the clean leading 1..N run — giving whole, correctly-labelled clauses."""
    lines = text.splitlines()
    offs: list[int] = []
    o = 0
    for l in lines:
        offs.append(o)
        o += len(l) + 1
    per_num: dict[int, tuple[int, str]] = {}
    for i, l in enumerate(lines):
        m = re.match(r"^[ \t]*(\d{1,3})\.[ \t]*$", l)     # a line that is only "N."
        if not m:
            continue
        num = int(m.group(1))
        title = ""
        for j in range(i + 1, min(i + 4, len(lines))):
            s = lines[j].strip()
            if s:
                title = s
                break
        title = re.split(r"\s*\.{3,}\s*", title)[0].strip(" .-:—")   # drop a TOC dotted leader
        if not title or not title[:1].isalpha() or not title[:1].isupper():
            continue
        if not (2 < len(title) <= 90):
            continue
        per_num[num] = (offs[i], title[:90])   # last wins → the body heading, not the TOC
    if len(per_num) < 4:
        return []
    seq: list[tuple[int, int, str]] = []
    n = 1
    while n in per_num and len(seq) < cap:
        off, title = per_num[n]
        seq.append((n, off, title))
        n += 1
    if len(seq) < 4:
        return []
    seq.sort(key=lambda x: x[1])
    lw = (level_word or "").strip()
    sections: list[tuple[str, str]] = []
    for idx, (num, start, title) in enumerate(seq):
        end = seq[idx + 1][1] if idx + 1 < len(seq) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        label = f"{lw} {num}" if lw else f"{num}."
        sections.append((f"{label}: {title}", body))
    return sections


def _sections_from_llm(text: str) -> list[tuple[str, str]]:
    """Split raw text into (title, body) sections using an LLM-detected heading
    convention. Returns [] if the model finds no convention or the split yields
    fewer than 2 nodes. Runs only in the no-markdown-header fallback, so the
    per-document LLM cost is paid only when the cheap path already failed."""
    try:
        from reasoning.doc_intel import detect_heading_prefixes
    except Exception:
        return []
    try:
        info = detect_heading_prefixes(text)
    except Exception:
        return []
    prefixes = [p.strip() for p in (info.get("prefixes") or [])
                if isinstance(p, str) and p.strip()]
    # The word the document calls its divisions, for labelling a bare-numbered
    # split — the model's explicit level_word, else the prefix it named (a policy
    # whose Contents header says "Clause" but whose headings are "1.", "2."), else
    # a word scanned from the text. Used by the bare-numbered fallback below.
    level_word = ((info.get("level_word") or "").strip()
                  or (prefixes[0] if prefixes else "")
                  or _numbered_level_word(text))

    matches: list = []
    if prefixes:
        # Build a SAFE regex from the escaped prefix words: a line that starts with
        # one of them followed by a number (arabic or roman). No model-authored
        # regex — re.escape blocks injection / catastrophic backtracking.
        alt = "|".join(re.escape(p) for p in prefixes[:8])
        try:
            heading_re = re.compile(
                rf"(?im)^[ \t]*(?:{alt})[ \t]*[\(\.\-:]?[ \t]*[\dIVXLCivxlc٠-٩]+",
            )
            matches = list(heading_re.finditer(text))
        except re.error:
            matches = []

    # Prefix headings didn't line up (or there was no prefix). The model routinely
    # mistakes a Contents label ("Clause") for a prefix while the real headings are
    # bare numbers, so ALWAYS try the bare-numbered split as the fallback, labelled
    # with the level word the model gave. This is what makes the LLM path cover
    # policies/procedures/contracts with no Article/Section keyword.
    if len(matches) < 2:
        numbered = _numbered_split(text, level_word)
        if len(numbered) >= 2:
            return numbered
        return []
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if not block:
            continue
        title = (block.splitlines()[0].strip() if block else "")[:120]
        sections.append((title, block))
    return sections
