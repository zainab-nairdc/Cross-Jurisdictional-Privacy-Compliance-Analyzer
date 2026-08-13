"""Canonical compliance taxonomy.

Every chunk in the corpus is tagged with exactly one (topic, subcategory)
pair from this module. Retrieval can then filter by either topic or
(topic, subcategory) before semantic ranking, eliminating the
cross-topic false matches that pure-similarity search produces.

The structure is hand-curated, not generated. Twelve topics cover
privacy + security + sector-specific banking obligations across the
Bahrain / India / Kuwait corpus. Each leaf is non-overlapping by
intent — see `CLASSIFIER_GUIDANCE` below for the disambiguation rules.

When extending: prefer adding a subcategory under an existing topic
over inventing a new top-level topic. Top-level changes break the UI
cascade and the analyst's mental model.
"""

from __future__ import annotations


# --------------------------------------------------------------------------
# Taxonomy definition
# --------------------------------------------------------------------------
#
# Layout: TOPIC -> {label, subcategories: {tag: label}}
# - tag      = stable lowercase snake_case identifier stored in chunk metadata
# - label    = human-readable string for UI rendering
#
# UNCLASSIFIED is a reserved tag returned by the classifier when no leaf
# fits (definitions, preambles, schedules, signatures). Such chunks are
# still searchable via free-text but won't appear under any topic filter.

UNCLASSIFIED = "unclassified"

TAXONOMY: dict[str, dict] = {
    "lawful_basis": {
        "label": "Lawful basis & consent",
        "subcategories": {
            "consent":                  "Consent",
            "legitimate_interests":     "Legitimate interests",
            "legal_obligation":         "Legal obligation",
            "vital_or_public_task":     "Vital interest / public task",
        },
    },
    "data_subject_rights": {
        "label": "Data subject rights",
        "subcategories": {
            "access":                       "Access",
            "rectification":                "Rectification",
            "erasure":                      "Erasure",
            "objection_and_automated":      "Objection / automated decisions",
        },
    },
    "notice_and_transparency": {
        "label": "Notice & transparency",
        "subcategories": {
            "privacy_notice":           "Privacy notice",
            "secondary_use_notice":     "Secondary-use notice",
            "language_accessibility":   "Language & accessibility",
        },
    },
    "cross_border": {
        "label": "Cross-border transfers & data residency",
        "subcategories": {
            "adequacy_assessment":      "Adequacy assessment",
            "transfer_mechanisms":      "Transfer mechanisms (SCCs, BCRs, authorisations)",
            "data_localisation":        "Data localisation",
            "transfer_exemptions":      "Transfer exemptions",
        },
    },
    "sensitive_data": {
        "label": "Sensitive & special-category data",
        "subcategories": {
            "sensitive_processing":     "Sensitive-data processing",
            "children_and_minors":      "Children & minors",
        },
    },
    "security": {
        "label": "Security controls",
        "subcategories": {
            "technical_measures":       "Technical measures",
            "organisational_measures":  "Organisational measures",
            "access_control":           "Access control / IAM",
            "logging_and_monitoring":   "Logging & monitoring",
        },
    },
    "breach_management": {
        "label": "Breach management",
        "subcategories": {
            "incident_detection":       "Incident detection",
            "regulator_notification":   "Regulator notification",
            "data_subject_notification":"Data subject notification",
            "incident_response_plan":   "Incident response plan",
        },
    },
    "retention": {
        "label": "Retention & disposal",
        "subcategories": {
            "retention_periods":        "Retention periods",
            "secure_disposal":          "Secure disposal",
            "archive_and_backup":       "Archive & backup",
        },
    },
    "governance": {
        "label": "Governance & accountability",
        "subcategories": {
            "dpo_appointment":          "DPO appointment",
            "records_of_processing":    "Records of processing",
            "dpia_and_risk":            "DPIA & risk assessment",
            "policies_and_procedures":  "Policies & procedures",
        },
    },
    "third_party": {
        "label": "Third-party & outsourcing",
        "subcategories": {
            "processor_obligations":    "Processor obligations",
            "vendor_due_diligence":     "Vendor due diligence",
            "cloud_and_offshoring":     "Cloud & offshoring",
            "data_sharing":             "Data sharing with third parties",
        },
    },
    "sector_specific": {
        "label": "Sector-specific (banking & financial)",
        "subcategories": {
            "kyc_and_cdd":              "KYC & customer due diligence",
            "aml_and_sanctions":        "AML & sanctions",
            "customer_protection":      "Customer protection",
            "operational_resilience":   "Operational resilience",
        },
    },
    "enforcement": {
        "label": "Enforcement & remedies",
        "subcategories": {
            "regulator_powers":         "Regulator powers",
            "penalties":                "Penalties",
            "complaints_and_grievance": "Complaints & grievance",
            "individual_redress":       "Individual redress",
        },
    },
}


# --------------------------------------------------------------------------
# Classifier guidance (used by the LLM prompt + as living documentation)
# --------------------------------------------------------------------------
#
# These rules disambiguate cases where a chunk could plausibly fit two
# leaves. The classifier picks the PRIMARY purpose of the obligation,
# not every aspect it touches.

CLASSIFIER_GUIDANCE = """
Tagging rules — pick the PRIMARY purpose of the obligation, not every aspect it touches:

- A breach-notification clause that requires "notify the regulator within 72 hours
  AND maintain incident logs" is breach_management/regulator_notification, not
  security/logging_and_monitoring. The logging is a side-obligation; the primary
  duty is the notification.

- A clause about "encrypt customer payment data stored within India" is
  cross_border/data_localisation, not security/technical_measures, because the
  primary mandate is *where* the data must live; encryption is the means, not
  the end.

- A KYC clause that says "verify identity using government documents" is
  sector_specific/kyc_and_cdd, not lawful_basis/legal_obligation, even though
  KYC IS a legal-obligation lawful basis. Sector-specific rules take precedence
  over generic lawful-basis tagging.

- A children's-data clause is sensitive_data/children_and_minors regardless of
  whether it talks about consent, retention, or notice — the special-category
  framing wins because that's how analysts will look for it.

- DPO appointment, qualifications, and independence rules all go under
  governance/dpo_appointment. DPO *fees* go under enforcement/penalties only if
  framed as a fine; otherwise governance/dpo_appointment.

- Definitions, preambles, schedules, signatures, gazette numbers, table-of-
  contents fragments → return "unclassified". Do not force a tag.

- A clause covering multiple topics (e.g. "the controller shall implement
  technical measures, appoint a DPO, and notify breaches within 72 hours") →
  pick the topic the clause LEADS WITH or whose imperative verb dominates. If
  truly co-equal, prefer the more specific topic over the more general one.
"""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def all_topics() -> list[tuple[str, str]]:
    """Return [(tag, label)] for every top-level topic."""
    return [(t, v["label"]) for t, v in TAXONOMY.items()]


def all_subcategories(topic: str) -> list[tuple[str, str]]:
    """Return [(tag, label)] for the subcategories under one topic."""
    if topic not in TAXONOMY:
        return []
    return list(TAXONOMY[topic]["subcategories"].items())


def is_valid(topic: str, subcategory: str | None = None) -> bool:
    """True if the topic exists and (if given) the subcategory is under it.
    The reserved value `UNCLASSIFIED` is also valid (with subcategory None)."""
    if topic == UNCLASSIFIED:
        return subcategory is None or subcategory == ""
    if topic not in TAXONOMY:
        return False
    if subcategory is None or subcategory == "":
        return True
    return subcategory in TAXONOMY[topic]["subcategories"]


def topic_label(topic: str) -> str:
    if topic == UNCLASSIFIED:
        return "Unclassified"
    return TAXONOMY.get(topic, {}).get("label", topic)


def subcategory_label(topic: str, subcategory: str) -> str:
    if topic == UNCLASSIFIED or topic not in TAXONOMY:
        return subcategory
    return TAXONOMY[topic]["subcategories"].get(subcategory, subcategory)


def render_for_prompt() -> str:
    """Render the taxonomy as a numbered list the LLM classifier can read.
    Each leaf appears as `topic/subcategory  — Topic label / Subcategory label`."""
    lines = []
    for topic, body in TAXONOMY.items():
        lines.append(f"\n{body['label']} ({topic}):")
        for sub_tag, sub_label in body["subcategories"].items():
            lines.append(f"  - {topic}/{sub_tag} — {sub_label}")
    lines.append(f"\n{UNCLASSIFIED} — none of the above (definitions, preambles, schedules)")
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------
#
# Cached tags (chunk_tags), cached mapping results, and every stored
# classification are keyed on this version. When it changes, consumers treat
# older records as stale.
#
# ── schema v1 -> v2: what changed and why ──────────────────────────────────
#
# v1 hashed the set of LEAVES ("topic/subcategory") only. That had a hole: a
# top-level topic carrying no subcategories contributed nothing to the hash,
# so adding one would NOT change the fingerprint and every consumer would keep
# serving stale tags with no staleness signal at all. It was latent while the
# taxonomy was hand-edited and every topic happened to have subcategories; it
# became reachable the moment human-approved expansion could add a topic.
#
# v1 also ignored LABELS, which are not decoration: render_for_prompt() shows
# them to the classifier, and resolve_concept() matches against them. Editing
# a label changes what the model is told and what resolves — so it must change
# the version.
#
# v2 hashes the COMPLETE structure: every topic tag, every topic label, every
# subcategory tag, every subcategory label, and the reserved UNCLASSIFIED
# sentinel.
#
# THE PREFIX IS THE ALGORITHM GENERATION, and that is what makes this change
# safe. A stored "v1-fea40d25" is unambiguously a v1-algorithm fingerprint and
# can never collide with a v2 one, so historical records stay distinguishable
# and nothing pretends an old classification was produced under the new rules.
# The lineage records the transition explicitly (LINEAGE_ALGORITHM), so
# consumers can see the VOCABULARY did not change — only how it is hashed.
#
# NOT included in the hash: ALIASES. An alias maps alternative wording onto an
# existing topic; it does not change what any topic MEANS, so a chunk tagged
# `security` stays correctly `security` whatever the alias table says.
# Including them would make every alias addition invalidate the entire corpus,
# which is precisely the cost that stops people adding aliases — and adding
# aliases is the cheap, human-controlled fix we WANT to be easy.

import hashlib as _hashlib

# Bumped v1 -> v2 with the structural fingerprint above. Bump again only if the
# algorithm changes, never for a content change — content changes are what the
# hash suffix is for.
_TAXONOMY_SCHEMA = "v2"


def _structure_tokens(structure: dict) -> list[str]:
    """Canonical, order-independent tokens describing a taxonomy structure.

    Sorted at every level, so the same taxonomy always hashes identically no
    matter what order it was declared in. Tags and labels are namespaced
    (`topic:` / `leaf:`) so a topic and a subcategory sharing a name cannot
    silently produce the same token.

    A topic with NO subcategories still emits its own `topic:` token — that is
    the v1 hole this closes.
    """
    tokens: list[str] = []
    for topic in sorted(structure):
        body = structure[topic] or {}
        tokens.append(f"topic:{topic}={body.get('label', '')}")
        subs = body.get("subcategories") or {}
        for sub in sorted(subs):
            tokens.append(f"leaf:{topic}/{sub}={subs[sub]}")
    tokens.append(f"reserved:{UNCLASSIFIED}")
    return sorted(set(tokens))


def fingerprint_of(structure: dict) -> str:
    """The v2 fingerprint of any taxonomy-shaped mapping.

    Takes the structure as an argument rather than reading the global, so a
    PROPOSED taxonomy can be fingerprinted without being applied — which is
    what lets the review UI show the version a change will produce before
    anyone edits this file.
    """
    digest = _hashlib.sha1(
        "|".join(_structure_tokens(structure)).encode("utf-8")).hexdigest()[:8]
    return f"{_TAXONOMY_SCHEMA}-{digest}"


def _taxonomy_fingerprint() -> str:
    return fingerprint_of(TAXONOMY)


TAXONOMY_VERSION = _taxonomy_fingerprint()

# The last fingerprint produced by the v1 leaf-only algorithm. Retained so a
# stored version can still be RECOGNISED rather than merely looking foreign —
# see TAXONOMY_LINEAGE, which records that the vocabulary was identical either
# side of the transition.
LEGACY_V1_VERSION = "v1-fea40d25"


def fingerprint_with(extra_leaves=(), *, labels=None) -> str:
    """What TAXONOMY_VERSION WOULD become if `extra_leaves` were added.

    Purely a calculation on a COPY — it adds nothing to the taxonomy and has no
    side effects.

    `extra_leaves` are "topic/subcategory", or a bare "topic" to propose a
    top-level topic with no subcategories (now representable, because v2 hashes
    topics as well as leaves).

    `labels` maps a tag or leaf path to the human label the change will use,
    e.g. {"adm": "Automated decisions", "adm/registers": "ADM registers"}.
    Labels are part of the v2 hash, so an accurate prediction needs them; a
    caller that omits them gets a prediction based on the tag standing in for
    its own label, which will not match the file once a real label is written.
    """
    labels = labels or {}
    hypothetical = {
        topic: {"label": body.get("label", ""),
                "subcategories": dict(body.get("subcategories") or {})}
        for topic, body in TAXONOMY.items()
    }
    for raw in (extra_leaves or ()):
        leaf = str(raw).strip()
        if not leaf:
            continue
        topic, _, sub = leaf.partition("/")
        topic, sub = topic.strip(), sub.strip()
        if not topic:
            continue
        if topic not in hypothetical:
            hypothetical[topic] = {"label": labels.get(topic, topic),
                                   "subcategories": {}}
        if sub:
            hypothetical[topic]["subcategories"][sub] = labels.get(leaf, sub)
    return fingerprint_of(hypothetical)


# --------------------------------------------------------------------------
# Lineage
# --------------------------------------------------------------------------
#
# TAXONOMY_VERSION alone answers "were these tags written under a different
# taxonomy?" but not "does that difference actually invalidate them?". Those
# are not the same question, and conflating them is expensive: the fingerprint
# hashes the WHOLE leaf set, so ADDING one topic invalidates every tag in the
# corpus and forces a full re-classification (one local LLM call per chunk).
# That cost is what stops a taxonomy from ever being extended in practice.
#
# The lineage records WHAT changed at each bump, so a consumer can tell an
# additive change (old tags stay correct, they are merely incomplete — a chunk
# tagged `security` is still security even though a new topic now exists) from
# a semantic or structural one (old tags may now be wrong and must be redone).
#
# Append-only, oldest first. Adding a leaf to TAXONOMY without adding an entry
# here is a mistake that `lineage_is_current()` detects and the test suite
# fails on — that is deliberate, it forces the change to be described by the
# human making it.
#
# `change` is one of:
#   initial      — the first recorded version
#   additive     — leaves ONLY added; every pre-existing leaf keeps its meaning
#   semantic     — a leaf's meaning changed without the leaf set changing
#   removal      — leaves removed or renamed
#   restructure  — topics reorganised; treat all prior tags as invalid
#   algorithm    — the FINGERPRINT changed while the vocabulary did not. Tags
#                  written before it classified against exactly the same
#                  topics, so they stay semantically correct even though their
#                  stored version string no longer matches.

LINEAGE_INITIAL     = "initial"
LINEAGE_ADDITIVE    = "additive"
LINEAGE_SEMANTIC    = "semantic"
LINEAGE_REMOVAL     = "removal"
LINEAGE_RESTRUCTURE = "restructure"
LINEAGE_ALGORITHM   = "algorithm"

# Changes that leave pre-existing tags correct-but-possibly-incomplete.
# `algorithm` belongs here because it changes how the vocabulary is HASHED,
# not what the vocabulary is.
_NON_INVALIDATING = (LINEAGE_INITIAL, LINEAGE_ADDITIVE, LINEAGE_ALGORITHM)

TAXONOMY_LINEAGE: list[dict] = [
    {
        "version": "v1-fea40d25",
        "change":  LINEAGE_INITIAL,
        "date":    "2025-01-01",
        "added":   [],
        "removed": [],
        "note":    "Twelve hand-curated topics, 44 leaves. The baseline "
                   "vocabulary; every earlier tag predates version stamping. "
                   "Fingerprinted by the v1 leaf-only algorithm.",
    },
    {
        "version": "v2-a894a88f",
        "change":  LINEAGE_ALGORITHM,
        "date":    "2026-08-13",
        "added":   [],
        "removed": [],
        "note":    "Fingerprint algorithm v1 -> v2. The VOCABULARY is "
                   "unchanged — still the same twelve topics and 44 leaves. "
                   "v1 hashed leaves only, so a top-level topic with no "
                   "subcategories would not have changed the version, and "
                   "label edits went undetected although the classifier reads "
                   "labels. v2 hashes the complete structure. Tags stamped "
                   "v1-fea40d25 remain semantically valid; they will be "
                   "re-stamped on the next classification pass.",
    },
]


def lineage_is_current() -> bool:
    """Does the newest lineage entry describe the taxonomy as it stands now?

    False means someone edited TAXONOMY without recording why. The tag data
    is not corrupt, but nothing can tell whether existing tags survived the
    edit, which is exactly the judgement the lineage exists to preserve.
    """
    return bool(TAXONOMY_LINEAGE) and TAXONOMY_LINEAGE[-1]["version"] == TAXONOMY_VERSION


def lineage_entry(version: str) -> dict | None:
    """The recorded entry for one version, or None if it predates the lineage."""
    for entry in TAXONOMY_LINEAGE:
        if entry["version"] == version:
            return entry
    return None


def tags_still_valid_since(version: str) -> bool:
    """Are tags written under `version` still semantically correct today?

    True when every change since then was additive: such tags are INCOMPLETE
    (a multi-topic chunk may now warrant a topic that did not exist) but not
    WRONG, so a consumer may keep using them and re-classification can be
    scheduled rather than forced.

    False whenever the answer is not provably yes — an unknown version, a gap
    in the lineage, or any semantic/removal/restructure change. Callers that
    need certainty get the conservative answer, so this can never quietly
    bless a tag that a restructure invalidated.
    """
    if not version:
        return False
    # No shortcut for `version == TAXONOMY_VERSION`: the lineage may already
    # record a change PAST the current fingerprint (a pending bump under
    # review), and answering from the fingerprint alone would call those tags
    # valid without ever consulting what changed.
    seen = False
    for entry in TAXONOMY_LINEAGE:
        if seen and entry["change"] not in _NON_INVALIDATING:
            return False
        if entry["version"] == version:
            seen = True
    return seen


# --------------------------------------------------------------------------
# Concept resolution
# --------------------------------------------------------------------------
#
# A model asked to classify text does not reliably answer in the controlled
# vocabulary. It says "storage limitation" when the taxonomy says "retention",
# or "Data Retention" when the tag is `retention`. Rejecting those outright
# (which is what the strict classifier does today) throws away correct
# classifications over wording; accepting them as-is would let arbitrary
# free text become a topic, which is the failure this module exists to prevent.
#
# resolve_concept() is the controlled middle: it maps a model's wording onto
# the official vocabulary through explicit, auditable steps, and REFUSES when
# no step is safe. Its three outcomes are deliberately distinct:
#
#   matched       the concept IS an official topic. Safe to store as one.
#   unresolved    the concept is meaningful but no official topic represents
#                 it. This is the input to the human-reviewed suggestion
#                 workflow — NOT an error, and never forced into a topic.
#   unclassified  no meaningful topic applies at all (the model declined, or
#                 was not confident enough to be worth acting on).
#
# "unresolved" and "unclassified" are NOT the same thing and must not be
# merged: the first says the taxonomy may need to grow, the second says this
# text has nothing to classify. Collapsing them either buries real gaps or
# floods the review queue with noise.

MATCHED    = "matched"
UNRESOLVED = "unresolved"
# UNCLASSIFIED is defined at the top of this module and reused as the third
# outcome, so callers writing a chunk tag and callers reading a resolution
# speak the same word for the same idea.

# resolution methods, in the order they are attempted
METHOD_EXACT      = "exact"
METHOD_ALIAS      = "alias"
METHOD_NORMALIZED = "normalized"
METHOD_SEMANTIC   = "semantic"
METHOD_HUMAN      = "human"
METHOD_NONE       = "none"

# Below this, the model is guessing. Mirrors the floor already applied in
# reasoning.classifier._normalise so both paths agree on what "too unsure to
# act on" means.
MIN_CONCEPT_CONFIDENCE = 0.3

# Semantic matching is the only inexact step, so it is gated twice: the best
# candidate must clear an absolute similarity bar AND beat the runner-up by a
# margin. A concept that sits between two topics is a genuine ambiguity and is
# left unresolved for a human, never assigned to whichever scored 0.001 higher.
SEMANTIC_MATCH_THRESHOLD = 0.75
SEMANTIC_MATCH_MARGIN    = 0.05

# Things a model says when it means "none of these fit". Recognised so the
# answer is recorded as a declaration rather than mistaken for a concept named
# "n/a" that then gets proposed as a new official topic.
_NO_FIT_TOKENS = frozenset({
    "", "none", "no topic", "no topics", "no fit", "no match", "na", "n a",
    "null", "nil", "unknown", "unclassified", "other", "misc",
    "miscellaneous", "not applicable", "no suitable topic",
    "no suitable existing topic", "new topic", "new topic candidate",
})


# --------------------------------------------------------------------------
# Aliases
# --------------------------------------------------------------------------
#
# Hand-curated synonyms mapping model wording onto official leaves. This table
# is SOURCE, edited by people, for the same reason TAXONOMY is: an alias
# silently redirects a concept into an existing topic, so adding one is a
# vocabulary decision, not a runtime inference.
#
# A value is either "topic" or "topic/subcategory". validate_aliases() proves
# every value resolves, and the test suite runs it.
#
# What does NOT belong here: any phrase that could honestly mean two different
# topics. Bare "sanctions" is the worked example — it is `aml_and_sanctions`
# in a banking clause and `penalties` in an enforcement one. Aliasing it would
# make the resolver confidently wrong half the time, so it is deliberately
# absent and such wording falls through to semantic matching or to a human.

#
# The four entries marked EVIDENCE below are not guesses. They come from the
# Phase 2 dry run over the real corpus, where the classifier produced each
# wording and then — because nothing mapped it — proposed it as a NEW official
# topic. Every one is a concept the taxonomy already covers, so the fix is a
# vocabulary alias rather than a new topic. Each also came from a requirement
# that received ZERO official topics, which is what makes them worth aliasing:
# without one, the provision is simply unclassified.

ALIASES: dict[str, str] = {
    # ── EVIDENCE (Phase 2, real corpus) ──
    # Observed once each; the wording is what the model reached for when the
    # official tag did not occur to it.
    "cyber risk management":        "security",
    "record maintenance":           "governance/records_of_processing",
    "customer acceptance policy":   "sector_specific/kyc_and_cdd",
    "data disclosure restrictions": "third_party/data_sharing",

    # ── retention ──
    "storage limitation":        "retention/retention_periods",
    "data retention":            "retention",
    "data storage period":       "retention/retention_periods",
    "data storage periods":      "retention/retention_periods",
    "retention schedule":        "retention/retention_periods",
    "records retention":         "retention/retention_periods",
    "data disposal":             "retention/secure_disposal",
    "data destruction":          "retention/secure_disposal",
    "erasure of records":        "retention/secure_disposal",

    # ── security ──
    "information security":      "security",
    "infosec":                   "security",
    "cybersecurity":             "security",
    "cyber security":            "security",
    "data security":             "security",
    "safeguards":                "security",
    "technical and organisational measures": "security",
    "technical and organizational measures": "security",
    "identity and access management":        "security/access_control",
    "iam":                       "security/access_control",
    "audit logging":             "security/logging_and_monitoring",
    "audit trail":               "security/logging_and_monitoring",

    # ── lawful_basis ──
    "legal basis":               "lawful_basis",
    "lawful processing":         "lawful_basis",
    "grounds for processing":    "lawful_basis",
    "consent management":        "lawful_basis/consent",

    # ── data_subject_rights ──
    "individual rights":         "data_subject_rights",
    "rights of individuals":     "data_subject_rights",
    "data subject requests":     "data_subject_rights",
    "dsar":                      "data_subject_rights/access",
    "subject access":            "data_subject_rights/access",
    "right to be forgotten":     "data_subject_rights/erasure",
    # Keys are stored already-normalised, so the hyphenated spelling
    # ("automated decision-making") reaches this entry too.
    "automated decision making":            "data_subject_rights/objection_and_automated",

    # ── notice_and_transparency ──
    "transparency":              "notice_and_transparency",
    "fair processing notice":    "notice_and_transparency/privacy_notice",
    "privacy policy":            "notice_and_transparency/privacy_notice",
    "information to be provided": "notice_and_transparency",

    # ── cross_border ──
    "international transfers":   "cross_border",
    "international transfer":    "cross_border",
    "overseas transfer":         "cross_border",
    "onward transfer":           "cross_border",
    "data residency":            "cross_border/data_localisation",
    "data localization":         "cross_border/data_localisation",
    "standard contractual clauses": "cross_border/transfer_mechanisms",
    "sccs":                      "cross_border/transfer_mechanisms",
    "binding corporate rules":   "cross_border/transfer_mechanisms",

    # ── sensitive_data ──
    "special category data":     "sensitive_data/sensitive_processing",
    "special categories of personal data": "sensitive_data/sensitive_processing",
    "sensitive personal data":   "sensitive_data/sensitive_processing",
    "childrens data":            "sensitive_data/children_and_minors",
    "children s data":           "sensitive_data/children_and_minors",
    "minors":                    "sensitive_data/children_and_minors",

    # ── breach_management ──
    "data breach":               "breach_management",
    "breach notification":       "breach_management/regulator_notification",
    "incident management":       "breach_management/incident_response_plan",
    "incident response":         "breach_management/incident_response_plan",
    "security incident":         "breach_management",

    # ── governance ──
    "accountability":            "governance",
    "record keeping":            "governance/records_of_processing",
    "recordkeeping":             "governance/records_of_processing",
    "privacy governance":        "governance",
    "data governance":           "governance",
    "dpia":                      "governance/dpia_and_risk",
    "data protection impact assessment": "governance/dpia_and_risk",
    "privacy impact assessment": "governance/dpia_and_risk",
    "privacy by design":         "governance/policies_and_procedures",
    "data protection officer":   "governance/dpo_appointment",

    # ── third_party ──
    "vendor management":         "third_party/vendor_due_diligence",
    "supplier management":       "third_party/vendor_due_diligence",
    "third party risk":          "third_party/vendor_due_diligence",
    "outsourcing":               "third_party",
    "subprocessors":             "third_party/processor_obligations",
    "sub processors":            "third_party/processor_obligations",
    "cloud computing":           "third_party/cloud_and_offshoring",

    # ── sector_specific ──
    "kyc":                       "sector_specific/kyc_and_cdd",
    "know your customer":        "sector_specific/kyc_and_cdd",
    "customer due diligence":    "sector_specific/kyc_and_cdd",
    "aml":                       "sector_specific/aml_and_sanctions",
    "anti money laundering":     "sector_specific/aml_and_sanctions",
    "sanctions screening":       "sector_specific/aml_and_sanctions",
    "business continuity":       "sector_specific/operational_resilience",

    # ── enforcement ──
    "fines":                     "enforcement/penalties",
    "regulatory powers":         "enforcement/regulator_powers",
    "supervisory powers":        "enforcement/regulator_powers",
    "complaints":                "enforcement/complaints_and_grievance",
    "grievance":                 "enforcement/complaints_and_grievance",
    "remedies":                  "enforcement/individual_redress",
    "compensation":              "enforcement/individual_redress",
}


# --------------------------------------------------------------------------
# Resolution machinery
# --------------------------------------------------------------------------

import re as _re
from dataclasses import dataclass as _dataclass, field as _field


@_dataclass(frozen=True)
class ConceptResolution:
    """What resolve_concept() decided, and how.

    `concept` always carries the model's ORIGINAL wording, matched or not.
    Keeping it is what makes duplicate suggestions detectable later without
    re-running the model, and what lets a reviewer see that "storage
    limitation" and "retention" were the same underlying finding.
    """
    status:      str            # MATCHED | UNRESOLVED | UNCLASSIFIED
    concept:     str            # the model's original wording, verbatim
    topic:       str   = ""     # official tag; "" unless MATCHED
    subcategory: str   = ""     # official tag under `topic`; may be ""
    method:      str   = METHOD_NONE
    confidence:  float = 0.0    # the model's confidence, carried through
    detail:      str   = ""     # human-readable reason, for audit + review UI
    # Populated on a semantic near-miss: the topics that scored best but did
    # not clear the gate. Feeds "similar existing topics" in the review UI so
    # a reviewer can see what the model nearly picked.
    candidates:  tuple = _field(default_factory=tuple)

    @property
    def is_matched(self) -> bool:
        return self.status == MATCHED

    @property
    def is_unresolved(self) -> bool:
        """True when this concept should be considered for a TopicSuggestion."""
        return self.status == UNRESOLVED

    @property
    def leaf(self) -> str:
        """'topic/subcategory', or just 'topic' when no subcategory. '' if unmatched."""
        if not self.is_matched:
            return ""
        return f"{self.topic}/{self.subcategory}" if self.subcategory else self.topic


_PUNCT_RE = _re.compile(r"[^a-z0-9]+")


def normalise_concept(text: str) -> str:
    """Collapse wording to a comparable form: lowercase, punctuation to spaces.

    'Data Retention', 'data_retention' and 'Data-Retention!' all become
    'data retention'. Used for alias lookup and for the normalized-match
    index; deliberately does NOT drop words like 'data', because dropping
    them turns 'data minimisation' into 'minimisation' and invites exactly
    the silent conflation this module refuses to make.
    """
    return _PUNCT_RE.sub(" ", (text or "").lower()).strip()


def is_no_fit(concept: str) -> bool:
    """Is this wording the model DECLINING rather than naming a concept?

    Lets a caller tell the two UNCLASSIFIED causes apart: "none of these fit"
    (nothing to record) versus "retention, but I'm only 15% sure" (worth
    recording as a rejected guess, because it is evidence about the model
    rather than about the taxonomy).
    """
    return normalise_concept(concept) in _NO_FIT_TOKENS


def _depluralise(token: str) -> str:
    for suf, rep in (("ies", "y"), ("sses", "ss"), ("shes", "sh"),
                     ("ches", "ch"), ("xes", "x"), ("s", "")):
        if token.endswith(suf) and len(token) > len(suf) + 1:
            return token[:-len(suf)] + rep
    return token


def _singular_form(norm: str) -> str:
    """Normalised text with its LAST token de-pluralised.

    Lets 'retention period' reach `retention_periods` without loosening the
    match to fuzzy territory. Only the last token, because that is the head
    noun in every label in this taxonomy.
    """
    parts = norm.split()
    if not parts:
        return norm
    return " ".join(parts[:-1] + [_depluralise(parts[-1])])


def _build_match_index() -> dict[str, set]:
    """normalised text -> {(topic, subcategory)} for every official name.

    Indexes tags AND human labels, both as written and de-pluralised. A form
    landing on more than one leaf is kept with all of them so the caller can
    see it is ambiguous and refuse, rather than silently taking the first.
    """
    index: dict[str, set] = {}

    def add(text: str, topic: str, sub: str) -> None:
        for form in (normalise_concept(text), _singular_form(normalise_concept(text))):
            if form:
                index.setdefault(form, set()).add((topic, sub))

    for topic, body in TAXONOMY.items():
        add(topic, topic, "")
        add(body["label"], topic, "")
        for sub_tag, sub_label in body["subcategories"].items():
            add(sub_tag, topic, sub_tag)
            add(sub_label, topic, sub_tag)
    return index


_MATCH_INDEX = _build_match_index()


def _split_leaf(value: str) -> tuple[str, str]:
    """'topic/sub' -> ('topic', 'sub'); 'topic' -> ('topic', '')."""
    topic, _, sub = (value or "").partition("/")
    return topic.strip(), sub.strip()


def validate_aliases() -> list[str]:
    """Prove every alias points at a real leaf. Returns a list of problems.

    Run by the test suite so a typo in ALIASES fails CI rather than silently
    routing a concept to a topic that does not exist — which would surface as
    a mysteriously unclassified requirement months later.
    """
    problems: list[str] = []
    for alias, value in ALIASES.items():
        norm = normalise_concept(alias)
        if not norm:
            problems.append(f"alias {alias!r} normalises to empty")
            continue
        if norm != alias:
            problems.append(
                f"alias key {alias!r} is not in normalised form (expected {norm!r})")
        topic, sub = _split_leaf(value)
        if not is_valid(topic, sub or None):
            problems.append(f"alias {alias!r} -> {value!r} is not a valid leaf")
        if norm in _NO_FIT_TOKENS:
            problems.append(f"alias {alias!r} collides with a no-fit token")
        # An alias that contradicts an unambiguous official name would make
        # the resolver's answer depend on step ordering. Officially-named
        # forms must never be re-pointed somewhere else.
        official = _MATCH_INDEX.get(norm)
        if official and len(official) == 1 and (topic, sub) not in official:
            problems.append(
                f"alias {alias!r} -> {value!r} contradicts official name "
                f"{sorted(official)[0]}")
    return problems


def _cosine(a: list, b: list) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    if not na or not nb:
        return 0.0
    return num / (na * nb)


def _semantic_targets() -> list[tuple[str, str, str]]:
    """[(topic, subcategory, text_to_embed)] for every official leaf + topic."""
    out: list[tuple[str, str, str]] = []
    for topic, body in TAXONOMY.items():
        out.append((topic, "", body["label"]))
        for sub_tag, sub_label in body["subcategories"].items():
            out.append((topic, sub_tag, f"{body['label']}: {sub_label}"))
    return out


def default_embed_fn():
    """The project embedder, wrapped to the embed_fn contract. Lazily imported.

    NOT used unless a caller passes it in. taxonomy.py stays importable with
    no model on disk and no torch in the environment — every test in this
    module runs without loading a 400MB SentenceTransformer, and the semantic
    path is exercised with a stub instead.
    """
    def _embed(texts: list[str]) -> list[list[float]]:
        from ingestion.embedder import get_model
        return [list(v) for v in get_model().encode(texts, normalize_embeddings=True)]
    return _embed


def resolve_concept(
    concept:            str,
    *,
    subcategory:        str   = "",
    confidence:         float = 1.0,
    embed_fn:           callable = None,
    min_confidence:     float = MIN_CONCEPT_CONFIDENCE,
    semantic_threshold: float = SEMANTIC_MATCH_THRESHOLD,
    semantic_margin:    float = SEMANTIC_MATCH_MARGIN,
) -> ConceptResolution:
    """Map one model-produced concept onto the official taxonomy, or refuse.

    Steps, in order, stopping at the first that is SAFE:

      1. exact       the concept already is an official tag ('retention',
                     'retention/retention_periods', or a bare subcategory tag
                     — all 44 are globally unique, so that is unambiguous).
      2. alias       a curated synonym in ALIASES.
      3. normalized  case/punctuation/plural-insensitive equality against an
                     official tag or label. Only when exactly one leaf matches.
      4. semantic    embedding similarity, ONLY when `embed_fn` is supplied,
                     and only when the best candidate clears both the absolute
                     threshold and the margin over the runner-up.

    No step guesses. A concept matching two leaves is ambiguous and comes back
    UNRESOLVED with both listed, because picking one would be a vocabulary
    decision and this function is not entitled to make those.

    `embed_fn` is callable(list[str]) -> list[list[float]]. When omitted the
    semantic step is skipped entirely — so resolution stays deterministic and
    dependency-free by default, and a caller opts into fuzziness explicitly.

    Returns a ConceptResolution; never raises, never mutates TAXONOMY.
    """
    raw  = (concept or "").strip()
    norm = normalise_concept(raw)

    # ── The model declining is an ANSWER, and a valid one. Recorded as such
    #    so "none of these fit" never becomes a proposed new topic named "n/a".
    if norm in _NO_FIT_TOKENS:
        return ConceptResolution(
            status=UNCLASSIFIED, concept=raw, confidence=confidence,
            method=METHOD_NONE,
            detail="model reported no suitable existing topic")

    # ── Too unsure to act on. Checked BEFORE matching so a low-confidence
    #    guess cannot become either a stored topic or a suggestion — it is
    #    noise in both directions.
    if confidence < min_confidence:
        return ConceptResolution(
            status=UNCLASSIFIED, concept=raw, confidence=confidence,
            method=METHOD_NONE,
            detail=f"confidence {confidence:.2f} below floor {min_confidence:.2f}")

    sub_norm = normalise_concept(subcategory)

    def _finish(topic: str, sub: str, method: str, detail: str) -> ConceptResolution:
        """Attach the model's subcategory when it is valid under the topic.

        A wrong subcategory drops rather than sinking the whole match — the
        topic is the load-bearing part, and this mirrors what the existing
        classifier already does at reasoning/classifier.py.
        """
        final_sub = sub
        if not final_sub and sub_norm:
            hit = _MATCH_INDEX.get(sub_norm) or _MATCH_INDEX.get(_singular_form(sub_norm))
            if hit and len(hit) == 1:
                cand_topic, cand_sub = next(iter(hit))
                if cand_topic == topic and cand_sub:
                    final_sub = cand_sub
        return ConceptResolution(
            status=MATCHED, concept=raw, topic=topic, subcategory=final_sub,
            method=method, confidence=confidence, detail=detail)

    # ── 1. exact ──────────────────────────────────────────────────────────
    exact_topic, exact_sub = _split_leaf(raw.strip().lower())
    if exact_sub and is_valid(exact_topic, exact_sub):
        return _finish(exact_topic, exact_sub, METHOD_EXACT,
                       "concept is an official leaf tag")
    if not exact_sub and exact_topic in TAXONOMY:
        return _finish(exact_topic, "", METHOD_EXACT,
                       "concept is an official topic tag")
    if not exact_sub:
        # A bare subcategory tag. Safe because subcategory tags are globally
        # unique across the taxonomy — asserted by the test suite, so this
        # stops being safe loudly rather than silently if that ever changes.
        for _t, _body in TAXONOMY.items():
            if exact_topic in _body["subcategories"]:
                return _finish(_t, exact_topic, METHOD_EXACT,
                               "concept is an official subcategory tag")

    # ── 2. alias ──────────────────────────────────────────────────────────
    if norm in ALIASES:
        a_topic, a_sub = _split_leaf(ALIASES[norm])
        if is_valid(a_topic, a_sub or None):
            return _finish(a_topic, a_sub, METHOD_ALIAS,
                           f"curated alias {norm!r} -> {ALIASES[norm]!r}")

    # ── 3. safe normalized ────────────────────────────────────────────────
    hits = _MATCH_INDEX.get(norm) or _MATCH_INDEX.get(_singular_form(norm))
    if hits:
        if len(hits) == 1:
            n_topic, n_sub = next(iter(hits))
            return _finish(n_topic, n_sub, METHOD_NORMALIZED,
                           f"normalised form {norm!r} matches one official name")
        # Two or more leaves share this wording. Genuinely ambiguous — a human
        # decides, we do not.
        return ConceptResolution(
            status=UNRESOLVED, concept=raw, confidence=confidence,
            method=METHOD_NONE,
            detail=f"{norm!r} matches {len(hits)} official names; ambiguous",
            candidates=tuple(sorted(hits)))

    # ── 4. semantic (opt-in) ──────────────────────────────────────────────
    if embed_fn is not None:
        try:
            targets = _semantic_targets()
            vectors = embed_fn([raw] + [t[2] for t in targets])
            probe, rest = vectors[0], vectors[1:]
            scored = sorted(
                ((_cosine(probe, v), t) for v, t in zip(rest, targets)),
                key=lambda x: x[0], reverse=True)
        except Exception as exc:                       # embedder unavailable
            return ConceptResolution(
                status=UNRESOLVED, concept=raw, confidence=confidence,
                method=METHOD_NONE,
                detail=f"semantic matching unavailable: {type(exc).__name__}")
        if scored:
            best_score, (b_topic, b_sub, _) = scored[0]
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            near = tuple((t[0], t[1], round(s, 4)) for s, t in scored[:3])
            if best_score >= semantic_threshold and (best_score - runner_up) >= semantic_margin:
                return _finish(
                    b_topic, b_sub, METHOD_SEMANTIC,
                    f"semantic match {best_score:.2f} (runner-up {runner_up:.2f})")
            # Close but not safe. The near-misses ride along as "similar
            # existing topics" for the reviewer.
            return ConceptResolution(
                status=UNRESOLVED, concept=raw, confidence=confidence,
                method=METHOD_NONE, candidates=near,
                detail=(f"best semantic match {best_score:.2f} did not clear "
                        f"threshold {semantic_threshold:.2f} / margin "
                        f"{semantic_margin:.2f}"))

    # ── Nothing was safe. The concept is meaningful but the taxonomy does not
    #    represent it: exactly the input the suggestion workflow exists for.
    return ConceptResolution(
        status=UNRESOLVED, concept=raw, confidence=confidence,
        method=METHOD_NONE,
        detail="no official topic matches this concept")


def resolve_concepts(items: list[dict], *, embed_fn: callable = None,
                     **kw) -> list[ConceptResolution]:
    """resolve_concept() over a model's whole `topics` array, order preserved.

    Each item is {concept, subcategory?, confidence?} — the shape the
    classification prompt returns.

    Multi-topic is the POINT, so distinct topics all survive and there is no
    cap on how many. Only genuine duplication collapses, in two forms:

      - same leaf twice ("retention" and "data retention") — one topic named
        twice. Kept once, at the higher confidence.
      - a bare topic alongside one of its own subcategories ("retention" plus
        "storage limitation" -> retention/retention_periods) — the general
        claim is absorbed by the specific one, which says everything it said
        and more.

    Distinct subcategories under one topic are NOT duplication and both
    survive: retention_periods and secure_disposal are different obligations.

    Without this, a rollup that counts topics would show `retention` twice for
    a requirement that concerns retention once.
    """
    resolved: list[ConceptResolution] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        resolved.append(resolve_concept(
            item.get("concept") or item.get("topic") or "",
            subcategory = item.get("subcategory") or "",
            confidence  = float(item.get("confidence", 1.0) or 0.0),
            embed_fn    = embed_fn,
            **kw,
        ))

    specific = {r.topic for r in resolved if r.is_matched and r.subcategory}
    out: list[ConceptResolution] = []
    at_leaf: dict[str, int] = {}
    for res in resolved:
        if not res.is_matched:
            out.append(res)          # unresolved / unclassified pass through
            continue
        if not res.subcategory and res.topic in specific:
            continue                 # absorbed by a more specific sibling
        prior = at_leaf.get(res.leaf)
        if prior is not None:
            if res.confidence > out[prior].confidence:
                out[prior] = res
            continue
        at_leaf[res.leaf] = len(out)
        out.append(res)
    return out
