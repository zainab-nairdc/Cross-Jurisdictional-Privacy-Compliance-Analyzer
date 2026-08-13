"""Deterministic detection of legal cross-references in provision text.

A requirement extracted from "The Authority shall perform the duties referred
to in Article 31" is not self-contained: it points somewhere. Losing that
pointer makes the requirement look complete when it is not, and copying the
target's text into it would fabricate a provision nobody enacted. So the
pointer is recorded as a pointer.

This module does DETECTION only — it finds the reference and normalises what
it says. It never decides what the reference POINTS AT: resolution needs the
document's chunk index and lives in apps.library.references. The split is not
cosmetic. Detection is pure, deterministic and unit-testable with no database;
resolution is the part that can fail safely, and keeping them apart is what
lets a reference be recorded as detected-but-unresolved rather than dropped.

Regex, not a model. Legal citation forms are a narrow, closed grammar, and a
model asked to spot them would occasionally invent one — which is the single
worst outcome here. A wrong cross-reference is far more damaging than a missing
one: it manufactures traceability that does not exist, and a reviewer has no
way to tell a fabricated link from a real one. Everything in this module is
therefore biased towards emitting nothing when unsure.

Grounded in the actual corpus. The forms handled here were taken from the
Bahrain PDPL, Egypt PDPL, GDPR and Kuwait ETL text already indexed, where the
dominant shapes are "Article (10) of this Law", "Paragraph (2) of Article (34)
of this Law" and "Paragraph (1) of this Article".
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── vocabularies ────────────────────────────────────────────────────────────

KIND_ARTICLE   = "article"
KIND_SECTION   = "section"
KIND_CLAUSE    = "clause"
KIND_PARAGRAPH = "paragraph"
KIND_SCHEDULE  = "schedule"
KIND_LAW       = "law"
KIND_UNKNOWN   = "unknown"

SCOPE_INTERNAL = "internal"
SCOPE_EXTERNAL = "external"
SCOPE_UNKNOWN  = "unknown"

# Relative designations. Stored in `ref_number` because they ARE the normalised
# designation for these references — "the preceding Article" names its target
# by position, not by number. Kept stable from detection onward so the
# deduplication key never changes when resolution later succeeds or fails.
REL_PRECEDING = "preceding"
REL_FOLLOWING = "following"
REL_SELF      = "self"
RELATIVE_NUMBERS = frozenset({REL_PRECEDING, REL_FOLLOWING, REL_SELF})

DETECTED_BY_REGEX = "regex"
DETECTED_BY_LLM   = "llm"


@dataclass(frozen=True)
class DetectedReference:
    """One reference found in a span of text, before anything is resolved.

    `ref_text` is the matched source wording, verbatim and never normalised —
    it is the audit record of what the provision actually said.

    `ref_number` is the normalised designation, and its grammar is closed:
        "31"        a single article/section/paragraph/schedule
        "31(2)"     a provision and its subsection
        "31-35"     an inclusive range
        "preceding" / "following" / "self"   relative designations
        "self(1)"   a subsection of the article the text sits in
        ""          no number could be normalised (e.g. a bare "this Law")

    It is fixed at DETECTION and never rewritten by resolution, which is what
    makes it safe to use in the deduplication key: a re-run that newly
    resolves a reference must update that reference, not create a second one.
    """
    ref_text:     str
    ref_kind:     str
    ref_number:   str
    scope:        str
    confidence:   float
    detected_by:  str = DETECTED_BY_REGEX
    # Set when the reference names another instrument ("Law No. 30 of 2018").
    # Matching it to a Document happens during resolution, not here.
    law_citation: str = ""
    law_number:   str = ""
    law_year:     str = ""
    start:        int = 0
    end:          int = 0

    @property
    def relative_kind(self) -> str:
        """'preceding' | 'following' | 'self', or '' if not a relative ref."""
        base = self.ref_number.partition("(")[0]
        return base if base in RELATIVE_NUMBERS else ""

    @property
    def is_relative(self) -> bool:
        return bool(self.relative_kind)

    @property
    def is_range(self) -> bool:
        return "-" in self.ref_number and not self.is_relative

    @property
    def subsection(self) -> str:
        """The bracketed part of the designation: '31(2)' -> '2'. '' if none."""
        _, _, tail = self.ref_number.partition("(")
        return tail.rstrip(")") if tail else ""

    @property
    def base_number(self) -> str:
        """The designation without its subsection: '31(2)' -> '31'."""
        return self.ref_number.partition("(")[0]

    def range_bounds(self) -> tuple[int, int] | None:
        if not self.is_range:
            return None
        lo, _, hi = self.ref_number.partition("-")
        try:
            return int(lo), int(hi)
        except ValueError:
            return None


# ── shared fragments ────────────────────────────────────────────────────────

# A provision number: 31, 67B. The optional trailing letter is real — the
# Indian IT Act indexes provisions as "67B."
_N = r"\d{1,4}[A-Za-z]?"

# "of this Law" / "of this Act". Consumed as part of the reference so a
# standalone "this Law" pattern cannot fire again on the same words and file a
# duplicate, noisier reference beside the precise one.
_OF_THIS_LAW = r"(?:\s*,?\s*of\s+(?:this|the\s+present)\s+(?:Law|Act|Regulation|Order|Decree))?"

# Instrument citations: "Law No. 30 of 2018", "Regulation (EU) 2016/679",
# "Decree-Law No. 16 of 2014".
_LAW_CITATION = (
    r"(?:Decree[-\s]?Law|Law|Act|Regulation|Directive|Order|Decision|Resolution|Circular)"
    r"\s*(?:No\.?|Number|n[°º])?\s*"
    r"(?:\(\s*(?:EU|EC|E\.?U\.?)\s*\)\s*)?"
    r"(?P<lawnum>\d{1,4}(?:\s*/\s*\d{2,4})?)"
    r"(?:\s*(?:of|,)\s*(?:the\s+year\s+)?(?P<lawyear>\d{4}))?"
)

# ── false-positive guards ───────────────────────────────────────────────────
#
# Applied as lookaheads at the point of match. Each one exists because the
# construct genuinely occurs in regulatory prose and is NOT a provision
# reference:
#   "Article 5%"            a percentage that happens to follow the word
#   "Section 2.5"           document-structure numbering, not a statutory
#                           provision — decimal numbering is a drafting
#                           convention, and treating it as a citation invents
#                           links between unrelated policy headings
#   "paragraph 3 of the sentence"   points inside prose, not at a provision
_NOT_PERCENT   = r"(?!\s*%)"
_NOT_DECIMAL   = r"(?!\s*\.\s*\d)"
_NOT_PROSE_TARGET = (
    r"(?!\s+of\s+(?:the|this)\s+"
    r"(?:sentence|phrase|table|figure|annex\s+table|preceding\s+sentence|"
    r"foregoing\s+sentence|above\s+sentence))"
)
_GUARDS = _NOT_PERCENT + _NOT_DECIMAL + _NOT_PROSE_TARGET


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _norm_num(raw: str) -> str:
    """'  07 ' -> '7'; '67b' -> '67B'. Leading zeros dropped so 'Article 07'
    and 'Article 7' normalise to the same target."""
    s = (raw or "").strip()
    m = re.match(r"^0*(\d+)\s*([A-Za-z]?)$", s)
    if not m:
        return s.upper()
    return m.group(1) + m.group(2).upper()


# ── patterns, in priority order ─────────────────────────────────────────────
#
# Order is load-bearing. Compound forms must match BEFORE their parts, or
# "Paragraph (2) of Article (34)" files two references — a paragraph and an
# article — instead of the one reference it actually is. Overlap suppression
# in detect_references() enforces the priority: once a span is consumed, no
# later pattern may match inside it.

_PATTERNS: list[tuple[str, str]] = [

    # 1. Provision of an EXTERNAL instrument.
    #    "Article 5 of Law No. 30 of 2018", "Article 6 of Regulation (EU) 2016/679"
    ("article_of_law",
     r"\b(?P<kind>Articles?|Sections?|Clauses?)\s*\(?\s*(?P<num>" + _N + r")(?:\s*\))?"
     + _GUARDS +
     r"(?:\s*\(\s*(?P<sub>\d{1,3}[a-z]?)\s*\))?"
     r"\s*,?\s*of\s+(?:the\s+)?(?P<law>" + _LAW_CITATION + r")"),

    # 2. Compound: a paragraph OF a numbered article.
    #    "Paragraph (2) of Article (34) of this Law"
    ("paragraph_of_article",
     r"\b(?:Paragraphs?|Clauses?|Items?)\s*\(?\s*(?P<sub>\d{1,3}[a-z]?)(?:\s*\))?"
     r"\s*,?\s*of\s+(?:the\s+)?Articles?\s*\(?\s*(?P<num>" + _N + r")(?:\s*\))?"
     + _OF_THIS_LAW),

    # 3. Compound relative: a paragraph of the article the text sits in.
    #    "Paragraph (1) of this Article"
    ("paragraph_of_this_article",
     r"\b(?:Paragraphs?|Clauses?|Items?)\s*\(?\s*(?P<sub>\d{1,3}[a-z]?)(?:\s*\))?"
     r"\s*,?\s*of\s+this\s+(?P<kind>Article|Section|Clause)"),

    # 4. Inclusive range. Plural "Articles" OR an explicit "to"/"through" is
    #    required: a bare hyphen between two numbers is not a citation.
    #    "Articles 31 to 35", "Articles 31-35", "Article 31 through 35"
    ("range",
     r"\b(?P<kind>Articles|Sections|Paragraphs|Clauses|Schedules)\s*\(?\s*(?P<lo>" + _N + r")(?:\s*\))?"
     r"\s*(?:to|through|[-‐-―])\s*\(?\s*(?P<hi>" + _N + r")(?:\s*\))?"
     + _OF_THIS_LAW),
    ("range_singular_to",
     r"\b(?P<kind>Article|Section|Paragraph|Clause|Schedule)\s*\(?\s*(?P<lo>" + _N + r")(?:\s*\))?"
     r"\s*(?:to|through)\s*\(?\s*(?P<hi>" + _N + r")(?:\s*\))?"
     + _OF_THIS_LAW),

    # 5. Article with a spelled-out subsection.
    #    "Article 31 paragraph 2", "Article (4) paragraphs (1)"
    ("article_with_paragraph",
     r"\b(?P<kind>Articles?|Sections?)\s*\(?\s*(?P<num>" + _N + r")(?:\s*\))?"
     + _GUARDS +
     r"\s*,?\s*(?:paragraphs?|clauses?|items?)\s*\(?\s*(?P<sub>\d{1,3}[a-z]?)(?:\s*\))?"
     + _OF_THIS_LAW),

    # 6. Plain provision, optional bracketed subsection.
    #    "Article 31", "Article (10) of this Law", "Article 31(2)"
    ("plain",
     r"\b(?P<kind>Articles?|Sections?|Clauses?|Schedules?|Paragraphs?|Rules?|Regulations?)"
     r"\s*\(?\s*(?P<num>" + _N + r")(?:\s*\))?"
     + _GUARDS +
     r"(?:\s*\(\s*(?P<sub>\d{1,3}[a-z]?)\s*\))?"
     + _OF_THIS_LAW),

    # 7. Relative designations, resolvable only from position.
    ("relative",
     r"\b(?:the\s+)?(?P<rel>preceding|previous|foregoing|following|next|succeeding|present|this)"
     r"\s+(?P<kind>Article|Section|Clause|Paragraph|Schedule)\b"),

    # 8. The instrument itself. Only reached when not already consumed as the
    #    tail of a provision reference, so "Article (10) of this Law" does NOT
    #    also file a bare "this Law".
    ("this_law",
     r"\b(?:this|the\s+present)\s+(?P<kind>Law|Act|Regulation|Decree)\b"),

    # 9. A named external instrument with no provision attached.
    ("law_citation",
     r"\b(?P<law>" + _LAW_CITATION + r")"),
]

_COMPILED = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in _PATTERNS]

_KIND_BY_WORD = {
    "article": KIND_ARTICLE, "articles": KIND_ARTICLE,
    "section": KIND_SECTION, "sections": KIND_SECTION,
    "clause": KIND_CLAUSE,   "clauses": KIND_CLAUSE,
    "paragraph": KIND_PARAGRAPH, "paragraphs": KIND_PARAGRAPH,
    "schedule": KIND_SCHEDULE,   "schedules": KIND_SCHEDULE,
    "rule": KIND_SECTION, "rules": KIND_SECTION,
    "regulation": KIND_SECTION, "regulations": KIND_SECTION,
    "law": KIND_LAW, "act": KIND_LAW, "decree": KIND_LAW,
}

_RELATIVE_BY_WORD = {
    "preceding": REL_PRECEDING, "previous": REL_PRECEDING, "foregoing": REL_PRECEDING,
    "following": REL_FOLLOWING, "next": REL_FOLLOWING, "succeeding": REL_FOLLOWING,
    "this": REL_SELF, "present": REL_SELF,
}

# Confidence by construct. An explicitly numbered citation is as certain as
# regex gets; a relative designation is certain in its READING but says
# nothing about whether a target exists, and a bare instrument name is the
# weakest signal here.
_CONFIDENCE = {
    "article_of_law": 0.95, "paragraph_of_article": 0.95,
    "paragraph_of_this_article": 0.85, "range": 0.9, "range_singular_to": 0.9,
    "article_with_paragraph": 0.92, "plain": 0.95,
    "relative": 0.7, "this_law": 0.6, "law_citation": 0.8,
}


def _kind_of(word: str, default: str = KIND_UNKNOWN) -> str:
    return _KIND_BY_WORD.get((word or "").strip().lower(), default)


def detect_references(text: str) -> list[DetectedReference]:
    """Every legal reference in `text`, in order of appearance.

    Patterns are applied in priority order and each match CONSUMES its span,
    so a compound form is recorded once rather than being shredded into its
    parts by a later, simpler pattern.

    Returns [] for empty text. Never raises — a detector that throws on odd
    input would take the requirement down with it, and the requirement is the
    thing that must survive.
    """
    body = text or ""
    if not body.strip():
        return []

    consumed: list[tuple[int, int]] = []

    def overlaps(a: int, b: int) -> bool:
        return any(a < end and b > start for start, end in consumed)

    found: list[DetectedReference] = []
    for name, rx in _COMPILED:
        for m in rx.finditer(body):
            if overlaps(m.start(), m.end()):
                continue
            ref = _build(name, m, body)
            if ref is None:
                continue
            consumed.append((m.start(), m.end()))
            found.append(ref)

    found.sort(key=lambda r: r.start)
    return found


def _build(name: str, m: re.Match, body: str) -> DetectedReference | None:
    """Turn one regex match into a DetectedReference, or None to discard it."""
    groups   = m.groupdict()
    ref_text = _clean(m.group(0))
    if not ref_text:
        return None

    law_raw  = _clean(groups.get("law") or "")
    law_num  = re.sub(r"\s+", "", groups.get("lawnum") or "")
    law_year = (groups.get("lawyear") or "").strip()

    # An external instrument is named -> the reference leaves this document.
    if law_raw:
        scope = SCOPE_EXTERNAL
    elif re.search(r"of\s+(?:this|the\s+present)\s+(?:Law|Act|Regulation|Order|Decree)\s*$",
                   ref_text, re.IGNORECASE):
        scope = SCOPE_INTERNAL
    elif name in ("paragraph_of_this_article", "relative", "this_law"):
        scope = SCOPE_INTERNAL
    else:
        # A bare "Article 31" is PROBABLY internal, but probably is not a fact.
        # Left unknown; resolution upgrades it only if it actually resolves
        # inside this document.
        scope = SCOPE_UNKNOWN

    conf = _CONFIDENCE.get(name, 0.7)

    if name in ("range", "range_singular_to"):
        lo, hi = _norm_num(groups["lo"]), _norm_num(groups["hi"])
        if not (lo.isdigit() and hi.isdigit()) or int(hi) <= int(lo):
            # "Articles 35 to 31" is not a range anyone drafted; a descending
            # or non-numeric pair is far likelier to be prose than a citation.
            return None
        return DetectedReference(
            ref_text=ref_text, ref_kind=_kind_of(groups["kind"], KIND_ARTICLE),
            ref_number=f"{lo}-{hi}", scope=scope, confidence=conf,
            start=m.start(), end=m.end())

    if name == "relative":
        rel = _RELATIVE_BY_WORD.get((groups["rel"] or "").lower())
        if rel is None:
            return None
        return DetectedReference(
            ref_text=ref_text, ref_kind=_kind_of(groups["kind"], KIND_ARTICLE),
            ref_number=rel, scope=scope, confidence=conf,
            start=m.start(), end=m.end())

    if name == "paragraph_of_this_article":
        # "Paragraph (1) of this Article" — the target article is wherever the
        # text sits, so it is a SELF reference carrying a subsection.
        sub = _norm_num(groups.get("sub") or "")
        return DetectedReference(
            ref_text=ref_text, ref_kind=KIND_PARAGRAPH,
            ref_number=f"{REL_SELF}({sub})" if sub else REL_SELF,
            scope=scope, confidence=conf,
            start=m.start(), end=m.end())

    if name == "this_law":
        return DetectedReference(
            ref_text=ref_text, ref_kind=KIND_LAW, ref_number="",
            scope=SCOPE_INTERNAL, confidence=conf,
            start=m.start(), end=m.end())

    if name == "law_citation":
        return DetectedReference(
            ref_text=ref_text, ref_kind=KIND_LAW, ref_number="",
            scope=SCOPE_EXTERNAL, confidence=conf, law_citation=law_raw,
            law_number=law_num, law_year=law_year,
            start=m.start(), end=m.end())

    # Remaining: plain / article_with_paragraph / paragraph_of_article /
    # article_of_law — all a numbered provision, optionally with a subsection.
    num = _norm_num(groups.get("num") or "")
    if not num:
        return None
    sub = _norm_num(groups.get("sub") or "")
    ref_number = f"{num}({sub})" if sub else num
    kind = _kind_of(groups.get("kind") or "", KIND_ARTICLE)
    if name == "paragraph_of_article":
        # The TARGET is the article; the paragraph narrows within it. Recorded
        # as an article reference so resolution looks in the article index.
        kind = KIND_ARTICLE

    return DetectedReference(
        ref_text=ref_text, ref_kind=kind, ref_number=ref_number, scope=scope,
        confidence=conf, law_citation=law_raw, law_number=law_num,
        law_year=law_year, start=m.start(), end=m.end())


# ── article-number extraction from stored chunk metadata ────────────────────

# `article_ref` as the chunker writes it. Real values in the corpus include
# "Article (7) Processing of data ...", "Article (4)", "Preamble", "Section_1",
# "First Article", "CHAPTER XIII - MISCELLANEOUS" and "67B. Punishment for ...".
# Only the numbered forms can anchor a reference, so everything else yields
# no number and simply never becomes a resolution target.
_ARTICLE_IN_REF = re.compile(
    r"\b(?:Article|Section|Clause|Regulation|Rule)\s*\(?\s*(\d{1,4}[A-Za-z]?)(?:\s*\))?",
    re.IGNORECASE)
_LEADING_NUMBER = re.compile(r"^\s*(\d{1,4}[A-Za-z]?)\s*[.)]")


def article_number_of(article_ref: str) -> str:
    """The provision number an indexed chunk sits under, or ''.

    '' is the honest answer for "Preamble", "First Article" and
    "CHAPTER XIII - MISCELLANEOUS": they carry no number, so nothing can cite
    them by number, so they never become a resolution target. Returning a
    guess for them is precisely how a wrong link would get created.
    """
    ref = (article_ref or "").strip()
    if not ref:
        return ""
    m = _ARTICLE_IN_REF.search(ref)
    if m:
        return _norm_num(m.group(1))
    m = _LEADING_NUMBER.match(ref)
    if m:
        return _norm_num(m.group(1))
    return ""
