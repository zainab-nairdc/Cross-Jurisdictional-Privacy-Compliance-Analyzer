**BANK OF BAHRAIN AND KUWAIT (BBK)**

**Security Incident Response Standard Operating Procedure**

Document Reference: PROC-012

Version: 1.0

Effective Date: 1 January 2025

Document Owner: Chief Information Security Officer (CISO)

Classification: Internal — Restricted

Review Cycle: Annual

|   **Version** | **Date**   | **Author**   | **Description**   |
|---------------|------------|--------------|-------------------|
|           1.0 | 01/01/2025 | CISO Office  | Initial release   |

## 1. Purpose and Scope

This Standard Operating Procedure (SOP) establishes the framework for identifying, reporting, containing, investigating, and resolving security incidents — including personal data breaches — at Bank of Bahrain and Kuwait (BBK). It defines roles, responsibilities, timelines, and escalation paths to ensure a consistent, legally compliant, and auditable incident response process.

This SOP applies to:

- All BBK employees, contractors, and third-party service providers
- All BBK systems, applications, networks, and data repositories
- All types of security incidents including personal data breaches, unauthorized access, malware, ransomware, insider threats, and system outages affecting data integrity or confidentiality
- All jurisdictions in which BBK operates, including the Kingdom of Bahrain, Kuwait, and India

## 2. Regulatory and Legal Basis

This SOP is designed to ensure compliance with the following regulatory frameworks:

| **Regulation / Framework**                                                 | **Jurisdiction**   | **Key Obligation**                                      |
|----------------------------------------------------------------------------|--------------------|---------------------------------------------------------|
| Personal Data Protection Law No. 30 of 2018 (PDPL)                         | Bahrain            | Breach notification to PDPB and data subjects           |
| PDPA Ministerial Order No. 43/2022 — Technical and Organisational Measures | Bahrain            | Documentation of breaches; controller obligations       |
| CBK Cyber Operational Resilience Framework (CORF) 2025                     | Kuwait             | Incident response, reporting to CBK                     |
| Data Privacy Protection Regulation — Administrative Decision 26/2024       | Kuwait             | Data subject notification and breach handling           |
| Digital Personal Data Protection Act 2023 (DPDP Act)                       | India              | Intimation to Data Protection Board and Data Principals |
| Digital Personal Data Protection Rules 2025 (DPDP Rules)                   | India              | Breach description, timing, and notification format     |

## 3. Definitions

| **Term**                         | **Definition**                                                                                                                                                                                        |
|----------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Security Incident                | Any actual or suspected event that compromises the confidentiality, integrity, or availability of BBK information assets or systems.                                                                  |
| Personal Data Breach             | A security incident resulting in the accidental or unlawful destruction, loss, alteration, unauthorized disclosure of, or access to personal data transmitted, stored, or otherwise processed by BBK. |
| Data Fiduciary / Data Controller | BBK, as the entity that determines the purposes and means of processing personal data.                                                                                                                |
| Data Subject / Data Principal    | An identified or identifiable natural person whose personal data is processed by BBK.                                                                                                                 |
| Incident Response Team (IRT)     | The cross-functional team responsible for managing security incidents, comprising CISO, IT Security, Legal, Compliance, and DPO.                                                                      |
| PDPB                             | Personal Data Protection Board — the supervisory authority under Bahrain's PDPL.                                                                                                                      |
| Data Protection Board (DPB)      | The supervisory authority under India's DPDP Act 2023.                                                                                                                                                |
| RTO                              | Recovery Time Objective — the target time to restore normal operations after an incident.                                                                                                             |

## 4. Roles and Responsibilities

| **Role**                      | **Responsibilities**                                                                                                           |
|-------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| CISO                          | Overall accountability for incident response; approves escalation to regulators; chairs the IRT.                               |
| Data Protection Officer (DPO) | Assesses whether a personal data breach has occurred; leads regulatory notification decisions; coordinates with data subjects. |
| IT Security Team              | Technical detection, containment, eradication, and forensic investigation of incidents.                                        |
| Legal & Compliance            | Advises on regulatory notification obligations; reviews notification content; manages regulatory correspondence.               |
| IT Operations                 | System recovery and restoration activities; maintains audit logs.                                                              |
| Human Resources               | Manages insider threat investigations; supports disciplinary proceedings.                                                      |
| All Employees                 | Report suspected incidents immediately via the designated reporting channel.                                                   |

## 5. Incident Classification

All security incidents shall be classified upon initial triage according to the following severity matrix:

| **Level**   | **Severity**   | **Description**                                                                                   | **Response Time**         |
|-------------|----------------|---------------------------------------------------------------------------------------------------|---------------------------|
| P1          | Critical       | Large-scale personal data breach; ransomware affecting core banking; regulatory reportable event. | Immediate — within 1 hour |
| P2          | High           | Unauthorized access to customer data; confirmed malware; insider data exfiltration.               | Within 4 hours            |
| P3          | Medium         | Suspected breach under investigation; policy violation with data exposure risk.                   | Within 24 hours           |
| P4          | Low            | Minor policy violations; no confirmed data exposure; near-miss events.                            | Within 72 hours           |

## 6. Incident Response Phases

BBK's incident response follows a six-phase lifecycle aligned with ISO/IEC 27035 and applicable regulatory requirements.

### Phase 1 — Detection and Identification

Incidents may be detected through multiple channels including:

- Automated SIEM and security monitoring alerts
- Employee reports via the IT Security helpdesk or email: security@bbk.com
- Third-party vendor or partner notifications
- Regulatory or law enforcement notifications
- Customer complaints indicating unauthorized account access

Upon detection, the receiving party shall:

1. Log the incident in the BBK Incident Register immediately
2. Assign a unique Incident Reference Number (IRN)
3. Perform initial triage to classify severity (P1–P4)
4. Notify the CISO and DPO within 1 hour for P1/P2 incidents

### Phase 2 — Containment

Containment measures shall be implemented immediately upon classification. The IT Security Team shall:

- Isolate affected systems from the network to prevent further spread
- Revoke or suspend compromised credentials and access tokens
- Preserve forensic evidence — do not wipe affected systems before imaging
- Apply emergency patches or firewall rules where applicable
- Activate backup systems and failover procedures for critical services

Short-term containment is prioritized over system restoration to preserve evidence integrity.

### Phase 3 — Assessment and Personal Data Breach Determination

The DPO, in coordination with the IT Security Team and Legal, shall assess:

- Whether personal data was accessed, disclosed, altered, or destroyed
- The categories and approximate volume of data subjects affected
- The sensitivity of the data involved (e.g., financial data, health data, identity documents)
- The likely consequences for affected data subjects
- Whether the incident meets the threshold for regulatory notification

A Personal Data Breach Assessment Form (PROC-012-F1) shall be completed within 24 hours of incident detection for all P1 and P2 incidents.

### Phase 4 — Notification and Regulatory Reporting

BBK shall comply with the following jurisdiction-specific notification obligations:

#### 4.1 Bahrain — PDPL Article 18 / PDPA Order 43/2022

- The DPO shall notify the Personal Data Protection Board (PDPB) without undue delay upon confirming a reportable personal data breach
- Notification shall include: nature of the breach, categories and approximate number of data subjects affected, categories and approximate number of personal data records concerned, likely consequences, and measures taken or proposed
- Affected data subjects shall be notified where the breach is likely to result in high risk to their rights and freedoms
- Notification to data subjects is not required where: the affected personal data is encrypted and unintelligible; subsequent measures have eliminated the risk; individual notification would involve disproportionate effort

#### 4.2 Kuwait — CBK CORF 2025 / Administrative Decision 26/2024

- BBK's Kuwait operations shall report significant cyber incidents to the Central Bank of Kuwait (CBK) in accordance with the CORF 2025 reporting timelines
- The Incident Response Team shall prepare a formal incident report in the format prescribed by CBK
- Affected data owners (data subjects) shall be notified in accordance with Article 10 of Administrative Decision 26/2024

#### 4.3 India — DPDP Act 2023 / DPDP Rules 2025

- Upon becoming aware of a personal data breach, BBK India operations shall intimate the Data Protection Board (DPB) without delay
- Intimation shall include: a description of the breach including its nature, extent, timing and location; the categories and approximate number of Data Principals affected; the likely consequences of the breach; and measures taken or proposed
- Each affected Data Principal shall receive intimation in the form and manner prescribed by the DPB
- Intimation to the DPB shall be made in accordance with Rule 7 of the DPDP Rules 2025

### Phase 5 — Eradication and Recovery

Following containment and notification, the IT Security and Operations teams shall:

1. Remove malware, backdoors, and unauthorized access mechanisms
2. Patch and harden affected systems before reconnecting to production
3. Restore systems from clean, verified backups
4. Conduct post-restoration validation testing
5. Monitor restored systems for 72 hours post-recovery for signs of re-infection

Recovery activities shall be documented in the Incident Register with timestamps and responsible parties.

### Phase 6 — Post-Incident Review and Lessons Learned

Within 14 calendar days of incident closure, the CISO shall convene a Post-Incident Review (PIR) meeting. The PIR shall:

- Document a full incident timeline from detection to closure
- Identify root cause(s) of the incident
- Assess the effectiveness of containment and response measures
- Identify gaps in controls, processes, or awareness
- Define remediation actions with owners and target completion dates
- Update risk registers and control frameworks accordingly

A Post-Incident Review Report (PROC-012-F3) shall be submitted to the Board Risk Committee for P1 incidents within 30 days of closure.

## 7. Incident Documentation and Record Keeping

BBK shall maintain a comprehensive Incident Register capturing all security incidents regardless of severity. The following records shall be retained for a minimum of five (5) years:

- Initial incident report and triage assessment
- Personal Data Breach Assessment Form (PROC-012-F1)
- All regulatory notifications and correspondence (PROC-012-F2)
- Post-Incident Review Report (PROC-012-F3)
- Forensic investigation logs and evidence chain of custody records
- Communication logs with affected data subjects

All documentation shall be stored in BBK's secure document management system with access restricted to authorized personnel only.

## 8. Training and Awareness

BBK shall implement the following training obligations to ensure staff are equipped to identify and respond to security incidents:

- Annual mandatory security awareness training for all staff covering incident identification and reporting procedures
- Specialized incident response training for all IRT members — minimum once per year
- Tabletop exercise simulating a personal data breach scenario — minimum once per year
- Onboarding training for new joiners within 30 days of employment commencement

## 9. Third-Party and Vendor Incident Obligations

All third-party vendors and processors handling BBK personal data are contractually required to:

- Notify BBK of any confirmed or suspected personal data breach within 24 hours of detection
- Cooperate fully with BBK's incident investigation and provide all requested logs and evidence
- Not make any public statement or regulatory notification relating to the incident without prior written approval from BBK Legal
- Maintain and test their own incident response procedures consistent with BBK's requirements

Breach notification obligations for third parties are governed by BBK's Third-Party and Vendor Data Processing Policy (PROC-007).

## 10. Policy Review and Approval

| **Item**         | **Detail**                                                      | **Notes**    |
|------------------|-----------------------------------------------------------------|--------------|
| Document Owner   | Chief Information Security Officer (CISO)                       |              |
| Approved By      | Board Risk Committee                                            | January 2025 |
| Review Frequency | Annual or following a significant incident or regulatory change |              |
| Next Review Date | January 2026                                                    |              |
| Distribution     | CISO, DPO, Legal & Compliance, IT Security, HR, IT Operations   | Restricted   |

## Appendix A — Incident Response Contact Directory

| **Role**             | **Contact**                         | **Escalation Path**                              |
|----------------------|-------------------------------------|--------------------------------------------------|
| CISO                 | ciso@bbk.com                        | Primary incident commander                       |
| DPO                  | dpo@bbk.com                         | Personal data breach assessment and notification |
| IT Security Helpdesk | security@bbk.com  &#124;  Ext. 5000 | First point of contact for incident reporting    |
| Legal & Compliance   | legal@bbk.com                       | Regulatory notification approvals                |
| PDPB (Bahrain)       | www.pdpb.gov.bh                     | Bahrain supervisory authority                    |
| CBK (Kuwait)         | www.cbk.gov.kw                      | Kuwait supervisory authority                     |
| DPB (India)          | www.meity.gov.in                    | India supervisory authority                      |

## Appendix B — Notification Timeline Summary

| **Jurisdiction**   | **Regulatory Authority**   | **Notification Trigger**       | **Deadline**                            |
|--------------------|----------------------------|--------------------------------|-----------------------------------------|
| Bahrain            | PDPB                       | Confirmed personal data breach | Without undue delay                     |
| Kuwait             | CBK                        | Significant cyber incident     | Per CBK CORF 2025 timelines             |
| India              | Data Protection Board      | Confirmed personal data breach | Without delay (Rule 7, DPDP Rules 2025) |

This document is confidential and intended for internal use only. Unauthorized disclosure is prohibited.
