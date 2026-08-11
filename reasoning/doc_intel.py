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
import logging
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import OLLAMA_URL  # noqa: E402

import ollama  # noqa: E402

logger = logging.getLogger(__name__)

MODEL = "qwen2.5:7b"

# Title / authority / law number / date live in the first pages, so the pass that
# extracts them reads the front. This is NOT the whole story — see scan_document,
# which reads every window of the document.
_HEAD_CHARS = 6000

# Ollama defaults num_ctx to 4096 regardless of what the model was trained for
# (qwen2.5:7b supports 32k). Ollama TRUNCATES an over-long prompt silently rather
# than erroring, so running on that default produced confident answers about
# documents whose second half the model never saw. Pin it explicitly. 8192
# matches what the reasoning layer already runs (cfg.llm.fallback_num_ctx), so it
# is a context size this GPU is known to hold; raise it on bigger hardware and
# the sweep below widens to match.
_NUM_CTX = 8192

# Whole-document sweep. Window size is DERIVED from the context so the two can
# never drift apart: raise _NUM_CTX and the windows widen with it, rather than
# the sweep quietly overflowing a context someone forgot to widen too.
# Reserve ~1200 tokens for the prompt frame and the JSON answer; budget 2.8
# chars/token, well under English prose (~4) so token-dense passages — tables,
# citation strings, Arabic — still fit.
_TOKENS_RESERVED = 1200
_CHARS_PER_TOKEN = 2.8
_WINDOW_CHARS = int((_NUM_CTX - _TOKENS_RESERVED) * _CHARS_PER_TOKEN)
# Overlap so a sentence naming the regulator isn't split across a boundary and
# lost to both windows.
_WINDOW_OVERLAP = 1000


def _client() -> "ollama.Client":
    # A timeout is essential: without one, a stalled/overloaded Ollama makes the
    # analyze request hang forever and the wizard spinner never resolves. With it,
    # a slow call fails cleanly → _chat_json returns {} → the upload degrades to
    # "no suggestion" instead of freezing.
    return ollama.Client(host=OLLAMA_URL, timeout=120)


def _chat_json(prompt: str, model: str = MODEL) -> dict:
    """One local chat call, forced to JSON. Returns {} on any failure so a bad
    model response degrades to 'no suggestion' rather than crashing the upload."""
    try:
        resp = _client().chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0, "num_ctx": _NUM_CTX},
        )
        return json.loads(resp["message"]["content"])
    except Exception:
        # Degrade to "no suggestion" rather than crash the upload — but never
        # silently: a swallowed error here is indistinguishable from a document
        # the model had nothing to say about, which makes a broken Ollama look
        # like a boring document.
        logger.exception("doc-intel: local model call failed")
        return {}


_METADATA_PROMPT = """You are a legal/compliance document cataloguer preparing a
document for a RETRIEVAL system used by a bank's compliance, risk and legal
teams. Read the opening of a regulation or internal policy and extract metadata
that makes it easy to FILTER, FIND, and CITE later. Use ONLY what the text states
— never invent a number, date, authority, or fact. If a field is not present,
return an empty string "" (or [] for the list fields).

Return a JSON object with EXACTLY these keys:
- "name": short human title, e.g. "PDPA Order 43/2022" or "Group Privacy Policy"
- "full_name": the official full title as printed
- "doc_type": "regulation" (a law / regulation / circular issued by an authority)
  or "policy" (an internal bank policy / SOP / procedure / guideline)
- "jurisdiction": the country/region whose law the document is issued under or
  governs, as a lowercase slug. Use the REAL country, whatever it is — you are
  NOT limited to any list. Decide ONLY from explicit evidence in the text: the
  issuing authority, a registered office or postal address, a named national law,
  or a named regulator. If the text names no country, return "" — an empty string
  is CORRECT and expected. Never guess a country, and never copy a country from
  these instructions.
- "regulation_category": the subject area, lowercase, e.g. "data protection",
  "cybersecurity","aml/kyc","banking","privacy","electronic transactions",
  "internal controls","risk management"
- "privacy_relevance": how central personal-data / privacy is to this document —
  "high" (the document is fundamentally about data protection / privacy),
  "partial" (privacy is one of several topics it covers), or
  "low" (barely or not privacy-related). Judge from the actual content.
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


# Country → substrings that reliably signal it. Kept deliberately conservative
# (well-known names/authorities) so inference only fires on a clear signal.
_COUNTRY_HINTS = {
    "bahrain": ["bahrain"],
    "kuwait":  ["kuwait"],
    "qatar":   ["qatar"],
    "saudi":   ["saudi", "kingdom of saudi", "ksa"],
    "uae":     ["united arab emirates", "u.a.e", "abu dhabi", "dubai"],
    "oman":    ["sultanate of oman", "oman"],
    "egypt":   ["egypt", "egyptian"],
    "india":   ["republic of india", "indian ", "india"],
    "jordan":  ["jordan"],
    "lebanon": ["lebanon", "lebanese"],
    "turkey":  ["turkey", "turkish", "türkiye"],
    # A national regulator or a national data-protection act is the strongest
    # signal a privacy/finance document carries, so name them alongside the
    # country itself — many EU policies say "France"/"CNIL" but never "français".
    "france":  ["france", "french", "cnil", "république française"],
    "germany":  ["germany", "german federal", "bundesdatenschutz", "bafin"],
    "spain":    ["spain", "spanish", "aepd"],
    "italy":    ["italy", "italian", "garante"],
    "ireland":  ["ireland", "irish"],
    "netherlands": ["netherlands", "dutch"],
    "belgium":  ["belgium", "belgian"],
    "eu":      ["european union", "european parliament", "regulation (eu)", "gdpr"],
    "uk":      ["united kingdom", "u.k.", "great britain"],
    "usa":     ["united states", "u.s.a", "federal register"],
}


# The model writes a country however it likes — "European Union", "Kingdom of
# Bahrain", "United States of America" — which slugify to values the corpus does
# not use, so the same jurisdiction splits into rival candidates and the library
# grows a "europeanunion" alongside its "eu". Fold the spellings onto the slug
# the rest of the app filters on.
_SLUG_ALIASES = {
    "europeanunion": "eu", "europe": "eu", "europeancommission": "eu",
    "europeanparliament": "eu", "ec": "eu",
    "unitedstates": "usa", "unitedstatesofamerica": "usa", "us": "usa",
    "unitedkingdom": "uk", "greatbritain": "uk", "england": "uk",
    "saudiarabia": "saudi", "kingdomofsaudiarabia": "saudi", "ksa": "saudi",
    "unitedarabemirates": "uae",
    "kingdomofbahrain": "bahrain", "sultanateofoman": "oman",
    "stateofqatar": "qatar", "stateofkuwait": "kuwait",
    "republicofindia": "india", "bharat": "india",
    "frenchrepublic": "france", "republicoffrance": "france",
    "turkiye": "turkey", "arabrepublicofegypt": "egypt",
}


def _canonical_slug(slug: str) -> str:
    """Fold a model-written country name onto the corpus's slug for it."""
    return _SLUG_ALIASES.get(slug, slug)


def _infer_jurisdiction(blob: str) -> str:
    """Best-guess country slug from free text (issuing authority, title, scope).
    Returns '' when nothing matches confidently. Picks the country with the most
    keyword hits so a stray mention doesn't outweigh the real jurisdiction."""
    b = (blob or "").lower()
    best, best_n = "", 0
    for slug, kws in _COUNTRY_HINTS.items():
        n = sum(b.count(k) for k in kws)
        if n > best_n:
            best, best_n = slug, n
    return best


def _is_grounded(slug: str, blob: str) -> bool:
    """Is `slug` actually EVIDENCED anywhere in the document text?

    The local 7B model will state a jurisdiction with high confidence that
    appears nowhere in the document — it answered "bahrain" for a French GDPR
    privacy policy, anchored on a country name that was only ever an example in
    the prompt. Confidence is no signal, so the country is checked against the
    text instead: a jurisdiction that cannot be pointed at in the document is
    not a jurisdiction, it is a guess.
    """
    if not slug or not blob:
        return False
    b = blob.lower()
    kws = _COUNTRY_HINTS.get(slug)
    if kws:
        return any(k in b for k in kws)
    # A country the hint table doesn't know (the table is deliberately partial —
    # see extract_metadata: an unseen jurisdiction must still be able to flow
    # through). Accept it only if the document names it outright.
    words = re.sub(r"[^a-z0-9]+", " ", b)
    if re.search(rf"\b{re.escape(slug)}\b", words):
        return True
    # Multi-word countries arrive slugified ("costa rica" -> "costarica"), so
    # also join ADJACENT words and compare. Only adjacent runs — searching a
    # de-spaced copy of the whole document would match across unrelated word
    # boundaries, so "oman" would be found inside "R-oman-ia".
    toks = words.split()
    joined = {"".join(toks[i:i + k])
              for k in (2, 3) for i in range(len(toks) - k + 1)}
    return slug in joined


def _meta_sample(text: str, head: int = _HEAD_CHARS, tail: int = 3000) -> str:
    """Front-weighted sample for metadata extraction.

    Title, authority and law number live up front, so the head still dominates.
    But jurisdiction often does NOT: a policy can run for pages of generic
    privacy prose before naming the company's registered office, its governing
    law and its regulator. Reading only the head made the model infer a country
    from a document in which no country had yet appeared. The tail carries that
    signature block, so it is included.
    """
    t = (text or "").strip()
    if len(t) <= head + tail:
        return t
    return f"{t[:head]}\n[…]\n{t[-tail:]}"


_SWEEP_PROMPT = """You are scanning ONE EXCERPT of a longer legal / compliance
document. Report ONLY what THIS excerpt actually shows. Never guess, and never
carry over knowledge about similar documents.

Return a JSON object with EXACTLY these keys:
- "jurisdiction": the country or region whose law this excerpt shows the document
  is issued under or governs, as a lowercase slug. Give a value ONLY if THIS
  excerpt contains explicit evidence: an issuing authority, a registered office
  or postal address, a named national law, or a named regulator. If this excerpt
  shows no such evidence, return "" — that is the expected answer for most
  excerpts, and it is CORRECT. Never copy a country from these instructions.
- "jurisdiction_evidence": the exact phrase from the excerpt that proves it,
  copied VERBATIM from the text. "" when jurisdiction is "".
- "regulation_category": the subject area of this excerpt, lowercase, or ""
- "privacy_relevance": how central personal-data / privacy is to THIS excerpt —
  "high", "partial", or "low"
- "key_topics": 0-5 short lowercase subject tags for what this excerpt covers
- "full_name": the document's official full title, if THIS excerpt prints it, else ""
- "issuing_authority": WHOSE document this is. For a law or circular that is the
  issuing regulator ("Central Bank of Bahrain"). For a company policy, privacy
  notice or procedure it is THE COMPANY ITSELF — the controller, the entity that
  published it, the business named in the registration or signature block
  ("LinkCy SAS", "BBK"). A company policy is not authority-less: name the
  company. "" only when this excerpt names no such body.
- "document_id": the law / order / decision / policy number, digits only, if
  THIS excerpt states one, else ""
- "doc_year": 4-digit year of issuance, if THIS excerpt states one, else ""
- "effective_date": ISO YYYY-MM-DD if THIS excerpt states an effective /
  commencement date, else ""
- "version": the document version if THIS excerpt states one, else ""
- "owner_department": for an internal policy, the owning department if THIS
  excerpt names one, else ""

Copy these values from the excerpt. Do not paraphrase a title, do not infer a
year from context, and do not name an authority the excerpt does not mention.

Excerpt {i} of {n}:
---
{body}
---
JSON:"""

_RELEVANCE_RANK = {"low": 0, "partial": 1, "high": 2}

# How strongly a phrase evidences the document's OWN jurisdiction. Counting
# mentions gets this backwards: a Bahraini regulation that cites the GDPR
# throughout collects more "eu" windows than "bahrain" ones, and would be filed
# under the wrong regulator. What matters is the KIND of statement the country
# appeared in, not how often it appeared.
_EVIDENCE_TIERS = (
    (4, ("issued by", "central bank", "ministry", "authority", "commission",
         "regulator", "supervisory", "agency", "bureau", "council", "we, ",
         "king of", "amir", "sultan", "president of", "governor")),
    (3, ("law no", "decree", "royal", "pursuant to", "in accordance with",
         "governed by", "under the law", "legislation", "data protection act",
         "applicable laws", "competent authorit")),
    (2, ("registered office", "registered with", "head office", "headquarters",
         "trade and companies register", "registered in", "rue ", "street",
         "avenue", "p.o. box", "postal")),
)
# Phrases that mark a country as somewhere the document POINTS AT rather than
# somewhere it comes from — a foreign law it cites, a destination for transfers.
_FOREIGN_REFERENCE = (
    "such as", "outside", "transfer", "adequacy", "equivalent", "similar to",
    "for example", "third country", "other countries", "e.g.",
)


# A citation of a named instrument — "Regulation (EU) 2016/679", "Law No. 30 of
# 2018", "Directive 2002/58/EC". These name legislatures ("the European
# Parliament and of the Council"), so they trip the authority keywords below and
# score as though the document were ISSUED by that body. It is the difference
# between a law a document is made under and a law it merely complies with, and
# it is why a French policy citing the GDPR was being filed as an EU document.
_LAW_CITATION = re.compile(
    r"(?i)\b(regulation|directive|law|act|decree|order|ordinance|code)\b"
    r"[^.]{0,40}?(\(eu\)|no\.?\s*\d|\d{2,4}\s*/\s*\d{2,4}|\d+\s+of\s+\d{4})")


def _evidence_tier(phrase: str) -> int:
    """Rate a phrase as evidence of the document's own jurisdiction.

    4 = the body that issued it      3 = the law it is made under
    2 = a registered office/address  1 = an incidental mention
    0 = a reference to somewhere ELSE (a foreign law it merely cites)
    """
    p = (phrase or "").lower()
    if not p:
        return 0
    if any(k in p for k in _FOREIGN_REFERENCE):
        return 0
    # Tested BEFORE the authority keywords: a law citation that happens to name a
    # parliament is evidence of a governing instrument, not of an issuing body.
    if _LAW_CITATION.search(p):
        return 3
    for tier, kws in _EVIDENCE_TIERS:
        if any(k in p for k in kws):
            return tier
    return 1


def _rank_jurisdiction(votes: Counter, evidence: dict) -> tuple:
    """Resolve one jurisdiction from the per-window findings.

    Ordered by the STRENGTH of each country's best evidence; the window count
    only breaks ties between countries evidenced equally well. A country whose
    every mention was a pointer somewhere else (tier 0) is not a candidate at
    all — that is the GDPR-citation case, and it is the whole reason this does
    not simply take the most-mentioned country.
    """
    if not votes:
        return "", []
    ranked = sorted(
        ((slug, _evidence_tier(evidence.get(slug, "")), n)
         for slug, n in votes.items()),
        key=lambda r: (r[1], r[2]), reverse=True)
    best = ranked[0][0] if ranked[0][1] > 0 else ""
    return best, [{"jurisdiction": s, "tier": t, "windows": n}
                  for s, t, n in ranked]

# Fields the sweep reports as a single fact about the document. The first window
# that evidences one wins: a title, authority, number or date is printed at the
# point the document introduces itself, and a later restatement is usually a
# running header or a cross-reference.
_SWEEP_FACTS = ("full_name", "issuing_authority", "document_id", "doc_year",
                "effective_date", "version", "owner_department")


def _value_grounded(val: str, window: str) -> bool:
    """Is this free-text value actually present in the window it came from?

    The same failure as the jurisdiction one, in the other fields: a model asked
    for an issuing authority will supply a plausible one rather than "". Every
    substantive word has to appear in the text the model was shown, so a
    paraphrase survives but an invention does not. Digits must match exactly —
    a law number or year is worthless if it is approximately right.
    """
    v = (val or "").strip()
    if not v:
        return False
    w = window.lower()
    digits = re.findall(r"\d+", v)
    if digits and not all(d in window for d in digits):
        return False
    words = [t for t in re.findall(r"[a-z]{4,}", v.lower())]
    if not words:
        return bool(digits)          # pure number/date: the digit check settled it
    return all(t in w for t in words)


class AnalysisCancelled(Exception):
    """Raised by a progress callback to abandon an analysis in flight.

    Cancellation rides the progress callback rather than a separate channel:
    progress is already reported after every model call, which is exactly where
    it is safe to stop — between calls, never mid-call. A caller whose client
    has gone away raises this from its callback and the scan unwinds.
    """


def _emit(progress, done: int, total: int, label: str) -> None:
    """Report one completed step to a progress callback.

    The contract is progress(done, total, label): `done` counts COMPLETED model
    calls and `total` is every call the whole analysis will make, so the caller
    can render a percentage that reaches 100% exactly when the work ends.
    Reporting is best-effort — a failing progress callback must never take down
    an analysis that is otherwise succeeding — with one exception, AnalysisCancelled,
    which is the callback deliberately asking to stop and must not be swallowed.
    """
    if not progress:
        return
    try:
        progress(done, total, label)
    except AnalysisCancelled:
        raise
    except Exception:
        logger.debug("progress callback failed", exc_info=True)


def _windows(text: str, size: int = _WINDOW_CHARS,
             overlap: int = _WINDOW_OVERLAP) -> list[str]:
    """Split the document into overlapping windows that each fit the context."""
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= size:
        return [t]
    out, start, step = [], 0, max(1, size - overlap)
    while start < len(t):
        out.append(t[start:start + size])
        if start + size >= len(t):
            break
        start += step
    return out


def scan_document(text: str, progress=None,
                  step_offset: int = 0, step_total: int = 0) -> dict:
    """Read EVERY window of the document and aggregate what the model finds.

    The head pass (extract_metadata) reads the front, where the title and issuing
    authority live. That is not enough to characterise a document: jurisdiction,
    subject and privacy relevance can be established anywhere — a policy can run
    for pages of generic prose before it names its governing law and regulator.
    So this reads the whole thing, window by window, and reduces the results.

    Each window is judged on its OWN evidence: a window claiming a country is
    only counted when that country is grounded in that window's text, so one
    window cannot assert a jurisdiction the document never mentions. Countries
    are then ranked by how many windows independently evidence them.

    `progress` is an optional callable(done, total, label) — see _emit. The scan
    is usually one phase of a larger analysis, so `step_offset` / `step_total`
    let the caller place these windows inside a whole-analysis count; left at 0
    the windows are reported on their own.
    Returns {} when there is nothing to read.
    """
    wins = _windows(text)
    total = len(wins)
    if not total:
        return {}
    overall = step_total or total

    juris: Counter = Counter()
    evidence: dict[str, str] = {}
    topics: Counter = Counter()
    cats: Counter = Counter()
    rel: Counter = Counter()
    facts: dict[str, str] = {}       # first grounded value wins, front to back
    failed = 0

    for i, w in enumerate(wins, 1):
        d = _chat_json(_SWEEP_PROMPT.replace("{body}", w)
                       .replace("{i}", str(i)).replace("{n}", str(total)))
        # Reported AFTER the call returns, not before it starts: `done` has to
        # mean work finished, or the bar claims the last window is complete
        # while the model is still busy on it.
        _emit(progress, step_offset + i, overall,
              f"Reading section {i} of {total}")
        if not isinstance(d, dict) or not d:
            failed += 1                    # a stalled/malformed window is skipped,
            continue                       # never fatal — the rest still counts
        j = _canonical_slug(
            re.sub(r"[^a-z0-9]+", "", str(d.get("jurisdiction") or "").lower()))
        # Grounded against THIS window, not the whole document: the claim has to
        # be supported by the text the model was actually shown.
        if j and j != "other" and _is_grounded(j, w):
            juris[j] += 1
            ev = str(d.get("jurisdiction_evidence") or "").strip()
            if ev and j not in evidence:
                evidence[j] = ev[:200]
        c = str(d.get("regulation_category") or "").strip().lower()
        if c:
            cats[c] += 1
        r = str(d.get("privacy_relevance") or "").strip().lower()
        if r in _RELEVANCE_RANK:
            rel[r] += 1
        kt = d.get("key_topics") or []
        for t in ([kt] if isinstance(kt, str) else kt):
            t = re.sub(r"\s+", " ", str(t or "")).strip().lower()
            if t:
                topics[t] += 1
        # Single-fact fields: keep the first window that supplies a value the
        # window itself backs up. Checked against THIS window, so a fact can only
        # come from text the model actually read.
        for key in _SWEEP_FACTS:
            if key in facts:
                continue
            v = str(d.get(key) or "").strip()
            if v and _value_grounded(v, w):
                facts[key] = v

    read = total - failed
    if failed:
        logger.warning("doc scan: %d/%d windows failed to parse", failed, total)

    # "high" means privacy is what the document IS about, so it takes a real
    # share of the document reading that way — not one emphatic window.
    if read and rel.get("high", 0) / read >= 0.4:
        relevance = "high"
    elif rel.get("high") or rel.get("partial"):
        relevance = "partial"
    elif rel:
        relevance = "low"
    else:
        relevance = ""

    # Jurisdiction is resolved by EVIDENCE STRENGTH, not by how many windows
    # mentioned a country — see _rank_jurisdiction. A regulation that cites the
    # GDPR on twenty pages must not be filed as an EU document because of it.
    best, ranked = _rank_jurisdiction(juris, evidence)

    out = {
        "jurisdiction": best,
        "jurisdiction_votes": dict(juris),
        "jurisdiction_evidence": evidence.get(best, ""),
        "jurisdiction_ranked": ranked,
        "regulation_category": cats.most_common(1)[0][0] if cats else "",
        "privacy_relevance": relevance,
        "key_topics": [t for t, _ in topics.most_common(6)],
        "windows_total": total,
        "windows_read": read,
        "chars_read": len((text or "").strip()),
    }
    out.update({k: v for k, v in facts.items()})
    return out


def metadata_steps(text: str, full_scan: bool = True) -> int:
    """How many model calls extract_metadata will make on this text.

    Lets a caller compute the total for a whole analysis BEFORE starting, so the
    progress bar has a fixed denominator instead of one that grows as phases are
    discovered. One head pass, plus one call per sweep window.
    """
    if not (text or "").strip():
        return 0
    return 1 + (len(_windows(text.strip())) if full_scan else 0)


def extract_metadata(text: str, filename: str = "", full_scan: bool = True,
                     progress=None, step_offset: int = 0,
                     step_total: int = 0) -> dict:
    """Propose bibliographic metadata for a document.

    Two passes. The HEAD pass reads the front of the document for the fields that
    genuinely live there — title, issuing authority, law number, dates. The SWEEP
    pass (scan_document) then reads EVERY window of the document and votes on the
    fields that can only be judged from the whole of it: jurisdiction, subject,
    privacy relevance and topics. The sweep costs one model call per ~20k chars,
    so `full_scan=False` is available for callers that need the cheap head-only
    answer; analyze runs the full scan.

    Returns a dict with the keys listed in the prompt (+ 'confidence' and the
    'scan' telemetry), or {} if extraction failed. Values are suggestions for the
    user to confirm."""
    full = (text or "").strip()
    head = _meta_sample(full)
    if not head:
        return {}
    overall = step_total or metadata_steps(full, full_scan)
    # replace, not .format(): the structure prompt contains literal { } JSON
    # braces; use the same substitution style here for consistency + safety.
    data = _chat_json(_METADATA_PROMPT.replace("{head}", head))
    # The head pass is a full model call — ~15s — and used to be invisible to
    # progress, so the bar sat at zero through it and then jumped. It counts.
    _emit(progress, step_offset + 1, overall, "Detecting metadata")
    if not isinstance(data, dict):
        return {}
    # normalise: keep only known keys, coerce types, clamp confidence
    keys = ["name", "full_name", "doc_type", "jurisdiction", "regulation_category",
            "issuing_authority", "document_id", "doc_year", "effective_date",
            "version", "citation_abbr", "scope_summary", "owner_department",
            "privacy_relevance"]
    out = {k: str(data.get(k, "") or "").strip() for k in keys}
    # privacy_relevance: constrain to the three allowed buckets (else blank).
    pr = out.get("privacy_relevance", "").lower()
    out["privacy_relevance"] = pr if pr in ("high", "partial", "low") else ""
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

    # ---- SWEEP: read the rest of the document, not just the front ----------
    # The head pass consumed step_offset+1, so the windows continue from there.
    scan = scan_document(full, progress=progress,
                         step_offset=step_offset + 1,
                         step_total=overall) if full_scan else {}
    if scan:
        out["scan"] = {k: scan[k] for k in
                       ("windows_total", "windows_read", "chars_read",
                        "jurisdiction_votes", "jurisdiction_evidence")}
        # Whole-document fields: the sweep saw every page, the head pass saw the
        # front, so the sweep wins wherever it produced an answer.
        if scan.get("privacy_relevance"):
            out["privacy_relevance"] = scan["privacy_relevance"]
        if scan.get("key_topics"):
            merged = list(scan["key_topics"])
            merged += [t for t in out["key_topics"] if t not in merged]
            out["key_topics"] = merged[:6]
        if not out["regulation_category"] and scan.get("regulation_category"):
            out["regulation_category"] = scan["regulation_category"]
        # Single facts — title, authority, number, year, date, department. The
        # head pass sees only the front, and on a document that introduces itself
        # late (a policy that runs pages of generic prose before naming its
        # controller) it returns nothing at all. The sweep read every window, so
        # it fills whatever the head pass left blank.
        for key in _SWEEP_FACTS:
            if not out.get(key) and scan.get(key):
                out[key] = scan[key]

    # Keep the REAL detected country as a slug — do NOT clamp to a fixed list.
    # A jurisdiction the corpus hasn't seen (e.g. "egypt") flows through so the
    # wizard can offer to create it. Slugify: lowercase, spaces/punct -> nothing.
    jl = _canonical_slug(re.sub(r"[^a-z0-9]+", "", out["jurisdiction"].lower()))
    # Everything the document actually says — the head pass only saw a sample,
    # but grounding and inference get the whole text.
    evidence = " ".join([
        out.get("issuing_authority", ""), out.get("full_name", ""),
        out.get("name", ""), out.get("scope_summary", ""), full])
    # Reject an ungrounded jurisdiction BEFORE trusting it. A wrong country is
    # worse than a missing one here: it silently files the document under the
    # wrong regulator, and the wizard presents it as a confident suggestion the
    # user is likely to accept. Dropping it to "" hands the case to the sweep and
    # the deterministic inference below, and failing those, to the user.
    overridden = False
    if jl and not _is_grounded(jl, evidence):
        jl, overridden = "", True

    # Reconcile head vs sweep by EVIDENCE STRENGTH, not by which pass produced it.
    # "The sweep always wins" is wrong: the head pass reading "issued by the
    # Central Bank of Bahrain" is stronger evidence than twenty windows citing the
    # GDPR. Rate the head's answer on the same tier scale the sweep uses, and take
    # whichever is better evidenced — sweep first only on a genuine tie, since it
    # read more of the document.
    head_tier = 0
    if jl:
        if _is_grounded(jl, out.get("issuing_authority", "")):
            head_tier = 4                          # named in the issuing body
        elif _is_grounded(jl, " ".join([out.get("full_name", ""),
                                        out.get("name", "")])):
            head_tier = 3                          # named in the title
        else:
            head_tier = 1                          # somewhere in the text
    sweep_jl = scan.get("jurisdiction") or ""
    sweep_tier = 0
    if sweep_jl:
        sweep_tier = _evidence_tier(scan.get("jurisdiction_evidence", ""))
    if sweep_jl and sweep_tier >= head_tier:
        if jl and sweep_jl != jl:
            overridden = True
        jl = sweep_jl

    # Safety net: the model sometimes leaves jurisdiction blank even when the
    # country is obvious in the issuing authority / title (e.g. "Amir of the State
    # of Qatar"). Infer it deterministically from the fields it DID extract so the
    # user doesn't have to type a jurisdiction the document plainly states.
    if not jl:
        jl = _infer_jurisdiction(evidence)
    # Unknown stays EMPTY. 'other' is a jurisdiction the user can deliberately
    # choose (Document.JURISDICTION_CHOICES), so returning it here would dress a
    # failed detection up as a decision — and the field is blank=True, so "" is
    # storable. Blank leaves the wizard's selector unset and asks the user.
    out["jurisdiction"] = jl
    out["regulation_category"] = out["regulation_category"].lower()
    out["doc_type"] = "policy" if out["doc_type"].lower().startswith("pol") else "regulation"
    # The model's own number, kept under its real name. It describes the reply the
    # model gave, which is not the same thing as the answer being returned — the
    # validation above may have thrown that reply out.
    try:
        out["model_confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        out["model_confidence"] = 0.0
    # 'confidence' is what the UI shows, so it has to describe the FINAL values.
    # A model that said "bahrain" at 0.97 and was overruled does not get to keep
    # 0.97; and a jurisdiction that no evidence supports is not a confident answer
    # however sure the model sounded.
    conf = out["model_confidence"]
    if overridden:
        conf = min(conf, 0.5)
    if not out["jurisdiction"]:
        conf = min(conf, 0.3)
    out["confidence"] = round(conf, 2)
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
        # Two layouts, both common and both bare-numbered:
        #   "1."                     number alone, title on the next line
        #   "1. Data Controller …"   number and title on the SAME line
        # Only the first was handled, so a policy written in the second style
        # produced no outline at all and the wizard reported "no clear heading
        # structure" for a document with plainly numbered sections. The trailing
        # dot is what separates a real clause number from a bare page number.
        m = re.match(r"^[ \t]*(\d{1,3})\.[ \t]*$", l)
        inline = None if m else re.match(r"^[ \t]*(\d{1,3})\.[ \t]+(\S.*)$", l)
        if not m and not inline:
            continue
        num = int((m or inline).group(1))
        if num in found:                                  # first (usually TOC) wins
            continue
        if inline:
            title = inline.group(2).strip()
        else:
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
        # The prefix scan finding nothing means the level word the model named is
        # not actually how this document heads its divisions — it guessed
        # "Article" for a policy whose sections are plain "1.", "2.". Labelling
        # them "Article 1" would print a structure the document does not have.
        # Requiring SEVERAL line-initial hits, not one: this policy cites
        # "Article 37 of the GDPR" twice at the start of a wrapped line, which a
        # single-match test read as proof the document is built from Articles.
        if label_word and len(re.findall(
                rf"(?im)^[ \t]*{re.escape(label_word)}[ \t]+\d", text)) < 3:
            label_word = ""
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
