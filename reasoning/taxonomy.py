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
# Cached tags (chunk_tags) and cached mapping results are keyed on this
# version. Whenever the SET of leaves changes, the fingerprint changes and
# every consumer treats older tags as stale (must re-classify). The human
# prefix is bumped manually when leaf *semantics* change without the set of
# tags changing (e.g. a definition tweak); the hash suffix auto-invalidates
# on any structural change even if someone forgets to bump the prefix.

import hashlib as _hashlib

_TAXONOMY_SCHEMA = "v1"


def _taxonomy_fingerprint() -> str:
    leaves: list[str] = []
    for _topic, _body in TAXONOMY.items():
        for _sub in _body["subcategories"]:
            leaves.append(f"{_topic}/{_sub}")
    leaves.append(UNCLASSIFIED)
    leaves.sort()
    digest = _hashlib.sha1("|".join(leaves).encode("utf-8")).hexdigest()[:8]
    return f"{_TAXONOMY_SCHEMA}-{digest}"


TAXONOMY_VERSION = _taxonomy_fingerprint()
