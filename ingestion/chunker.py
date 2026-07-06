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

    return {
        "content":           text,
        "node_id":           _node_id(doc_title, chunk_id, index),
        "article_ref":       section_title,
        "section_title":     section_title,
        "hierarchy_path":    full_path,
        "chunk_id":          chunk_id,
        "section_level":     section_level,
        "chunk_index":       index,
        "chunk_total":       total,
        "parent_chunk_id":   parent_chunk_id,
        "embed_skip":        embed_skip,
        "is_obligation":     bool(_OBLIGATION_RE.search(text)),
        "chunk_type":        _classify(text, section_title),
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
        "source_url":        str(meta.get("Source URL", "")).strip(),
    }


_MIN_BODY_TOKENS = 5   # anything shorter than 5 tokens is basically just a heading


def _has_real_body(content: str) -> bool:
    """check that a section actually has text in it.
    the markdown splitter creates a section for every heading, even if the
    body underneath is empty (e.g. "## Ministry of Justice" with nothing
    after it). we throw those away — they're not useful chunks."""
    return len(_tokenizer.encode(content.strip())) >= _MIN_BODY_TOKENS


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


def chunk_document(text, meta: dict) -> list[dict]:
    """the one function you call from outside.
    pass in the markdown text + the metadata dict for the document, get
    back a list of chunk dicts ready for the embedder."""
    if hasattr(text, "text") and not isinstance(text, str):
        text = text.text
    if not isinstance(text, str) or not text.strip():
        return []

    sections: list[tuple[str, str]] = []
    for d in _md_splitter.split_text(text):
        body = d.page_content.strip()
        if not body:
            continue
        crumbs = [d.metadata[k] for k in ("h1", "h2", "h3", "h4") if d.metadata.get(k)]
        sections.append((" > ".join(crumbs), body))

    if len(sections) >= 2 and any(h for h, _ in sections):
        print(f"    [chunker] {len(sections)} sections")
        return _build(sections, meta)

    print(f"    [chunker] WARNING: no markdown headers in {meta.get('Document Title','')!r}")
    return _build_unstructured(text, meta)
