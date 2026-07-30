# CJPCA — Client Demo Runbook

A step-by-step script for demoing the three core features (Comparison, Policy
Mapping, Copilot) plus the supporting screens. Keep this open on a second screen.

---

## 0. Pre-flight (2 min before the client joins)

| Check | Action |
|-------|--------|
| Server running | `http://127.0.0.1:8000` should load the login page |
| Login | user **`admin`** · password **`admin12345`** |
| Warm up the LLM | Open **Copilot**, ask any question once so Ollama loads the model into GPU (first call is slow, ~5–10s; after that it's warm) |
| Model | Local **`qwen2.5:7b-instruct`** on your RTX 3070 GPU — no internet/API keys needed |

> **Data note (for you, not the client):** the Comparison and Mapping screens are
> pre-loaded with **curated, accurate demo data** grounded in the real Bahrain PDPL,
> India DPDP Act 2023, and Kuwait DPPR. The **Copilot answers live** on the GPU. If
> the client asks to run a fresh comparison/mapping live, it works — just slower
> (30–90s) and thinner than the pre-loaded examples.

---

## 1. COMPARISON — regulation-to-regulation

### How it works
Hybrid retrieval (ChromaDB dense vectors + SQLite BM25 keyword) pulls the relevant
clauses from **both** regulations, filtered by the compliance **taxonomy** (8 topics:
consent, cross-border, data-subject rights, breach notification, DPO, children,
retention, security). A LangGraph reasoning workflow then, per topic:
**retrieve → draft obligation pair → verify citations → classify the relationship**.
Every row is grounded in source text with a citation and a confidence score.

### Relationship types the client will see
`Equivalent` · `Stricter in A` · `Stricter in B` · `Additional in A/B` · **`Conflicting`** (red — needs legal review)

### What to show — click path
1. Sidebar → **Comparison**.
2. Open the flagship run: **Bahrain PDPL ↔ India DPDPA** → `http://127.0.0.1:8000/comparison/runs/11/`
3. Walk the tabs:
   - **Obligations** — the side-by-side table. Point at the **Cross-border transfers**
     row flagged **Conflicting** — Bahrain uses an *adequacy allow-list*, India a
     *Government deny-list*: structurally opposite. This is the "aha" row.
   - **Overview / Charts** — the relationship mix at a glance.
   - Point out the **citations** (e.g. *PDPL Art. 12*, *DPDP Act s. 16*) and
     **confidence** on each row — nothing is unsourced.

### Talking points
- "Every comparison is grounded in the actual clause text with a citation — no hallucinated law."
- "The engine flags where two regimes **conflict**, so legal can focus only on the divergences."
- Contrast pairs: **Bahrain ↔ Kuwait** (run 12) is *mostly Equivalent* — two closely-aligned
  GCC regimes; **Bahrain ↔ India** (run 11) diverges sharply. That contrast tells the story.

### Other seeded runs
- Bahrain ↔ Kuwait — `/comparison/runs/12/` (highly aligned; 5 Equivalent)
- India ↔ Kuwait — `/comparison/runs/13/` (several India-stricter + a cross-border conflict)

---

## 2. POLICY MAPPING — internal policy vs regulation

### How it works
Takes a BBK internal policy, auto-classifies which topics it covers, retrieves the
matching regulatory obligations (Bahrain PDPL), and for each obligation asks:
**does the policy cover this?** Output is a coverage verdict + evidence + a
remediation-ready gap.

### Coverage indicators
`Covered` (green) · `Partial` (amber) · `Requires Review` · **`Not Covered`** (red gap) — each with a **severity** (Critical/High/Medium/Low).

### What to show — click path
1. Sidebar → **Policy Mapping**.
2. Show a **strong** policy first, then a **problem** policy — the contrast lands:
   - **BBK Data Privacy Protection Policy** (strong) → `http://127.0.0.1:8000/mapping/7/`
     — mostly **Covered**; 2 gaps (cross-border transfer lacks an adequacy step; breach
     notification has no regulator deadline).
   - **BBK Customer Data Handling Procedure** (contradictory) → `http://127.0.0.1:8000/mapping/9/`
     — **Critical** gaps: authorises overseas transfers with no adequacy check, and
     retains customer data *indefinitely* — both contradict PDPL.
3. Click any gap row → the **evidence panel** shows the policy excerpt, the regulatory
   requirement it's measured against, and an **AI-drafted remediation** suggestion.

### Talking points
- "It doesn't just say *not covered* — it quotes the policy, cites the regulation, rates
  severity, and drafts the fix."
- "Coverage rolls up per policy so compliance sees their exposure at a glance."

### Other seeded mappings
- BBK Data Subject Rights Procedure (partial) → `/mapping/8/` — *in the reviewer queue*
- BBK Retention & Disposal Policy (outdated) → `/mapping/10/` — 5 gaps

---

## 3. COPILOT — grounded Q&A (LIVE on the GPU)

### How it works
A chat over the indexed corpus. It runs the **same guard-railed pipeline** as the
structured workflows: retrieve → draft → **verify citations against the source chunks**
→ answer. It preferentially uses **approved** comparison/mapping results, and cites
inline. If it can't fully verify, it hedges rather than bluffing.

### What to show — click path
1. Sidebar → **Copilot** (or the chat panel).
2. Ask a grounded question, e.g.:
   - *"What are the requirements for transferring personal data outside Bahrain under the PDPL?"*
   - *"How does India's cross-border transfer rule differ from Bahrain's?"*
   - *"Which BBK policies have gaps in cross-border transfer?"*
3. Point at the **inline citations** (e.g. *Bahrain PDPL, Art. 12*) under the answer.

### Talking points
- "It answers **only from the retrieved source text** and cites it — and it will tell you
  when it *can't* fully verify rather than making something up."
- "It's reading the same indexed corpus and the approved analyses, so the chat stays
  consistent with the structured screens."

> **Heads-up:** the live answer sometimes opens with *"I couldn't synthesise a fully-
> verified answer, but here's what the sources say…"* — that's the citation-verifier being
> conservative, **not** a failure. The cited content underneath is correct. Frame it as a
> feature: "it's honest about confidence."

---

## 4. Supporting screens (great for "and then what?")

| Screen | What it shows | URL |
|--------|---------------|-----|
| **Review & Validate** | Draft → Reviewed → Approved workflow + audit trail; the DSR mapping is waiting in the queue | `/review/` |
| **Analytics** | Coverage dashboards + heatmap | `/analytics/` |
| **Gap Register** | Every confirmed gap across approved analyses, by severity, with remediation + due dates | `/analytics/gaps/` |
| **Conflict Scanner** | Every `Conflicting` obligation across jurisdictions (the cross-border conflicts) | `/analytics/conflicts/` |
| **History / Audit** | Full audit log of every action | `/history/` |

---

## 5. Suggested 5-minute flow

1. **Login** → dashboard (30s).
2. **Comparison** — open Bahrain ↔ India, land on the **Conflicting** cross-border row (90s).
3. **Policy Mapping** — strong policy, then the contradictory one; open a gap's evidence + remediation (90s).
4. **Copilot** — one live cross-border question, point at citations (60s).
5. **Gap Register / Analytics** — "everything rolls up here for the compliance team" (30s).

---

## Credentials
- URL: `http://127.0.0.1:8000`
- Username: `admin` · Password: `admin12345`
