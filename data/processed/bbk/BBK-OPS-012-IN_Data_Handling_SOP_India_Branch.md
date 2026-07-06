**BBK BANK**

Bank of Bahrain and Kuwait

**India Branch — Branch Operations**

**Data Handling & Classification**

**Standard Operating Procedure**

*Branch-Specific Local Supplement*

| **Document ID**    | BBK-OPS-012-IN                                   |
|--------------------|--------------------------------------------------|
| **Parent Policy**  | BBK-OPS-012 v1.3                                 |
| **Branch**         | India Branch                                     |
| **Jurisdiction**   | Republic of India                                |
| **Version**        | 1.0                                              |
| **Effective Date** | 1 March 2025                                     |
| **Regulatory Ref** | DPDPA 2023 / RBI Master Directions / IT Act 2000 |
| **Classification** | CONFIDENTIAL — INTERNAL USE ONLY                 |

## 1. Purpose and Relationship to Group Policy

This document is a jurisdiction-specific supplement to the BBK Group Data Handling & Classification SOP (BBK-OPS-012). It adapts Group standards to the legal and regulatory obligations applicable to BBK's India Branch, operating under the regulatory supervision of the Reserve Bank of India (RBI) and subject to India's Digital Personal Data Protection Act 2023 (DPDPA).

Where provisions of this supplement differ from Group policy, the more stringent requirement applies. Staff must also be aware that India's data protection framework is evolving; this document will be updated as DPDPA Rules are notified by the Data Protection Board of India.

*ℹ As at the effective date of this document, the DPDPA 2023 has received Presidential assent but its implementing Rules have not yet been fully notified. This SOP reflects the obligations as currently understood; updates will be issued as Rules are published.*

## 2. Applicable Regulatory Framework

| **Regulation / Authority**                                               | **Relevance to This SOP**                                                                                                                |
|--------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| Digital Personal Data Protection Act 2023 (DPDPA)                        | Primary personal data protection law; establishes obligations for Data Fiduciaries, consent requirements, and rights of Data Principals. |
| Information Technology Act 2000 (IT Act) & IT (Amendment) Act 2008       | Provisions on cybersecurity, electronic records, and liability for data breaches remain operative alongside DPDPA.                       |
| RBI Master Direction on KYC (2016, as amended)                           | Customer identification, due diligence, record retention requirements for banks in India.                                                |
| RBI Master Direction — Information Technology Framework for Banks (2023) | IT governance, data security, outsourcing, and cloud storage requirements.                                                               |
| Prevention of Money Laundering Act 2002 (PMLA) & Rules                   | Retention and reporting obligations for transaction and customer identification records.                                                 |
| Data Protection Board of India (DPBI)                                    | Regulatory authority under DPDPA; adjudicates complaints and imposes penalties.                                                          |

## 3. Key Terminology — DPDPA Alignment

India's DPDPA uses distinct terminology that maps to Group policy concepts as follows:

| **DPDPA Term**                   | **Group Policy Equivalent**   | **Notes**                                                                                                                   |
|----------------------------------|-------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| Data Fiduciary                   | Data Controller (BBK)         | BBK India Branch is a Data Fiduciary.                                                                                       |
| Data Principal                   | Data Subject                  | The individual whose personal data is processed.                                                                            |
| Data Processor                   | Data Processor / Vendor       | Third parties processing data on BBK's instructions.                                                                        |
| Consent Manager                  | N/A (India-specific role)     | DPDPA introduces a registered Consent Manager intermediary for managing consent. To be implemented when Rules are notified. |
| Significant Data Fiduciary (SDF) | N/A (India-specific)          | SDFs face enhanced obligations. BBK India's SDF status will be assessed upon DPBI designation.                              |

## 4. Consent Management — India Branch Requirements

The DPDPA introduces a consent-first model for processing personal data. The India Branch must:

- Provide a clear and plain-language notice to Data Principals before or at the time of collecting personal data, describing the purpose of processing and their rights.
- Obtain free, specific, informed, unconditional, and unambiguous consent through a clear affirmative action.
- Maintain a consent record for each Data Principal, including the date, channel, and specific consent given.
- Ensure consent can be withdrawn as easily as it was given; withdrawal must be acted upon promptly.
- Identify and document all processing activities that rely on Legitimate Use (the DPDPA's alternative to legitimate interests) rather than consent, including: legal obligations, medical emergencies, state functions, and employment-related processing.

*ℹ Unlike GDPR, India's DPDPA does not list 'legitimate interests' as a broad lawful basis. Processing without consent must fall within one of the defined 'Legitimate Uses' in Section 7 of the DPDPA. Legal review is required before relying on any Legitimate Use basis.*

## 5. Data Retention — India Regulatory Schedule

| **Data Category**                     | **Group Default**     | **India Requirement**            | **Legal Basis**                     |
|---------------------------------------|-----------------------|----------------------------------|-------------------------------------|
| KYC / Customer ID Records             | 10 years              | 10 years post-relationship       | RBI KYC Master Direction; PMLA 2002 |
| Transaction Records                   | 10 years              | 10 years                         | PMLA 2002, Rule 10                  |
| Loan & Credit Files                   | 10 years              | 12 years post-settlement         | Limitation Act 1963; RBI Directions |
| Consent Records                       | N/A (new requirement) | Duration of processing + 3 years | DPDPA 2023 (anticipated Rules)      |
| Employee Records                      | 7 years               | 8 years post-employment          | Shops & Establishments Act; DPDPA   |
| Suspicious Transaction Reports (STRs) | 10 years              | 10 years                         | PMLA 2002 / FIU-IND Guidance        |
| Electronic / System Audit Logs        | 5 years               | 5 years                          | RBI IT Framework for Banks 2023     |

*ℹ The DPDPA provides that personal data must be erased once the purpose of processing is served, unless retention is required by law. This introduces a storage limitation obligation more explicit than in some other Gulf frameworks — the India Branch must implement automated retention flags for personal data not covered by a statutory retention period.*

## 6. Cross-Border Data Transfers — India

The DPDPA permits transfer of personal data to countries or territories notified by the Central Government as approved for transfer. As at the effective date of this SOP:

- The approved country list has not yet been published by the Government of India.
- In the interim, BBK India Branch shall apply a restrictive approach: cross-border transfers of personal data should be minimized and documented.
- Transfers that are operationally necessary (e.g., to Group IT systems) must be reviewed and approved by the Branch Compliance Officer and Group DPO.
- Intra-group transfers to BBK Bahrain and BBK Kuwait are subject to the same transfer restrictions and must be documented pending the publication of approved country lists.

*ℹ RBI has separate data localisation requirements for payment data. All payment system data must be stored exclusively within India. This requirement is absolute and not subject to any exceptions. The IT and Operations teams have confirmed that payment data is stored locally; this must be verified at each system review.*

## 7. Data Subject (Data Principal) Rights — India Procedure

Under the DPDPA, Data Principals have the following rights which the India Branch must facilitate:

- Right to Information: Access to a summary of personal data processed and the processing activities.
- Right to Correction and Erasure: Request correction of inaccurate or incomplete data, and erasure of data where the purpose is served.
- Right to Grievance Redressal: Raise grievances with the Data Fiduciary (BBK India) before escalating to the DPBI.
- Right to Nominate: Nominate another individual to exercise rights in the event of death or incapacity.

Handling timeline for India Branch:

- Acknowledge requests within 5 business days.
- Respond within 30 calendar days (extendable to 45 days in complex cases with notice).
- Grievances must be addressed within the period prescribed by the DPDPA Rules (anticipated: 30 days).
- Log all requests in Form BBK-IN-DSR-001 and report monthly to the Branch Compliance Officer.

## 8. Breach Notification — India Requirements

- Personal data breaches must be reported to the Data Protection Board of India (DPBI) within the timeframe prescribed in the DPDPA Rules (anticipated: 72 hours for significant breaches).
- Affected Data Principals must be individually notified in the prescribed form and manner.
- All breaches — regardless of severity — must be logged in the Group Breach Register within 24 hours.
- The India Branch Compliance Officer coordinates DPBI notification in consultation with the Group DPO and Legal Division.
- Given the DPDPA Rules are pending notification, the Branch must apply best-practice notification timelines (72 hours to regulator; prompt notification to data subjects) until Rules are published.

## 9. Local Roles and Contacts

| **Role**                                   | **Responsibility**                                                                                                       |
|--------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| Branch Compliance Officer — India          | Primary regulatory contact for DPBI and RBI data matters; manages breach notifications; approves cross-border transfers. |
| Branch Privacy Liaison                     | Processes Data Principal rights requests; maintains consent records and local data registers.                            |
| RBI Regulatory Liaison                     | Manages RBI correspondence on IT, KYC, and data-related matters.                                                         |
| Chief Information Security Officer (India) | Oversees IT security controls; ensures data localisation requirements are met; manages cyber incident response.          |
| Group DPO (escalation)                     | Escalation point for cross-border transfers, DPDPA interpretation queries, and significant breach assessments.           |
