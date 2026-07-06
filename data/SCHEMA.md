# `metadata.csv` Schema

Reference for the 25 columns in [metadata.csv](metadata.csv). Updated 2026-04-30.

Columns marked **[retrieval]** are read by the retriever at query time. Columns marked **[provenance]** are descriptive only.

## Column reference

| # | Column | Role | Notes |
|---|---|---|---|
| 0 | `Jurisdiction` | [retrieval] | One of: `Bahrain`, `India`, `Kuwait`, `BBK` |
| 1 | `Regulation Name + Version` | [provenance] | Human-readable title |
| 2 | `Document Title` | [provenance] | Filename stem (matches the source file in `data/regulations/...`) |
| 3 | `Document Type` | [provenance] | Free text (Law, Act, Ministerial Order, Direction, Internal Policy, etc.) |
| 4 | `Issuing Authority` | [provenance] | Free text |
| 5 | `Publication Date` | [retrieval] | ISO 8601 (`YYYY-MM-DD`). Date the doc was published. |
| 6 | `Effective Date` | [retrieval] | ISO 8601. Must be `>= Publication Date`. |
| 7 | `Last Updated` | [provenance] | ISO 8601. Last amendment / re-issue. |
| 8 | `Source URL` | [provenance] | Authoritative URL for citation. ⚠️ Several Kuwait URLs are unverified — see Open Items in CHANGES. |
| 9 | `Language` | [retrieval] | ISO 639-1 (`en`, `ar`, …). |
| 10 | `Section/Article Identifiers` | [provenance] | Free text describing the doc's structure (e.g., `Articles 1-60`, `Chapters I-VII (Sections 1-32)`) |
| 11 | `Scope Summary` | [provenance] | One-paragraph human summary |
| 12 | `Notes for Ingestion` | [provenance] | Free-text annotations for the ingestion team |
| 13 | `regulation_category` | [retrieval] | Controlled vocab — see below |
| 14 | `retrieval_priority` | [retrieval] | Controlled vocab — see below |
| 15 | `privacy_relevance` | [retrieval] | Controlled vocab — see below |
| 16 | `applicable_sector` | [retrieval] | Controlled vocab — see below |
| 17 | `superseded` | [retrieval] | `TRUE` or `FALSE`. Never empty. |
| 18 | `superseded_by` | [retrieval] | `document_id` of replacement, or empty |
| 19 | `concept_tags` | [retrieval] | Comma-separated; controlled vocab — see [§ `concept_tags` controlled vocabulary](#concept_tags-controlled-vocabulary) at the end of this file |
| 20 | `document_id` | [retrieval] | Stable short ID — see ID conventions below |
| 21 | `parent_regulation` | [retrieval] | `document_id` of parent law, or empty for top-level docs |
| 22 | `version` | [retrieval] | `v1`, `1.0`, `26/2024`, `RBI/2023-24/107`, etc. |
| 23 | `chunk_strategy` | [retrieval] | Controlled vocab — see below |
| 24 | `cross_references` | [retrieval] | `document_id[:locator]` tokens, `;` separated. |

## Controlled vocabularies

### `regulation_category`

| Value | Meaning |
|---|---|
| `privacy_core` | Primary privacy law (e.g., PDPL, DPDP Act, DPPR). Always retrieved for privacy queries. |
| `privacy_implementing` | Subordinate rules/orders implementing a privacy_core law. |
| `privacy_narrow` | Privacy-adjacent, narrow scope (DPO fees, criminal-data confidentiality). Retrieved only when topically matched. |
| `banking_regulator` | Sector-specific rules from a banking regulator (CBB, CBK, RBI). |
| `cybersecurity` | National or sectoral cybersecurity frameworks (CITRA, RBI Cyber). |
| `cloud_regulation` | Cloud-specific rules (CITRA Cloud Framework). |
| `adjacent_law` | Non-privacy law with privacy-relevant provisions (IT Act 2000, Electronic Transactions Law). |
| `internal_policy` | BBK internal policy (governance level). |
| `internal_procedure` | BBK internal procedure (operational, derived from policy). |
| `internal_sop` | BBK Standard Operating Procedure (branch-specific or task-specific). |
| `internal_guideline` | BBK guideline (advisory, less binding than policy). |

### `retrieval_priority`

Determines whether a document is in the default retrieval pool.

| Value | Retriever behavior |
|---|---|
| `primary` | Always candidate for default retrieval. Should dominate top-k for in-scope queries. |
| `secondary` | Candidate for default retrieval, but ranked below `primary` for the same query relevance score. |
| `reference_only` | **Excluded** from default retrieval. Surfaces only when (a) explicitly cited by `document_id`, or (b) another retrieved doc references it via `cross_references`. |

### `privacy_relevance`

| Value | Meaning |
|---|---|
| `critical` | Core privacy law/policy — gap-analysis target. |
| `high` | Substantial privacy provisions; commonly retrieved. |
| `partial` | Some privacy-relevant clauses; retrieve when query is sector-specific. |
| `low` | Tangential — fee schedules, public registers, criminal proceedings carve-outs. |

### `applicable_sector`

| Value | Meaning |
|---|---|
| `general` | Economy-wide application (most privacy laws and PDPA orders). |
| `banking` | Bank-specific (CBB, CBK, RBI directions, BBK internal). |
| `cloud_services` | Cloud service providers. |
| `telecom_it` | Licensed telecom and IT service providers. |

### `chunk_strategy`

Hint for the chunker. The retriever does not read this directly.

| Value | When to use |
|---|---|
| `article` | Article-numbered laws and ministerial orders (split per article). |
| `section` | Section-numbered laws and frameworks (split per section). |
| `chapter` | Chapter-organized RBI directions and CBK guides (split per chapter, then sub-split). |
| `rule` | DPDP Rules 2025 (split per rule). |
| `clause` | BBK internal docs with numbered clauses/sections (split per top-level clause). |
| `whole` | Short documents that should not be sub-chunked (e.g., the BBK Privacy Statement). |

### `superseded`

`TRUE` or `FALSE`. Never empty. If `TRUE`, `superseded_by` MUST contain a valid `document_id`.

The retriever should exclude `superseded=TRUE` docs from default retrieval (same as `reference_only` semantics).

## `document_id` conventions

Pattern: `<JURISDICTION>-<DOC_FAMILY>[-<SUBID>]`

- `JURISDICTION`: `BH` (Bahrain), `IN` (India), `KW` (Kuwait), `BBK` (BBK internal)
- `DOC_FAMILY`: short uppercase token (`PDPL`, `PDPA-O42`, `DPDP-ACT`, `CBK-CORF`, `LGL-001`, …)
- `SUBID`: optional disambiguator (`O42` for Order 42; branch suffix for SOPs like `OPS-012-BH`)

IDs MUST be unique across the file. Once assigned, an ID is permanent — even after the doc is superseded. Citations live forever.

## `cross_references` format

Semicolon-separated tokens. Each token is `<document_id>` or `<document_id>:<locator>`.

Locators use the doc's own structure: `Art.8`, `Sec.43A`, `Sec.5`, `Rule.7`, `Chap.IX`. Whitespace inside tokens is allowed; tokens are trimmed.

Examples:
- `BH-PDPL:Art.12` — Article 12 of Bahrain PDPL
- `IN-IT-ACT:Sec.43A; IN-IT-ACT:Sec.72A` — both legacy IT Act sections
- `BH-PDPA-O43:Art.2; BH-PDPL:Art.8; BH-PDPA-O43:Art.4` — multiple targets

The retriever should use `cross_references` to (a) auto-include directly-cited docs even when `retrieval_priority=reference_only` or `superseded=TRUE`, and (b) boost the rank of cited targets when the citing doc is in the result set.

## Retrieval cheat-sheet

Default retrieval filter (pseudo-SQL):

```
SELECT * FROM metadata
WHERE retrieval_priority IN ('primary', 'secondary')
  AND superseded = 'FALSE'
  AND (
        applicable_sector = 'general'
     OR applicable_sector = <user's sector context>
      )
ORDER BY
    CASE retrieval_priority WHEN 'primary' THEN 0 WHEN 'secondary' THEN 1 END,
    CASE privacy_relevance WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'partial' THEN 2 ELSE 3 END,
    <semantic_score> DESC
```

When a retrieved doc has non-empty `cross_references`, hydrate those targets into the context window even if they would be excluded by the filter above (citation chain).

## `concept_tags` controlled vocabulary

Closed list of tags allowed in the `concept_tags` column. Synonyms are forbidden — pick a canonical form and stick to it.

### Naming rules

- **Pascal_Snake_Case**: each word capitalised, words joined by underscore (`Cross_Border_Transfer`, not `cross-border-transfer` or `crossBorderTransfer`).
- **No spaces**, no hyphens, no slashes.
- **Singular noun phrases** (`Data_Subject_Rights`, not `Right_to_Access`).
- **No abbreviations** unless universally recognised in the domain (`DPO`, `DPIA` are OK; `DSR` is not — use `Data_Subject_Rights`).
- **No jurisdiction prefixes** in tags. `Cross_Border_Transfer` covers Bahrain Article 12, DPDP Chapter on transfers, and Kuwait DPPR Articles equally — the jurisdictional context comes from the row's `Jurisdiction` column.

### Adding a new tag

1. Check this vocab first. If a near-synonym exists, use the existing one.
2. If genuinely new: add it to the relevant theme below with a one-line description, then use it in `metadata.csv`.
3. Never introduce a tag in `metadata.csv` without registering it here. Vocab drift is the killer for faceted retrieval.

### Tag list (organised by theme)

#### Lawfulness & consent
| Tag | Meaning |
|---|---|
| `Lawful_Basis` | Legal grounds for processing personal data (consent, contract, legitimate interest, legal obligation, etc.) |
| `Consent_Standard` | Requirements for valid consent — informed, specific, freely given, withdrawable. |
| `Consent_Notice` | Form and content of the notice presented to the data subject when collecting consent. |
| `Consent_Manager` | India DPDP-specific role; entities that manage consent on behalf of data principals. |
| `Cookie_Consent` | Cookie walls, tracking technology consent. |
| `Automated_Decision_Making` | Right to object to or get review of automated/profiling decisions. |

#### Data subject rights
| Tag | Meaning |
|---|---|
| `Data_Subject_Rights` | Generic — access, rectification, erasure, portability, objection. |
| `Access_Requests` | Specifically the right to access / DSAR procedures. |
| `Rectification` | Right to correct inaccurate data. |
| `Erasure` | Right to deletion ("right to be forgotten"). |
| `Complaints_Procedure` | How data subjects lodge complaints with the supervisory authority. |

#### Cross-border & localisation
| Tag | Meaning |
|---|---|
| `Cross_Border_Transfer` | Sending personal data across national borders. |
| `Adequacy_Decision` | Whitelist / equivalent-protection determinations. |
| `Data_Localisation` | Requirements to keep data physically inside a jurisdiction. |
| `Prior_Authorization` | Requirement to get authority approval before processing or transferring. |

#### Security
| Tag | Meaning |
|---|---|
| `Security_Measures` | Generic security obligations (technical and organisational measures). |
| `Encryption` | Specific encryption requirements. |
| `Log_Retention` | Mandated retention periods for system / access logs. |
| `Vulnerability_Assessment` | VA / VAPT requirements. |
| `Penetration_Testing` | PT requirements (often paired with VA). |
| `Privacy_By_Design` | "By design and by default" obligation. |
| `DPIA` | Data Protection Impact Assessment requirement. |

#### Breach & incident
| Tag | Meaning |
|---|---|
| `Breach_Notification` | Generic breach-notification duty. |
| `Breach_Notification_Timeline` | The specific time window (e.g., 72 hours, 1 hour). Use this when the row contains a clock requirement. |
| `Incident_Response` | Detect / respond / recover obligations. |
| `Cyber_Resilience` | Broader cyber and operational resilience programmes. |
| `Operational_Resilience` | Operational continuity, beyond pure cyber. |
| `Business_Continuity` | BCP / DR with RTO/RPO. |

#### Governance & DPO
| Tag | Meaning |
|---|---|
| `DPO` | Data Protection Officer — appointment, qualifications, duties. |
| `Data_Protection_Guardian` | Bahrain-specific term for DPO. Use both tags when both terms apply. |
| `Accountability_Framework` | Demonstrable compliance, records of accountability. |
| `Data_Governance` | Ownership, stewardship, accountability for data. |
| `IT_Governance` | IT-specific governance (board oversight, CISO, etc.). |
| `Records_of_Processing` | RoPA requirement. |
| `Information_Systems_Audit` | IS audit requirement. |
| `Governance_Oversight` | Board-level / senior-management oversight. |
| `Notification_Authority` | Notifying the supervisory authority of processing or DPO appointment. |
| `Registration_Fees` | Fees for DPO/processor/controller registration. |

#### Special categories of data
| Tag | Meaning |
|---|---|
| `Sensitive_Data` | Sensitive / special categories. |
| `Children_Data` | Children's personal data; parental consent. |
| `Criminal_Data` | Personal data related to criminal proceedings. |
| `Significant_Data_Fiduciary` | India DPDP-specific — heightened obligations for SDFs. |

#### Third-party & outsourcing
| Tag | Meaning |
|---|---|
| `Third_Party_Risk` | Risk management for vendors and external recipients. |
| `Outsourcing` | Outsourcing arrangements (especially RBI directions). |
| `Cloud_Computing` | Use of cloud services / cloud-specific rules. |
| `Data_Processor` | Processor obligations (vs. controller/fiduciary). |
| `Contractual_Safeguards` | Mandatory contractual clauses (data confidentiality, audit rights, etc.). |
| `Audit_Rights` | Right to audit a processor / vendor. |
| `Exit_Strategy` | Termination and data return/destruction at end of vendor relationship. |
| `Data_Sharing` | Disclosing personal data to third parties. |

#### Disclosure, customers, telecom
| Tag | Meaning |
|---|---|
| `Privacy_Notice` | The notice the controller publishes to data subjects. |
| `Disclosure_Requirements` | What the controller must disclose, when, how. |
| `Customer_Protection` | CBK/CBB customer-protection rules. |
| `Customer_Data_Handling` | Internal customer data handling procedures. |
| `Customer_Data_Protection` | Customer-data protection requirements (banking-supervisor framing). |
| `Telecom_Privacy` | Telecom / ISP privacy rules. |

#### Data lifecycle
| Tag | Meaning |
|---|---|
| `Data_Retention` | Retention periods. |
| `Data_Disposal` | Secure disposal / destruction of data. |
| `Data_Lifecycle` | End-to-end lifecycle policy combining retention + disposal. |
| `Data_Classification` | Data classification schemes (public, internal, confidential, etc.). |
| `Data_Confidentiality` | Confidentiality obligations specifically. |

#### Operational
| Tag | Meaning |
|---|---|
| `Operational_Procedures` | Operational/procedural how-to content (BBK SOPs). |
| `Data_Handling` | Generic data-handling operational rules. |

#### Misc — laws of adjacent / special scope
| Tag | Meaning |
|---|---|
| `Electronic_Signatures` | E-signature validity. |
| `Electronic_Records` | Legal recognition of electronic records. |
| `Authentication` | Authentication requirements. |
| `Unauthorized_Access` | Cybercrime-style provisions. |
| `Unauthorized_Disclosure` | Penalty for unauthorised disclosure (IT Act 72A, etc.). |
| `Data_Disclosure` | Generic disclosure-offence framing. |
| `Compensation` | Civil compensation for negligence (IT Act 43A, etc.). |
| `Criminal_Penalties` | Criminal sanctions. |
| `Confidentiality` | General confidentiality obligations. |
| `Enforcement` | Enforcement powers, supervisory authority procedures. |
| `Public_Registers` | Publicly-accessible personal data registers. |

### Synonyms to avoid

These look like reasonable tags but ARE NOT canonical — use the form on the right.

| ❌ Don't use | ✅ Use instead |
|---|---|
| `Data_Protection_Officer` | `DPO` |
| `Data_Subject_Access_Request` / `DSAR` | `Access_Requests` |
| `Right_To_Erasure` / `Right_To_Be_Forgotten` | `Erasure` |
| `Privacy_Impact_Assessment` / `PIA` | `DPIA` |
| `Cross_Border_Data_Flow` / `International_Transfer` | `Cross_Border_Transfer` |
| `Data_Breach` (as a tag for the obligation) | `Breach_Notification` |
| `72_Hour_Rule` | `Breach_Notification_Timeline` |
| `Vendor_Management` | `Third_Party_Risk` |
| `Cloud` | `Cloud_Computing` |
| `BCM` / `DR` | `Business_Continuity` |
| `Children` / `Minors` | `Children_Data` |
| `Sensitive_Personal_Data` / `SPI` / `SPDI` | `Sensitive_Data` |
| `Records_Of_Processing_Activities` / `RoPA` | `Records_of_Processing` |
