"""LLM document intelligence — metadata + structure extraction (local qwen).

Reads the opening pages of a document and asks the LOCAL model (Ollama
qwen2.5:7b) to propose:

  - metadata   : title, jurisdiction, issuing authority, law number, year,
                 effective date, document type, citation abbreviation
  - structure  : the document's own hierarchy (parts / chapters / sections /
                 articles) — useful when the regex heuristics don't recognise
                 an unfamiliar layout

Everything runs on local Ollama — no cloud (see the fully-local rule). The
output is a SUGGESTION the user confirms/edits in the upload wizard; it is
never auto-applied. That keeps a human in the loop for anything that feeds a
compliance judgement.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import OLLAMA_URL  # noqa: E402

import ollama  # noqa: E402

MODEL = "qwen2.5:7b"

# Metadata + title/authority/number live in the first pages; cap the context so
# the call stays fast and the model isn't distracted by body articles.
_HEAD_CHARS = 6000


def _client() -> "ollama.Client":
    return ollama.Client(host=OLLAMA_URL)


def _chat_json(prompt: str, model: str = MODEL) -> dict:
    """One local chat call, forced to JSON. Returns {} on any failure so a bad
    model response degrades to 'no suggestion' rather than crashing the upload."""
    try:
        resp = _client().chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0},
        )
        return json.loads(resp["message"]["content"])
    except Exception:
        return {}


_METADATA_PROMPT = """You are a legal/compliance document cataloguer preparing a
document for a RETRIEVAL system used by a bank's compliance, risk and legal
teams. Read the opening of a regulation or internal policy and extract metadata
that makes it easy to FILTER, FIND, and CITE later. Use ONLY what the text states
— never invent a number, date, authority, or fact. If a field is not present,
return an empty string "" (or [] for the list fields).

Return a JSON object with EXACTLY these keys:
- "name": short human title, e.g. "Bahrain PDPL" or "PDPA Order 43/2022"
- "full_name": the official full title as printed
- "doc_type": "regulation" (a law / regulation / circular issued by an authority)
  or "policy" (an internal bank policy / SOP / procedure / guideline)
- "jurisdiction": the country/region the document governs, as a lowercase slug,
  e.g. "bahrain","india","kuwait","saudi","uae","qatar","oman","egypt","eu".
  Use the REAL country even if unusual — do not force it into a short list.
- "regulation_category": the subject area, lowercase, e.g. "data protection",
  "cybersecurity","aml/kyc","banking","privacy","electronic transactions",
  "internal controls","risk management"
- "issuing_authority": the body that issued it, verbatim if stated
- "document_id": the law/order/decision/policy number only (digits), e.g. "30"
- "doc_year": 4-digit year of issuance, e.g. "2018"
- "effective_date": ISO date YYYY-MM-DD if an effective/commencement date is stated, else ""
- "version": the document version if stated (e.g. "v2.1", "2023"), else ""
- "citation_abbr": a short citation label if obvious (e.g. "PDPL"), else ""
- "scope_summary": ONE grounded sentence describing WHAT the document governs and
  WHO it applies to — the one-line context a reviewer wants when this document
  appears in search results. No marketing language.
- "key_topics": array of 3-6 short lowercase subject tags for what the document
  actually covers, e.g. ["consent","data breach notification","cross-border
  transfer","data subject rights"]. These help route retrieval to the right doc.
- "owner_department": for an internal policy, the owning department if stated
  (e.g. "Compliance","Risk","Legal","IT"), else ""
- "confidence": your confidence 0.0-1.0 that these values are correct

Document opening:
---
{head}
---
JSON:"""


def extract_metadata(text: str, filename: str = "") -> dict:
    """Propose bibliographic metadata for a document from its opening text.

    Returns a dict with the keys listed in the prompt (+ 'confidence'), or {}
    if extraction failed. Values are suggestions for the user to confirm."""
    head = (text or "").strip()[:_HEAD_CHARS]
    if not head:
        return {}
    # replace, not .format(): the structure prompt contains literal { } JSON
    # braces; use the same substitution style here for consistency + safety.
    data = _chat_json(_METADATA_PROMPT.replace("{head}", head))
    if not isinstance(data, dict):
        return {}
    # normalise: keep only known keys, coerce types, clamp confidence
    keys = ["name", "full_name", "doc_type", "jurisdiction", "regulation_category",
            "issuing_authority", "document_id", "doc_year", "effective_date",
            "version", "citation_abbr", "scope_summary", "owner_department"]
    out = {k: str(data.get(k, "") or "").strip() for k in keys}
    # key_topics is a list — normalise to lowercase, de-dupe, cap at 6.
    kt = data.get("key_topics") or []
    if isinstance(kt, str):
        kt = [kt]
    seen: set = set()
    topics: list[str] = []
    for t in kt:
        t = re.sub(r"\s+", " ", str(t or "")).strip().lower()
        if t and t not in seen:
            seen.add(t)
            topics.append(t)
    out["key_topics"] = topics[:6]
    # Keep the REAL detected country as a slug — do NOT clamp to a fixed list.
    # A jurisdiction the corpus hasn't seen (e.g. "egypt") flows through so the
    # wizard can offer to create it. Slugify: lowercase, spaces/punct -> nothing.
    jl = re.sub(r"[^a-z0-9]+", "", out["jurisdiction"].lower())
    out["jurisdiction"] = jl or "other"
    out["regulation_category"] = out["regulation_category"].lower()
    out["doc_type"] = "policy" if out["doc_type"].lower().startswith("pol") else "regulation"
    try:
        out["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        out["confidence"] = 0.0
    return out


_STRUCTURE_PROMPT = """You are a legal-document analyst. Infer the STRUCTURE of
the document below — its own hierarchy of divisions. Different laws nest
differently (Part > Chapter > Article, or Section > Sub-section, or flat
Articles). Detect what THIS document actually uses.

CRITICAL RULES:
- Use ONLY divisions that are EXPLICITLY headed in the text (a real heading like
  "Article 5", "CHAPTER II", "Section 3", "المادة 4"). Do NOT invent divisions
  and do NOT renumber.
- A "Whereas" preamble and numbered recital paragraphs written as "(1)", "(2)",
  "(3)" are RECITALS, not articles. NEVER relabel a recital as "Article N". If a
  block is recitals, label those nodes "Recital" and set the level name to
  "Recital".
- The excerpt may be sampled from several places in the document (separated by
  "[…]"). Infer the OVERALL scheme from all of it, not just the opening.

Return a JSON object:
- "scheme": short description, e.g. "Recitals + Chapters > Articles" or "Articles"
- "levels": array of level names, outermost first, e.g. ["Chapter","Article"]
- "outline": array of top-level divisions, each:
    { "label": "Chapter I", "title": "General provisions",
      "children": [ { "label": "Article 1", "title": "Subject-matter" }, ... ] }
  Cap children at 12 per node. Only include divisions actually headed in the text.
- "confidence": 0.0-1.0

Document (may be sampled from multiple sections):
---
{body}
---
JSON:"""


def _multi_sample(text: str, total: int = 12000) -> str:
    """Sample a long document from several points so the model can identify the
    heading convention even when the opening is a long recital/preamble."""
    text = (text or "").strip()
    if len(text) <= total:
        return text
    w = total // 3
    n = len(text)
    return f"{text[:w]}\n[…]\n{text[n//2:n//2+w]}\n[…]\n{text[int(n*0.72):int(n*0.72)+w]}"


_LEVELS_PROMPT = """Identify the DIVISION LEVELS this legal document uses to
structure its body (the enacting terms), outermost first.

Return a JSON object:
- "scheme": short description, e.g. "Chapters > Articles" or "Articles"
- "levels": array, OUTERMOST first, each { "name": "Chapter", "prefix": "Chapter" }
  where "prefix" is the EXACT word that begins every heading of that level as it
  appears in the text ("Chapter", "Article", "Section", "Part", "المادة", …).
  Use ONLY levels that appear as real headings. A flat article list = one level.
- "has_recitals": true if there is a "Whereas"/numbered-recital preamble.
- "confidence": 0.0-1.0

Recitals are NOT a body level — report them via has_recitals, never in "levels".

Document (sampled from several sections):
---
{body}
---
JSON:"""

# Heading label only: <prefix> <number/roman>. Built from the model's detected
# prefix via re.escape, so no model-authored regex ever runs.
def _level_regex(prefix: str):
    p = re.escape(prefix.strip())
    return re.compile(
        rf"(?im)^[ \t]*{p}[ \t]*[\(\.\-:]?[ \t]*([0-9٠-٩]+|[IVXLCM]+)\b[\)\.\-:]?[ \t]*"
    )


def _title_after(text: str, end: int) -> str:
    """Grab the heading's title — the rest of its line, or the next substantive
    line when the title sits on its own line (e.g. GDPR's 'CHAPTER I' / 'General
    provisions'). Skips pure-number / very-short / 'Section N' lines so a chapter
    doesn't get a sub-section marker or a page number as its title."""
    def _ok(s: str) -> bool:
        return bool(s) and not s.isdigit() and len(s) > 2 \
            and not re.match(r"(?i)^section\s+[0-9ivxlcm]+\b", s)

    nl = text.find("\n", end)
    same = text[end: nl if nl != -1 else len(text)].strip(" .-:—")
    if _ok(same):
        return same[:90]
    if nl != -1:
        for line in text[nl + 1: nl + 340].splitlines():
            s = line.strip(" .-:—")
            if _ok(s):
                return s[:90]
    return ""


def _extract_full_outline(text: str, levels: list[dict], cap: int = 400) -> list[dict]:
    """Regex-scan the ENTIRE document for every heading of every detected level
    and assemble the complete nested outline. Verbatim (headings/titles copied
    from the text). Deduped by label so running page-headers / TOC repeats don't
    double-count — each Chapter/Article number appears once, at first sight."""
    hits: list[tuple] = []
    seen: set = set()
    for depth, lv in enumerate(levels):
        prefix = (lv.get("prefix") or lv.get("name") or "").strip()
        if not prefix:
            continue
        for m in _level_regex(prefix).finditer(text):
            label = f"{prefix} {m.group(1)}".strip()
            key = label.lower()
            if key in seen:
                continue
            title = _title_after(text, m.end())
            # Skip mid-sentence cross-references ("…referred to in Chapter VIII,
            # a body…" / "Article 58(3) or by the Board"): a real heading's title
            # is empty (next line) or starts uppercase/digit — a fragment starts
            # with a comma, lowercase word, or "(number". Don't mark seen, so a
            # later genuine heading of the same number can still be picked up.
            if title and (title[0] in ",;:" or title[0].islower()
                          or re.match(r"^\(\d", title)):
                continue
            seen.add(key)
            hits.append((m.start(), depth, label, title))
    hits.sort(key=lambda h: h[0])
    # If the document has outer divisions (e.g. Chapters), drop any inner-level
    # headings (Articles) that appear BEFORE the first outer heading — those are
    # preamble citations, not real body articles (e.g. GDPR recitals citing
    # 'Article 263 TFEU'). For a flat article list (no outer level) this is a
    # no-op, so those documents keep all their top-level articles.
    outer_positions = [h[0] for h in hits if h[1] == 0]
    if outer_positions:
        first_outer = outer_positions[0]
        hits = [h for h in hits if h[1] == 0 or h[0] >= first_outer]
    hits = hits[:cap]

    root: list[dict] = []
    stack: list[tuple] = []   # (depth, node)
    for _pos, depth, label, title in hits:
        node = {"label": label, "title": title, "children": []}
        while stack and stack[-1][0] >= depth:
            stack.pop()
        (stack[-1][1]["children"] if stack else root).append(node)
        stack.append((depth, node))
    return root


def _extract_numbered_outline(text: str, label_word: str = "", cap: int = 200) -> list[dict]:
    """Fallback outline for documents whose divisions are BARE numbered headings
    ('1.', '2.', …) with the number on its own line and the title on the next —
    a common policy / procedure format that carries no 'Article'/'Section' prefix
    for the prefix regex to latch onto. Reads the whole text, takes the title from
    the line after each lone number, strips any TOC dotted leader + page number,
    and keeps a single clean, monotonically-increasing 1..N run so stray numbered
    list items in the body can't leak in."""
    lines = text.splitlines()
    found: dict[int, str] = {}
    for i, l in enumerate(lines):
        m = re.match(r"^[ \t]*(\d{1,3})\.[ \t]*$", l)    # a line that is only "N." (the
                                                          # trailing dot separates real
                                                          # clause numbers from bare page
                                                          # numbers like a lone "2")
        if not m:
            continue
        num = int(m.group(1))
        if num in found:                                  # first (usually TOC) wins
            continue
        title = ""
        for j in range(i + 1, min(i + 4, len(lines))):
            s = lines[j].strip()
            if s:
                title = s
                break
        # Drop a table-of-contents dotted leader + trailing page number
        # ("Purpose of the Policy ........ 3" -> "Purpose of the Policy").
        title = re.split(r"\s*\.{3,}\s*", title)[0].strip(" .-:—")
        # A real heading title starts with an uppercase letter and is short-ish.
        if not title or not title[:1].isalpha() or not title[:1].isupper():
            continue
        if not (2 < len(title) <= 90):
            continue
        found[num] = title[:90]
    # Keep only the leading 1,2,3,… run.
    lw = (label_word or "").strip()
    out: list[dict] = []
    n = 1
    while n in found and len(out) < cap:
        label = f"{lw} {n}".strip() if lw else f"{n}."
        out.append({"label": label, "title": found[n], "children": []})
        n += 1
    return out


def infer_structure(text: str, sample_chars: int = 12000) -> dict:
    """Infer the document's full structural hierarchy by reading the WHOLE text.

    The local model only names the division levels (Chapter/Article/…) from a
    sample; the complete outline is then extracted by scanning every heading
    across the entire document with a safe regex. So the outline reflects the
    full document, not a sample, and is exact (verbatim headings)."""
    text = (text or "").strip()
    if not text:
        return {}
    meta = _chat_json(_LEVELS_PROMPT.replace("{body}", _multi_sample(text, sample_chars)))
    if not isinstance(meta, dict):
        return {}
    levels = [lv for lv in (meta.get("levels") or []) if isinstance(lv, dict)]
    outline = _extract_full_outline(text, levels) if levels else []

    # Prefix-based scan found nothing (the LLM named a level, e.g. "Clause", but
    # the headings are bare-numbered — "1." on its own line, title on the next —
    # so no "<prefix> <n>" ever matched). Fall back to a numbered-heading scan,
    # labelling with the detected level word when there is one ("Clause 1").
    if not outline:
        label_word = (levels[0].get("name") or levels[0].get("prefix") or "").strip() if levels else ""
        numbered = _extract_numbered_outline(text, label_word)
        if len(numbered) >= 3:
            outline = numbered
            meta["scheme"] = (label_word + "s").capitalize() if label_word else "Numbered sections"
            levels = levels or [{"name": label_word or "Section"}]

    # Recitals: count them across the whole doc rather than listing all 173.
    if meta.get("has_recitals"):
        n_rec = len(re.findall(r"(?m)^\s*\(\d+\)\s", text))
        rec_node = {"label": "Recitals", "title": (f"{n_rec} recitals" if n_rec else "preamble"),
                    "children": []}
        outline = [rec_node] + outline

    return {
        "scheme": meta.get("scheme", ""),
        "levels": [lv.get("name", lv.get("prefix", "")) for lv in levels],
        "outline": outline,
        "confidence": meta.get("confidence", 0.0),
    }


_HEADING_PROMPT = """You are segmenting a legal or policy document into its nodes.
Identify how the document marks where each numbered division STARTS.

Return a JSON object:
- "prefixes": array of the literal words that begin a heading line, e.g.
  ["Article"], ["Section"], ["Chapter","Article"], ["Clause"], Arabic ["المادة"].
  Use ONLY words that actually appear at the start of headings in the text below.
- "numbered": true if the divisions are BARE-NUMBERED — a lone number such as
  "1.", "2.", "3." begins each division with NO keyword word before it. Else false.
- "level_word": if the document has its own name for these numbered divisions
  (e.g. a Contents header labelled "Clause" or "Section"), give that ONE word;
  otherwise "".
- "examples": array of 2-4 verbatim heading strings copied from the text
- "confidence": 0.0-1.0

Do not invent words that are not present. If there is no consistent heading
convention, return an empty "prefixes" array and "numbered": false.

Document:
---
{body}
---
JSON:"""


def detect_heading_prefixes(text: str, max_chars: int = 9000) -> dict:
    """Ask the local model for the heading words that mark node boundaries.

    Returns {"prefixes": [...], "examples": [...], "confidence": float}. The
    caller builds a SAFE regex from the (escaped) prefixes and splits the full
    text on it — the model never rewrites the text, so legal wording is exact.
    Returns {} on failure / no convention."""
    body = (text or "").strip()[:max_chars]
    if not body:
        return {}
    data = _chat_json(_HEADING_PROMPT.replace("{body}", body))
    return data if isinstance(data, dict) else {}


def head_text(pdf_path, max_pages: int = 6) -> str:
    """Fast first-pages text grab for metadata/structure inference.

    Uses PyMuPDF's text layer directly — no docling — so it's instant and can
    run inside the upload request before the heavy ingest. Good enough for the
    title/authority/number that live up front; the full parse still happens at
    index time. Returns '' if the file can't be read."""
    try:
        import fitz  # PyMuPDF
        parts = []
        with fitz.open(str(pdf_path)) as doc:
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                parts.append(page.get_text())
        return "\n".join(parts).strip()
    except Exception:
        return ""


def structure_to_html(structure: dict) -> str:
    """Render an inferred structure dict into the small HTML tree the upload
    wizard drops into its review step. Escapes all model text. Returns '' if
    there's no usable outline."""
    from html import escape
    outline = (structure or {}).get("outline") or []
    if not outline:
        return ""
    scheme = escape(str(structure.get("scheme", "") or ""))
    rows = []
    for node in outline[:60]:
        label = escape(str(node.get("label", "") or ""))
        title = escape(str(node.get("title", "") or ""))
        kids = node.get("children") or []
        count = (f'<span style="font-size:9.5px;font-weight:700;color:#3B6FE0;background:#EEF2FB;'
                 f'padding:1px 7px;border-radius:9px;margin-left:8px;">{len(kids)}</span>') if kids else ""
        rows.append(
            f'<div style="padding:6px 10px;border-bottom:1px solid #F0F3F9;">'
            f'<span style="font-size:11px;font-weight:700;color:#002583;">{label}</span>'
            f'<span style="font-size:11px;color:#3A4560;margin-left:8px;">{title}</span>{count}</div>'
        )
        for ch in kids[:60]:
            cl = escape(str(ch.get("label", "") or ""))
            ct = escape(str(ch.get("title", "") or ""))
            rows.append(
                f'<div style="padding:4px 10px 4px 26px;border-bottom:1px solid #F5F7FB;">'
                f'<span style="font-size:10.5px;font-weight:600;color:#3B6FE0;">{cl}</span>'
                f'<span style="font-size:10.5px;color:#6B7690;margin-left:8px;">{ct}</span></div>'
            )
    header = (f'<p style="font-size:11px;color:#7B8499;margin:0 0 8px;">Detected scheme: '
              f'<b style="color:#14213D;">{scheme or "—"}</b></p>') if scheme else ""
    return (header +
            '<div style="border:1px solid #E9EDF5;border-radius:10px;overflow:hidden;'
            'max-height:260px;overflow-y:auto;">' + "".join(rows) + "</div>")
