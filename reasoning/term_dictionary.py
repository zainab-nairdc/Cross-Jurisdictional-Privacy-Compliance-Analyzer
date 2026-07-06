"""Cross-Jurisdiction Privacy Term Dictionary — auto-generated.

Maintained via scripts/dictionary/ — generate_dictionary_from_corpus.py
to rebuild from the corpus, verify_dictionary_llm.py to LLM-audit the
citations, audit_term_citations.py to BM25-check each cited article.

Methodology:
  Stage 1: per-document LLM term extraction (Cardillo et al., 2025)
  Stage 2: per-country ranking
  Stage 3: cross-jurisdiction LLM matching with anti-hallucination
           validation — every label is verified to appear in the
           extracted-terms input before being accepted.
"""

from __future__ import annotations
import re


CATEGORIES = (
    "Roles", "Lawful basis", "Data categories", "Data subject rights",
    "Security & breach", "Cross-border", "Governance", "Enforcement", "Other",
)


# 9 confirmed cross-jurisdiction privacy concepts
TERMS: dict[str, dict] = {
    'cybersecurity': {
        "category":   'Security & breach',
        "definition": 'Preservation of confidentiality, integrity, and availability of information and information systems through the cyber medium.',
        "jurisdictions": {
            'India': {'term': 'Cyber security', 'citation': 'Section 3(a)(iii)'},
            'Kuwait': {'term': 'Cybersecurity', 'citation': '1.1 Definitions'},
        },
        "synonyms":      ['Cyber security'],
        "cluster_jurs":  ['India', 'Kuwait'],
    },
    'data protection authority': {
        "category":   'Enforcement',
        "definition": 'A public authority established to protect personal data and supervise compliance.',
        "jurisdictions": {
            'Bahrain': {'term': 'Personal Data Protection Authority', 'citation': 'Article (27)'},
            'Kuwait': {'term': 'CITRA', 'citation': 'Definitions'},
        },
        "synonyms":      ['CITRA', 'Personal Data Protection Authority'],
        "cluster_jurs":  ['Bahrain', 'Kuwait'],
    },
    'data protection impact assessment': {
        "category":   'Governance',
        "definition": 'A process assessing the rights of data subjects and risks to their personal data from processing activities.',
        "jurisdictions": {
            'Bahrain': {'term': 'Data Protection Impact Assessment', 'citation': 'Article (1)'},
            'India': {'term': 'Data Protection Impact Assessment', 'citation': 'Section 10(2)(c)(i)'},
        },
        "synonyms":      [],
        "cluster_jurs":  ['Bahrain', 'India'],
    },
    'data subject': {
        "category":   'Roles',
        "definition": 'An identified individual or an individual who can be identified by reference to personal data.',
        "jurisdictions": {
            'Bahrain': {'term': 'Data subject', 'citation': 'Article (1)'},
            'India': {'term': 'Data Principal', 'citation': 'Section 2(j)'},
        },
        "synonyms":      ['Data Principal'],
        "cluster_jurs":  ['Bahrain', 'India'],
    },
    'electronic signature': {
        "category":   'Data categories',
        "definition": 'Authentication of an electronic record by a subscriber using electronic technique or data identifying and distinguishing a person.',
        "jurisdictions": {
            'India': {'term': 'electronic signature', 'citation': 'Section 2(ta)'},
            'Kuwait': {'term': 'Electronic Signature', 'citation': 'Article 1'},
        },
        "synonyms":      [],
        "cluster_jurs":  ['India', 'Kuwait'],
    },
    'personal data': {
        "category":   'Data categories',
        "definition": 'Any information concerning an identified or identifiable individual.',
        "jurisdictions": {
            'Bahrain': {'term': 'Data or Personal Data', 'citation': 'Article (1)'},
            'Kuwait': {'term': 'Personal data (Personally Identifiable Information (PII))', 'citation': 'Definitions'},
        },
        "synonyms":      ['Data or Personal Data', 'Personal data (Personally Identifiable Information (PII))'],
        "cluster_jurs":  ['Bahrain', 'Kuwait'],
    },
    'processing': {
        "category":   'Governance',
        "definition": 'Any operation or set of operations performed upon personal data, including collection, recording, organizing, and storage.',
        "jurisdictions": {
            'Bahrain': {'term': 'Processing', 'citation': 'Article (1)'},
            'India': {'term': 'processing', 'citation': 'Section 2(x)'},
        },
        "synonyms":      [],
        "cluster_jurs":  ['Bahrain', 'India'],
    },
    'sensitive personal data': {
        "category":   'Data categories',
        "definition": 'Personal information revealing race, ethnicity, political opinions, religious beliefs, union affiliation, or criminal records.',
        "jurisdictions": {
            'Bahrain': {'term': 'Sensitive Personal Data', 'citation': 'Article (1)'},
            'India': {'term': 'sensitive personal data or information', 'citation': 'Section 43A Explanation(iii)'},
        },
        "synonyms":      ['sensitive personal data or information'],
        "cluster_jurs":  ['Bahrain', 'India'],
    },
    'service provider': {
        "category":   'Roles',
        "definition": 'A natural or legal person who provides communications, information technology, or other services.',
        "jurisdictions": {
            'India': {'term': 'service provider', 'citation': 'Section 6A(1) Explanation'},
            'Kuwait': {'term': 'Communications and Information Technology Service Provider (Service Provider)', 'citation': 'Definitions'},
        },
        "synonyms":      ['Communications and Information Technology Service Provider (Service Provider)'],
        "cluster_jurs":  ['India', 'Kuwait'],
    },
}


# ── Compatibility surface ──


def all_terms() -> list[dict]:
    return [{"canonical": k, **v} for k, v in sorted(TERMS.items())]


def by_category() -> dict[str, list[tuple[str, dict]]]:
    out: dict[str, list[tuple[str, dict]]] = {}
    for k, v in TERMS.items():
        out.setdefault(v.get("category", "Other"), []).append((k, v))
    return out


def lookup(term: str) -> dict | None:
    if not term:
        return None
    t = term.lower().strip()
    if t in TERMS:
        return TERMS[t]
    for canonical, entry in TERMS.items():
        if t in (s.lower() for s in entry.get("synonyms", [])):
            return entry
        for j_info in entry.get("jurisdictions", {}).values():
            if (j_info.get("term") or "").lower() == t:
                return entry
    return None


def synonyms_for_query(query: str) -> list[str]:
    if not query:
        return []
    out: set[str] = set()
    for canonical, entry in TERMS.items():
        keys = [canonical] + list(entry.get("synonyms", []))
        keys += [j.get("term", "") for j in entry.get("jurisdictions", {}).values() if j.get("term")]
        for key in keys:
            if not key or len(key) < 3:
                continue
            if re.search(r"(?<![A-Za-z])" + re.escape(key.lower()) + r"(?![A-Za-z])", query.lower()):
                out.update(s for s in keys if s and len(s) >= 3)
                break
    return sorted(out)


def expand_query(query: str) -> str:
    extra = synonyms_for_query(query)
    if not extra:
        return query
    add = " ".join(s for s in extra if s.lower() not in query.lower())
    return f"{query} {add}" if add else query
