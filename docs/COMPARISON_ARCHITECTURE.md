# Comparison Feature — Full Architecture

> How regulation‑to‑regulation comparison works in CJPCA, from the button click
> to the rendered result. This documents the **actual code path** as it exists in
> the repo, not a generic RAG description. File/line references are included so
> you can jump straight to the source.

---

## 0. What the feature does (in one paragraph)

You pick **two regulations** (e.g. *Bahrain PDPL* vs *India DPDP Act*), optionally
narrow to specific **topics** (consent, breach notification, …), and hit **Run**.
The system retrieves the relevant clauses from *both* regulations, asks an LLM to
produce a structured, topic‑by‑topic comparison, then **verifies every citation
the LLM produced against the actual source text** before saving it. The result is
a table of *obligation rows* — each row says how the two regulations relate on one
topic (`Equivalent`, `Stricter in A/B`, `Additional in A/B`, `Conflicting`), with
a verbatim quote from each side, a confidence score, and a hallucination‑risk
score. Everything is grounded in retrieved source text with click‑through
citations.

---

## 1. The layers involved

A single comparison touches four layers. The AI runs **in‑process** with Django —
there is no separate AI service.

```
┌───────────────────────────────────────────────────────────────────────┐
│  DJANGO WEB APP        cjpca/apps/comparison/                          │
│  • Picker screen, POST handler, results workspace (8 tabs), exports    │
│  • Persists ComparisonRun + ComparisonResult rows                      │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ calls compare_regulations(...)
┌───────────────────────────────▼───────────────────────────────────────┐
│  REASONING LAYER       reasoning/                                      │
│  • workflows.py     — the public compare_regulations() entry + LangGraph│
│  • workflow_helpers — format chunks, verify citations, NLI scoring     │
│  • generator.py     — builds the LLM client (Ollama primary)           │
│  • prompts/         — comparison_workflow.yaml (the actual prompt)     │
│  • schemas.py       — ComparisonReport / ObligationComparison (pydantic)│
│  • taxonomy.py      — the 12‑topic compliance taxonomy                 │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ hybrid_search(...)
┌───────────────────────────────▼───────────────────────────────────────┐
│  RETRIEVAL LAYER       retrieval/                                      │
│  • ChromaDB dense vectors + SQLite FTS5 BM25, fused + reranked         │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ reads
┌───────────────────────────────▼───────────────────────────────────────┐
│  DATA                  chroma_data/ (vectors + bm25.db + chunk_tags)   │
│                        db.sqlite3 (Documents, Runs, Results, audit)    │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 2. End‑to‑end flow (the whole algorithm)

Here is the complete sequence for one comparison run. Each numbered step maps to
real code.

```
 [1] User picks Reg A + Reg B (+ optional topics) on the picker page
       │  cjpca/apps/comparison/views.py :: PairPickerView
       │  (topic_scan.scan_topic_coverage shows which topics each reg covers)
       ▼
 [2] POST /comparison/run/  → RunComparisonView.post()
       │  • create a ComparisonRun row (status=RUNNING)  ← workspace URL exists now
       │  • write an audit event (COMPARISON_RUN)
       │  • build the retrieval query from the chosen topics
       ▼
 [3] compare_regulations(query, reg_a, reg_b, doc_titles, topic, ...)
       │  reasoning/workflows.py
       │  ── RETRIEVAL ──────────────────────────────────────────────
       │  • _scoped_retrieve() per side → hybrid_search()
       │      · taxonomy filter (topic/subcategory) pushed down to DB
       │      · doc_title filter → LLM physically cannot see other docs
       │      · dense (Chroma) + BM25 (sqlite) → RRF fuse → rerank
       │  • format_nodes() turns chunks into labelled context blocks:
       │      [Chunk 1] (node_id=abc) CITATION: Bahrain PDPL — Art. 22
       ▼
 [4] LangGraph workflow runs:  draft → verify → (correct)* → finalize
       │  reasoning/workflows.py :: comparison_graph
       │
       │   draft   — one LLM call, output parsed into ComparisonReport
       │   verify  — check EVERY citation against the real chunks;
       │             auto‑correct chunk_ids; run NLI hallucination scoring;
       │             drop pure‑invention rows
       │   correct — (only if issues AND retries<max) re‑prompt the LLM
       │   finalize— return the report
       ▼
 [5] Back in the view: map each obligation → a ComparisonResult DB row
       │  • _map_relationship() turns (equivalence, stricter) → relationship
       │  • confidence capped at 0.45 if citation could not be verified
       │  • full pydantic report also stashed as run.report_json
       │  • status=COMPLETE, audit event (COMPARISON_COMPLETE)
       ▼
 [6] redirect → /comparison/runs/<pk>/  → ComparisonWorkspaceView
       │  • rehydrate obligations from run.report_json
       │  • compute stats / strictness axes / chart data / BBK implications
       │  • render the 8‑tab workspace
       ▼
 [7] Analyst reviews → "Send to reviewer" → lifecycle Draft→Reviewed→Approved
       │  • SubmitForReviewView flips rows to REVIEWED, notifies reviewers
       │  • Approved runs can export: exec‑summary PDF + register XLSX
```

There are **three entry points** into the same reasoning call, kept during the UI
consolidation:

| Route | View | Purpose |
|---|---|---|
| `POST /comparison/run/` | `RunComparisonView` | Main combined picker → synchronous run |
| `POST /comparison/analyst/` | `AnalystComparisonView` | Legacy analyst page (single topic + subcategory), kept for side‑by‑side |
| `_run_comparison_background()` | thread helper | Older background‑thread flow (still present) |

All three ultimately call the same `compare_regulations()` and persist the same
`ComparisonResult` rows. The current default flow is **synchronous** (runs in the
request thread) — this was a deliberate fix: the older subprocess/poll flow left
runs stuck in *running* after a server restart and silently showed 0 results.

---

## 3. Retrieval — how the clauses are found

Retrieval is **hybrid search** (`retrieval/retriever.py`). For each side of the
comparison, `_scoped_retrieve()` → `hybrid_search()` does:

1. **Query expansion** — the query is expanded with cross‑jurisdiction synonyms
   from the Term Dictionary (`reasoning/term_dictionary.py`), so "permission" also
   matches Bahrain's "consent" and India's "data principal".
2. **Dense vector search** — the query is embedded with `BAAI/bge-small-en-v1.5`
   (with the BGE query prefix) and searched against ChromaDB.
3. **Keyword search** — the same query hits a custom **SQLite FTS5 BM25** store.
   (Custom, not LlamaIndex's built‑in, because it persists and supports
   metadata‑filter push‑down; the eval showed hit_rate@5 dropped 0.95→0.875 with
   the in‑memory version.)
4. **Fusion** — the two ranked lists are merged with **Reciprocal Rank Fusion**
   (`QueryFusionRetriever`, k=60).
5. **Rerank** — a cross‑encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) reranks
   the candidates against the *original* query for precision.
6. **Parent expansion** — each chunk optionally gets its parent chunk attached for
   wider context.

### Two filters make comparison accurate, not just relevant

- **Document scoping** (`doc_titles`, `scope_mode`): in `strict` mode (the
  default) the DB `WHERE` clause restricts retrieval to the *selected* documents.
  The LLM **physically cannot see** chunks from any other document. `open` mode
  also pulls related chunks from the rest of that jurisdiction's corpus as
  supporting context.
  - ⚠️ Note: retrieval filters on `chunk_doc_title` (the **file stem** ingestion
    stored), *not* the display name. Passing the display name was the original
    "0 obligations, silent empty run" bug — see the comment at
    `views.py` in `_run_comparison_background`.
- **Taxonomy scoping** (`topic`, `subcategory`): filters chunks to a single
  compliance topic *before* semantic ranking. This is what stops the LLM from
  comparing "a Bahrain rectification clause against an India access clause just
  because they share vocabulary". Only chunks the classifier has tagged with that
  topic are eligible.

### Single‑topic vs multi‑topic retrieval (a real gotcha)

The query type changes the retrieval path:

- **`query` is a `str`** (single topic) → `_scoped_retrieve` per side, honours the
  `topic` filter and `top_k`.
- **`query` is a `list[str]`** (full comparison / multiple topics) →
  `_multi_query_retrieve`, one retrieval per concept, results merged with topic
  diversity preserved. Each query carries its **own** per‑query taxonomy filter
  (`topics_per_query`) so topics don't bleed into each other.

The view converts a **single** selected topic into a string (so the filter fires)
and keeps **multiple** topics as a list.

### The 12‑topic taxonomy

Defined in `reasoning/taxonomy.py`. Every chunk is tagged with exactly one
`(topic, subcategory)` pair. The topics:

`lawful_basis` · `data_subject_rights` · `notice_and_transparency` ·
`cross_border` · `sensitive_data` · `security` · `breach_management` ·
`retention` · `governance` · `third_party` · `sector_specific` (banking) ·
`enforcement`. (`unclassified` is reserved for preambles/definitions/schedules.)

Tags live in a `chunk_tags` side‑table (BM25 store) and are mirrored onto Chroma
metadata. `topic_scan.scan_topic_coverage()` reads this table to show, on the
picker, how many articles each regulation has per topic — and to detect
**"only in A / only in B"** topics (asymmetric coverage).

---

## 4. Turning chunks into a prompt — `format_nodes()`

`reasoning/workflow_helpers.py :: format_nodes()` renders each retrieved chunk
into a labelled block (capped at `max_chars=6000` per side — bumped from 2000
because the small cap truncated clauses and produced sparse comparisons):

```
=== REGULATION A — BAHRAIN ===
[Chunk 1] (node_id=abc123) CITATION: Bahrain PDPL — Article 22
<the clause text, de‑duplicated>

[Chunk 2] (node_id=def456) CITATION: Bahrain PDPL — Article 23
<the clause text>
```

The header gives the LLM **three things to copy** when it cites:
- the **chunk number** → goes in `source_chunk_a/b`
- the **node_id** → goes in `reg_a/b_chunk_id` (enables UI click‑through)
- the **citation text** → goes in `reg_a/b_citation`

The verifier later checks each of these against reality. `_dedup_content()` strips
repeated sentence fragments that multi‑column PDF extraction produces (they
confuse the LLM).

---

## 5. The LangGraph workflow — draft → verify → correct → finalize

Built in `reasoning/workflows.py :: _build_comparison_graph()`. It's a state
machine over `ComparisonState`:

```
        ┌─────────┐
 START→ │  draft  │  LLM call → parse into ComparisonReport
        └────┬────┘
             ▼
        ┌─────────┐
        │ verify  │  structural citation checks + NLI scoring + drop junk
        └────┬────┘
             │  _comparison_route():
             │    cite_issues AND retries<max_retries?
       ┌─────┴──────┐
   yes │            │ no
       ▼            ▼
  ┌─────────┐  ┌──────────┐
  │ correct │  │ finalize │→ END
  └────┬────┘  └──────────┘
       │ (re‑prompt with correction_hint + previous draft)
       └──► verify   (loop)
```

**Important:** `cfg.validation.max_retries = 0` in `reasoning/config.py`. So in the
default configuration the loop **does not re‑prompt** — it drafts once, verifies,
records the verify + hallucination scores on every row (so the UI can flag
unreliable ones), and finalizes. This was a deliberate performance decision: with
`timeout_sec=75`, the old `max_retries=2` could burn **7.5 minutes per topic** on
worst‑case re‑prompting, and re‑prompting the same chunks rarely produced a better
answer. Partial verification is still useful to an analyst, so the workflow ships
what it has rather than falling back to an empty report.

The graph has **no checkpointer** — the raw `NodeWithScore` objects kept in state
(needed by the evidence verifier) aren't msgpack‑serializable, and each run is
one‑shot anyway.

### The draft step

`_comparison_draft()` loads `comparison_workflow.yaml`, formats it with the query
+ both context blocks (+ correction hint/previous answer if looping), then calls
`_draft_with_parser()`:
- one real LLM call (`llm.ainvoke`)
- parse the text straight into `ComparisonReport` with `PydanticOutputParser`
- **only on a parse failure** delegate to `OutputFixingParser` for one re‑prompt
  (gated by `cfg.llm.retry_attempts`). This avoids the old "1 draft = up to 2–4
  LLM hits" multiplier that made the mapping screen take 5+ minutes.

---

## 6. The prompt (`comparison_workflow.yaml`)

This is the instruction set the LLM follows. The important rules:

**Citation rules (called "CRITICAL — violations invalidate the analysis"):**
1. Each chunk has a `[Chunk N] (node_id=...) CITATION: <text>` header.
2. Copy the citation text **character‑for‑character** into `reg_a/b_citation`.
3. Copy the `node_id` verbatim into `reg_a/b_chunk_id`.
4. Pull a **30–200 char verbatim substring** into `reg_a/b_evidence` (no
   paraphrase, no ellipsis).
5. Record the chunk number in `source_chunk_a/b`.
6. If no chunk supports an obligation, **omit it entirely**.

**One‑chunk‑per‑obligation rule:** each requirement must be drawn from one chunk;
never merge two chunks into one requirement.

**Obligation‑count rule:** one obligation per *distinct topic actually present* in
the chunks (range 1–10, no padding). Soft cap: any single `source_chunk` may
appear in at most 2 obligations, to stop over‑slicing.

**Classification labels:** `Equivalent` · `Partially Equivalent` · `Different` ·
`Conflicting` (use very rarely) · `Only in A` / `Only in B`.

**Strictness — three orthogonal axes** (this replaced a single "stricter" verdict
that pushed the model into absolute judgements). Each axis returns `A` / `B` /
`Equivalent` / `Not Assessable`:
- `procedural_stricter` — deadlines, proof‑of‑identity, notification, recordkeeping
- `substantive_stricter` — breadth of the right, conditions, exceptions, triggers
- `enforcement_stricter` — penalties, regulator powers, audits, criminal liability

`stricter_jurisdiction` is a **roll‑up** = majority vote across the three axes
(ties / all‑not‑assessable → "Neither").

**Tone rules:** comparative/descriptive language only. Forbidden phrases include
"significantly stricter", "aligns with GDPR", "more privacy‑friendly",
"fundamentally different", "best practice". The model must describe the *mechanism*
("Bahrain requires X within 10 days; India does not specify a timeline") and let
the reader judge magnitude.

The prompt ends by demanding **JSON only** matching the `ComparisonReport` shape.

---

## 7. Verification — the "don't trust the LLM" layer

This is the heart of the system, in
`reasoning/workflow_helpers.py :: verify_comparison_citations()`. After the draft,
**every obligation row** is checked. Two independent kinds of check:

### 7a. Structural citation checks (is the citation real?)

For each row:
- **Auto‑fill from `source_chunk`** — if the LLM gave a chunk number, back‑fill
  `reg_a/b_citation`, `reg_a/b_chunk_id`, and `reg_a/b_doc_title` from the real
  chunk metadata (covers the LLM forgetting a field).
- **Citation label check** — `reg_a/b_citation` must appear among the actual
  `[Chunk N] CITATION:` headers (lenient — legal phrasings drift).
- **Evidence check (verbatim)** — `reg_a/b_evidence` must be a whitespace‑normalised
  **substring of the cited chunk**. If it isn't in the cited chunk, the verifier
  tries **every other chunk on that side** and, on a hit, **auto‑corrects the
  chunk_id** to the real source (the LLM sometimes mis‑attributes a quote).
- **`citation_verified`** is set `True` only when the row's checks pass. Verbatim
  evidence is treated as the strongest signal: if a side has evidence, that side
  is accepted on evidence alone even if the label drifted; if a side has no
  evidence (e.g. "Only in A" leaves B empty), it falls back to the label check.

### 7b. Semantic check — NLI hallucination scoring (does the claim follow?)

`score_text_against_chunk()` runs an **NLI cross‑encoder**
(`cross-encoder/nli-deberta-v3-base`, ~700 MB, lazy‑loaded once, thread‑safe
double‑checked lock) between the AI's prose (`reg_a/b_requirement`) and the cited
chunk. It returns a **hallucination risk in [0,1]** (0 = fully entailed, 1 =
unsupported/contradicted). The row's `hallucination_risk` is set to the **worse of
the two sides** — if A is badly paraphrased, the row is suspect even if B is fine.
This catches subtle paraphrase drift that the substring check can't see.

### 7c. Dropping pure invention

`_is_fully_hallucinated_comparison()` drops a row entirely when it's "pure noise":
both sides missing a citation, **or** one side missing + `hallucination_risk >
0.90`. Dropped rows are **logged to the issues list** (which flows to the audit
trail) so there's a record of what the AI tried to invent — the user just never
sees fabricated obligations presented as "review me" candidates.

The same two‑guardrail pattern (`verify_simple_citations` /
`verify_policy_mapping_citations`) powers Policy Mapping and Gap Analysis — the
verifier module is shared.

---

## 8. The data shape — `ObligationComparison`

Each row the workflow produces is an `ObligationComparison`
(`reasoning/schemas.py`). Fields, grouped:

| Group | Fields |
|---|---|
| **Topic** | `topic` |
| **Source pointers** | `source_chunk_a/b` (int), `reg_a/b_chunk_id` (node_id), `reg_a/b_doc_title` |
| **Citations** | `reg_a/b_citation` (label), `reg_a/b_evidence` (verbatim quote) |
| **Analysis prose** | `reg_a/b_requirement` (2–4 sentences), `key_difference`, `notes` |
| **Classification** | `equivalence`, `similarity_score` (0–100), `confidence_score` (0–100) |
| **Strictness** | `procedural_stricter`, `substantive_stricter`, `enforcement_stricter`, `stricter_jurisdiction` (roll‑up) |
| **Verification (set by verifier)** | `citation_verified` (bool), `hallucination_risk` (0–1) |

A `ComparisonReport` is `{ obligations: [...], summary, query, regulation_a,
regulation_b, disclaimer }`. The `disclaimer` is fixed: *"AI‑assisted analytical
output. Not legal advice…"*.

All fields default to safe values so a partially‑correct LLM output still parses.

---

## 9. Persistence & the relationship mapping

Back in the view, each obligation becomes a `ComparisonResult` row
(`cjpca/apps/comparison/models.py`). Two transforms happen here:

**`_map_relationship(equivalence, stricter, similarity, confidence)`** collapses
the LLM's `equivalence` + `stricter_jurisdiction` into one of six UI relationships,
with a confidence and similarity:

| LLM `equivalence` | + stricter | → `relationship` |
|---|---|---|
| Equivalent | — | `equivalent` |
| Partially Equivalent | A / B | `stricter_in_a` / `stricter_in_b` |
| Different | A / B | `stricter_in_a` / `stricter_in_b` |
| Different | neither | `conflicting` |
| Conflicting | — | `conflicting` |
| Only in A / B | — | `additional_in_a` / `additional_in_b` |

**Confidence penalty:** if `citation_verified` is `False`, confidence is capped at
**0.45** — an unverifiable row can never look confident.

Two model layers store the run:

- **`ComparisonRun`** — one per run. Holds `reg_a`, `reg_b`, `topics`, `status`
  (pending/running/complete/failed/partially_failed), progress counts,
  `error_message`, and **`report_json`** (the full pydantic dump — the preferred
  hydration source for the workspace, because it keeps fields like the three
  strictness axes that have no dedicated column). Also carries the analyst→reviewer
  handoff fields (`analyst_note`, `submitted_for_review_at`, `submitted_by`).
- **`ComparisonResult`** — one per obligation row. Carries citations, previews,
  full clause text, `relationship`, `confidence`, `similarity_score`,
  `key_difference`, `rationale`, **`evidence_a/b`**, **`chunk_id_a/b`**,
  `citation_verified`, `hallucination_risk`, `principle_ids`, and a **lifecycle**
  (`draft → reviewed → approved / rejected`).
- **`AuditEvent`** — per‑result audit trail (actor, action, from/to lifecycle,
  diff, timestamp). Run‑level events also go to the global history/audit log.

Each `ComparisonResult` exposes UI helpers: `rel_color`, `rel_label`, `rel_bg`,
`confidence_pct`, `similarity_pct`, `is_orphan`. The relationship colours:
equivalent = green, stricter‑in‑A = navy, stricter‑in‑B = amber, additional =
muted, **conflicting = red** (flag for legal review).

---

## 10. What the output actually shows (the workspace)

`ComparisonWorkspaceView` renders `/comparison/runs/<pk>/` — an 8‑tab view
hydrated from `report_json` (+ lazy‑loaded tabs that query the run pk via HTMX).
The tabs and API endpoints (`cjpca/apps/comparison/api.py`, wired in `urls.py`):

| Tab | Endpoint | What it shows |
|---|---|---|
| **Obligations** | inline | The core table — one row per obligation: both citations, verbatim evidence, requirement prose, relationship badge, similarity, confidence, hallucination risk, `citation_verified` flag |
| **Overview** | `runs/<pk>/overview/` | Summary banner + counts |
| **Charts** | `runs/<pk>/clauses/` | Distribution histograms (below) |
| **Graph** | `runs/<pk>/graph/` | Node/edge graph of the comparison |
| **Arc Diagram** | `runs/<pk>/arcs/` | Arc visualisation linking A↔B clauses |
| **Topic Map** | `runs/<pk>/topic-map/` | Obligations grouped by the taxonomy topic of the chunks each cited |
| **Insights** | `runs/<pk>/insights/` | LLM summary + top divergences + BBK implications (below) |
| **BBK Implications** | inline | Deterministic compliance‑impact prose (below) |

### Aggregate stats (computed in `_build_analyst_aggregates`)

- `count`, `verified` (how many rows passed citation verification), `avg_hall`
  (average hallucination risk), `equiv` count, `conflicts` count
- **Per‑axis tallies** for procedural / substantive / enforcement strictness
  ({A, B, equivalent, not‑assessable})
- **Chart data**: confidence histogram (10 buckets), hallucination‑risk histogram
  (5 buckets), similarity histogram (10 buckets), strictness bar chart (3 axes),
  equivalence pie

### BBK compliance impact (`_build_compliance_impact`)

A **deterministic** (no extra LLM call) one‑paragraph narrative that buckets the
obligations into `conflicts`, `unilateral_a/b`, `procedural_actions`,
`substantive_gaps`, `enforcement_risks`, `aligned`, then writes actionable prose:
*"BBK should escalate to legal review N conflict(s)…"*, *"…adopt the stricter
requirement on N obligation(s)…"*, etc. It also builds a ranked **top_actions**
list (high = conflicts → escalate to legal; medium = adopt stricter procedure;
low = heightened enforcement risk). It handles the same‑jurisdiction case ("both
Kuwait regulations" instead of "Kuwait and Kuwait").

### Insights tab (`insights.py`) — this one *does* call the LLM again

- **AI summary** — a fresh 3‑sentence executive summary (≤70 words, plain English)
- **Top 3 divergences** — ranked by an importance score:
  `0.40·relationship_weight + 0.30·confidence + 0.20·(1−similarity) + 0.10·principle_criticality`
  (conflicting weighted 1.0, stricter 0.7, additional 0.5, equivalent 0.0)
- **BBK implications** — 2 sentences grounded in the top divergences
- **Confidence histogram** — 7 bins, no LLM

Both LLM cards have deterministic fallbacks if the model call fails.

### Exports (approved packages)

- `runs/<pk>/exports/exec-summary.pdf` — executive‑summary PDF
- `runs/<pk>/exports/comparison-register.xlsx` — full comparison register

---

## 11. The LLM behind it all

Built in `reasoning/generator.py`, configured in `reasoning/config.py`:

- **Primary (PoC default): local Ollama** — `qwen2.5:7b-instruct`, `format="json"`,
  `num_ctx=8192`, kept resident in GPU VRAM for 30 min between calls (`keep_alive`).
  qwen2.5:7b was chosen because `llama3.2:1b` was too weak — it echoed the schema's
  field descriptions instead of extracting.
- **Optional cloud fallback:** if `OPENROUTER_API_KEY` is set, OpenRouter
  (`anthropic/claude-haiku-4-5` by default) is added as a `.with_fallbacks()`
  provider. With no key — the default — the app is fully local, no internet.
- **Determinism:** `temperature=0.1` (hard‑capped at 0.3 for reasoning),
  `timeout_sec=75`, `retry_attempts=1`.
- The client is **rebuilt on every call** (deliberately not cached): a cached
  ChatOllama binds its async httpx client to the first event loop it runs in, and
  since each top‑level call runs under its own `asyncio.run(...)`, a singleton
  crashed the second flow with "Event loop is closed". Construction is
  network‑free and microsecond‑cheap.

---

## 12. Key design decisions & gotchas (why it's built this way)

- **Verify‑after‑generate, not trust‑the‑LLM.** Every citation is checked against
  source text; unverifiable rows are capped in confidence; pure invention is
  dropped and logged. This is the compliance‑grade guardrail.
- **Two independent guardrails per row:** verbatim substring ("is the quote real?")
  + NLI entailment ("does the claim follow?"). They catch different failure modes.
- **Taxonomy filtering before semantic search** prevents cross‑topic false matches
  — the classic RAG failure where two clauses match on vocabulary but not meaning.
- **Strict document scoping** at the DB layer means the LLM cannot cite a document
  the user didn't select.
- **`max_retries=0` + one‑call draft** is a speed decision — bounded wall time,
  scores recorded for UI flagging instead of expensive re‑prompting.
- **Synchronous run in the request thread** (current default) so a crash fails
  loudly instead of leaving a run stuck in "running".
- **Filter on `chunk_doc_title` (file stem), not display name** — the classic
  "0 obligations, silent empty run" bug.
- **`report_json` is the source of truth for rendering** — it preserves fields
  (the three strictness axes, raw equivalence) that don't have `ComparisonResult`
  columns; the rows exist mainly for querying, lifecycle, and the lazy tabs.

---

## 13. File map (jump‑to reference)

| Concern | File |
|---|---|
| Picker, POST handler, workspace, aggregates, exports | `cjpca/apps/comparison/views.py` |
| DB models (`ComparisonRun`, `ComparisonResult`, `AuditEvent`) + colours/labels | `cjpca/apps/comparison/models.py` |
| Tab‑rendering API endpoints | `cjpca/apps/comparison/api.py` |
| URL routes | `cjpca/apps/comparison/urls.py` |
| Per‑reg topic coverage / only‑in‑A‑or‑B scan | `cjpca/apps/comparison/topic_scan.py` |
| Insights tab (LLM summary, divergences, histogram) | `cjpca/apps/comparison/insights.py` |
| Strictness score | `cjpca/apps/comparison/strictness.py` |
| Public entry + LangGraph workflow | `reasoning/workflows.py` |
| Chunk formatting + citation verification + NLI | `reasoning/workflow_helpers.py` |
| The prompt | `reasoning/prompts/comparison_workflow.yaml` |
| Pydantic schemas | `reasoning/schemas.py` |
| LLM client builder | `reasoning/generator.py` |
| Reasoning config (models, retries, thresholds) | `reasoning/config.py` |
| Compliance taxonomy | `reasoning/taxonomy.py` |
| Hybrid retrieval (dense + BM25 + fuse + rerank) | `retrieval/retriever.py` |
| BM25 store + chunk_tags side‑table | `retrieval/bm25_store.py` |

---

# APPENDIX A — Function‑by‑function reference

Every function and class in the comparison path, in call order, with what it takes,
what it does, what it returns, and the non‑obvious reasons behind it. Grouped by
file.

## A1. `reasoning/workflows.py` — the workflow engine

### State type
- **`class ComparisonState(TypedDict, total=False)`** — the object that flows
  through the LangGraph. Keys: `query` (str or list), `reg_a`, `reg_b`,
  `context_a`, `context_b` (the formatted prompt blocks), `nodes_a`, `nodes_b`
  (the **raw** `NodeWithScore` lists, kept so the verifier can check evidence),
  `draft` (current `ComparisonReport`), `cite_issues` (str of problems found),
  `retries` (int), `final_output` (the finished report). `total=False` means every
  key is optional.

### Draft helper
- **`_draft_with_parser(prompt_text, response_model)`** *(async)* — the shared
  "call the LLM once and parse" routine used by all three workflows. Builds a
  `PydanticOutputParser`, gets the LLM via `_get_llm()`, calls `llm.ainvoke`,
  extracts `.content`, and parses straight into the pydantic model. **Only** if the
  parse throws does it fall back to `OutputFixingParser` for one corrective
  re‑prompt (gated by `cfg.llm.retry_attempts`). The whole point is to avoid the
  old "1 draft = 2–4 LLM hits" multiplier. Returns a validated pydantic object.

### Comparison graph nodes
- **`_comparison_draft(state)`** *(async)* — loads `comparison_workflow.yaml`,
  `.format()`s it with `query`, `context_a`, `context_b`, `correction_hint`
  (from `state["cite_issues"]`), and `previous_answer` (last draft as JSON, only
  present when looping). Calls `_draft_with_parser(..., ComparisonReport)`. Returns
  `{"draft": <report>, "retries": <n>}`.
- **`_comparison_verify(state)`** *(async)* — dumps each obligation to a dict, calls
  `verify_comparison_citations(...)` with both contexts and both raw node lists,
  re‑validates the returned dicts back into `ObligationComparison` objects, and
  returns `{"draft": ..., "cite_issues": "; ".join(issues) or None}`.
- **`_comparison_correct(state)`** *(async)* — if `retries >= max_retries`, stop:
  return `{"final_output": state["draft"]}` (ship what we have). Otherwise
  increment `retries` and re‑run `_comparison_draft` (which now sees the correction
  hint).
- **`_comparison_route(state)`** — the conditional edge. Returns `"correct"` when
  there are `cite_issues` **and** `retries < max_retries`, else `"finalize"`.
- **`_comparison_finalize(state)`** *(async)* — returns
  `{"final_output": state["draft"]}`.
- **`_build_comparison_graph()`** — wires the nodes: entry=`draft`,
  `draft→verify`, conditional `verify→{correct|finalize}`, `correct→verify`,
  `finalize→END`. Compiles with **no checkpointer** (raw nodes in state aren't
  serializable, and runs are one‑shot). Module‑level `comparison_graph` holds the
  compiled graph. *(The mapping and gap graphs are identical in shape — see A1b.)*

### Retrieval helpers
- **`_run_async(coro)`** — sync→async bridge. Probes `asyncio.get_running_loop()`:
  if it raises `RuntimeError` (normal sync caller) it uses `asyncio.run(coro)`; if a
  loop **is** running (called from async / ASGI), it runs the coro on a worker
  thread with its own loop, because nesting `asyncio.run` in a live loop raises.
- **`_scoped_retrieve(query, top_k, jurisdiction, doc_titles, scope_mode, rerank, topic, subcategory)`**
  — document‑scoped retrieval. If no `doc_titles`, delegates to a plain
  jurisdiction‑scoped `hybrid_search`. Otherwise runs a **primary** search
  restricted to `doc_titles`; in `strict` mode returns just that; in `open` mode
  also runs a **secondary** broader search over the jurisdiction, dedupes by
  `node_id`, and appends the extras (selected docs first). Taxonomy `topic`/
  `subcategory` push down to both backends regardless of mode.
- **`_multi_query_retrieve(queries, reg_a, reg_b, top_k_per_query, doc_title_a, doc_title_b, topics_per_query, subcategories_per_query, rerank)`**
  — the multi‑topic path. For each query it retrieves a small slice from **both**
  sides via `_scoped_retrieve` (strict mode), applying that query's own taxonomy
  topic (so topics don't bleed). Merges per side into a dict keyed by node_id
  (dedup via `setdefault`). Returns `{"regulation_a": [...], "regulation_b": [...]}`.
- **`_multi_query_mapping_retrieve(...)`** — the mapping‑side twin (regulation vs
  BBK policy split). Same structure; used by `map_policy_coverage`.

### Public entry point
- **`compare_regulations(query, reg_a, reg_b, top_k=8, rerank=False, doc_title_a, doc_title_b, doc_titles_a, doc_titles_b, scope_mode="strict", topic, subcategory, topics, subcategories)`**
  — **the function the Django views call.** Steps:
  1. Back‑compat: lift a single `doc_title_a/b` into a list.
  2. Branch on query type: **list** → `_multi_query_retrieve` (per‑concept,
     `top_k_per_query = max(top_k // len(query), 3)`), prompt query becomes the
     generic `"privacy regulation full comparison"`. **str** → `_scoped_retrieve`
     per side (honours strict/open + taxonomy), prompt query = the query itself.
  3. `format_nodes(...)` each side into `context_a` / `context_b` (`max_chars=6000`).
  4. Build the initial `state` (contexts **and** raw nodes for the verifier).
  5. `_run_async(comparison_graph.ainvoke(state))`.
  6. Stamp `query`, `regulation_a`, `regulation_b` onto the returned report (the
     LLM doesn't produce these — they're caller context) and return it.

### Sibling workflows (same skeleton, different schema/prompt/verifier)
- **A1b — `map_policy_coverage(...)`**, **`map_policy_coverage_auto(...)`**,
  **`generate_gap_analysis(...)`** and their graph nodes (`_mapping_*`, `_gap_*`)
  mirror the comparison graph exactly. `map_policy_coverage_auto` is notable: it
  reads the topics already classified onto a policy's chunks
  (`topics_for_docs`), classifies on demand if needed
  (`_classify_policy_chunks_on_demand`), drops topics the target regulation has
  zero chunks for, then runs one topic‑scoped mapping pass per remaining topic and
  concatenates the results — so a retention policy is never force‑mapped against
  breach‑notification clauses. Not part of the *comparison* path but shares all the
  same infrastructure.

### Debug printers
- **`print_comparison_report(r)`**, `print_policy_mapping_report`,
  `print_gap_analysis_report` — plain‑text CLI dumps, kept for parity with the old
  `analyzer.py`. Not used by the web UI.

## A2. `reasoning/workflow_helpers.py` — formatting + verification

- **`_dedup_content(text)`** — splits text into sentences, drops duplicates keyed by
  the first 60 lowercased chars, rejoins. Removes the verbatim repeats that
  multi‑column PDF extraction produces.
- **`format_nodes(nodes, label, max_chars=3000)`** — renders a node list into a
  labelled context block with `[Chunk N] (node_id=...) CITATION: <reg> — <ref>`
  headers. Truncates on a word boundary once `max_chars` is hit. This is the
  contract the LLM cites against and the verifier parses back.
- **`_normalise_quote(s)`** — lowercase + whitespace‑collapse, for fuzzy substring
  matching.
- **`_evidence_in_chunk(evidence, chunk_text)`** — True if `evidence` (≥10 chars) is
  a normalised substring of `chunk_text`. The verbatim test.
- **`_extract_chunk_citations(context)`** — regex‑parses `[Chunk N] (node_id=...)
  CITATION: <text>` headers back into `{chunk_number: citation}`. The optional
  `(node_id=...)` segment is explicitly matched — without it every citation check
  returned "not found" and marked every row unverified.
- **`_index_nodes(nodes)`** — `{node_id: content}` map for evidence lookup.
- **`_index_doc_titles(nodes)`** — `{node_id: doc_title}` for UI navigation
  back‑fill.
- **`_index_nodes_by_position(nodes)`** — `{chunk_number: node_id}`, mirroring
  `format_nodes` ordering, so a `source_chunk` integer resolves to a node_id.
- **`_get_nli_model()`** — thread‑safe lazy load of the deberta‑v3 NLI cross‑encoder
  (~700 MB) with double‑checked locking. Reads the model name from
  `cfg.validation.hallucination_model`.
- **`score_text_against_chunk(text, chunk_text)`** — runs NLI between prose and a
  chunk, softmaxes the [contradiction, neutral, entailment] logits, returns
  `1 − entailment_prob` in [0,1]. Returns 1.0 (max risk) for empty/short input.
- **`_is_fully_hallucinated_comparison(ob)`** — True when a row has no citation on
  both sides, or one side missing + `hallucination_risk > 0.90`. Used to drop junk.
- **`verify_comparison_citations(obligations_data, context_a, context_b, nodes_a, nodes_b, score_hallucination=True, drop_hallucinated=True)`**
  — **the comparison verifier.** For each row: auto‑correct citation labels and
  chunk_ids from `source_chunk`; auto‑fill doc_titles; run the label check and the
  verbatim‑evidence check (with the `_verbatim_or_recover` inner helper that scans
  all chunks and auto‑corrects a mis‑attributed chunk_id); set `citation_verified`;
  run NLI on both requirement fields and record the worse score as
  `hallucination_risk`; collect human‑readable issues. Finally drops
  fully‑hallucinated rows (logging each drop). Returns `(kept_obligations, issues)`.
- **`verify_policy_mapping_citations(...)`** — the mapping twin. Asymmetric:
  regulation side is required (drives `citation_verified` via
  `verify_simple_citations`), policy side is checked when claimed but allowed to be
  empty (legitimate "Not Covered").
- **`verify_simple_citations(rows, context, citation_field, label_field, nodes, chunk_id_field, evidence_field, doc_title_field, summary_field, ...)`**
  — the **generic** single‑sided verifier used by policy mapping (regulation side)
  and gap analysis. Same structural + NLI logic parameterised by field names. For
  gap analysis it scores the summary against **all** retrieved chunks and takes the
  **best** (lowest‑risk) — an obligation only needs to be entailed by one chunk.

## A3. `reasoning/generator.py` — the LLM client

- **`_build_openrouter_llm()`** — builds a `ChatOpenAI` pointed at OpenRouter's
  base URL, model from `cfg.llm.model`, `response_format={"type":"json_object"}`,
  attribution headers. Raises if `OPENROUTER_API_KEY` is unset.
- **`_build_ollama_fallback()`** — builds `ChatOllama` for the local model
  (`format="json"`, `num_ctx`, `keep_alive="30m"`, timeouts). Despite the name it's
  the **primary** in the PoC.
- **`_build_llm()`** — makes local Ollama the primary; if `OPENROUTER_API_KEY` is
  set, attaches OpenRouter as a `.with_fallbacks()` provider; otherwise returns
  Ollama alone.
- **`_get_llm()`** — returns `_build_llm()` **fresh every call** (not cached) to
  avoid the "Event loop is closed" bug from a cached async client bound to a dead
  loop.
- **`_format_chunks(chunks, max_chars=6000)`** — an alternate chunk formatter used
  by the orchestrator's `generate_structured` (headers carry node_id + doc + article
  + jurisdiction). The comparison workflow uses `format_nodes` instead.
- **`generate_structured(query, chunks, route, prompt_key, response_model, correction_context, previous_draft)`**
  *(async)* — the orchestrator's generic "prompt → parsed pydantic" call (used by
  the copilot/orchestrator path, not the comparison workflow, which has its own
  `_draft_with_parser`).

## A4. `retrieval/retriever.py` — hybrid search

- **`class _SQLiteBM25Retriever(BaseRetriever)`** — adapts the custom SQLite FTS5
  store to LlamaIndex's retriever interface. `_retrieve(query_bundle)` calls
  `search_bm25(...)` and wraps rows as `NodeWithScore`.
- **`class RetrievalService`** — one instance per process. `__init__` sets a
  `MockLLM` on `Settings` (so fusion doesn't bind a real LLM), builds the BGE
  embedder with the query prefix, opens the **same** Chroma collection ingestion
  wrote (cosine space), and wraps it in a `VectorStoreIndex`. The reranker loads
  lazily.
  - **`_get_reranker()`** — lazy `SentenceTransformerRerank` (ms‑marco MiniLM).
  - **`_normalise_jurs(jurs)`** — maps `"bahrain"→"Bahrain"` etc. via
    `JURISDICTION_NORM` so caller and stored data agree.
  - **`_build_chroma_filters(...)`** — assembles LlamaIndex `MetadataFilters`
    (AND‑combined) for jurisdiction(s), doc_type, doc_title(s), topic, subcategory.
    Returns `None` if nothing to filter.
  - **`_bm25_filters(...)`** — the same filter set shaped as `search_bm25` kwargs.
  - **`search(query, top_k, jurisdiction, jurisdictions, doc_type, doc_title, doc_titles, topic, subcategory, rerank=True, expand_parent=True, expand_synonyms=True)`**
    — the full pipeline: optional synonym expansion → build filters → vector
    retriever + BM25 retriever → `QueryFusionRetriever` (RRF, `num_queries=1`) →
    rerank against the **original** query → slice `top_k` → attach parent bodies.
    Returns `list[NodeWithScore]`.
- **`_get_service()`** — thread‑safe double‑checked singleton for the service
  (avoids two concurrent first‑callers racing Chroma's Windows file lock and
  loading the embedder twice).
- **`hybrid_search(...)`** — module‑level functional wrapper around
  `_get_service().search(...)`. **This is what the reasoning layer calls.**
- **`search_comparative(query, reg_a, reg_b, ...)`** — convenience that retrieves
  both sides in one call. (The comparison workflow uses `_scoped_retrieve` per side
  instead, for scope/taxonomy control.)
- **`_get_st_model()` / `_embed_query(query)`** — back‑compat helpers used by the
  retrieval eval scripts.

## A5. `cjpca/apps/comparison/views.py` — the web layer

- **`_get_reg(jurisdiction, preferred_pk)`** — resolves a jurisdiction to its
  canonical indexed regulation `Document` (prefers an explicit pk, then the
  `CANONICAL_REGS` PDPL, then first). Stops the picker grabbing a non‑PDPL doc.
- **`_all_regs(jurisdiction)`** — all indexed regulations for a jurisdiction (for
  selection lists).
- **`_map_relationship(equivalence, stricter, llm_similarity=-1, llm_confidence=-1)`**
  — collapses the LLM's `equivalence` + `stricter_jurisdiction` into
  `(relationship, confidence, similarity_score)`; uses the LLM's own similarity/
  confidence when provided, else hard‑coded per‑branch defaults. (See the table in
  §9.)
- **`_detect_principles(text)`** — cheap taxonomy probe: returns taxonomy tags whose
  label tokens appear in the obligation text. Seeds `ComparisonResult.principle_ids`
  for legacy filters/exports (the Topic Map tab is the real source of truth).
- **`_ollama_is_reachable()`** — 3‑second health probe of the Ollama `/api/tags`
  endpoint.
- **`_launch_subprocess(command, *args)`** — spins up a `manage.py <command>`
  subprocess with `PYTHONPATH` fixed so `reasoning/` and `retrieval/` import; logs
  to `logs/`. Used by the older background flow.
- **`_run_comparison_background(run_pk, include_orphans, articles_a, articles_b)`**
  — the background‑thread runner: builds the query from `run.topics` (via
  `_CONCEPT_QUERIES`), calls `compare_regulations`, writes `ComparisonResult` rows,
  optionally adds orphan rows from `scan_topic_coverage`, sets status, audits.
  Superseded by the synchronous flow but still present.
- **`class PairPickerView(View)`** — `GET /comparison/`. Lists all indexed
  regulations, resolves the two picked regs from `?reg_a_pk`/`?reg_b_pk`, runs
  `scan_topic_coverage` to populate the topic chips + coverage bars, flags the
  same‑jurisdiction case, renders `comparison_custom_scope.html`.
- **`class RunComparisonView(View)`** — `POST /comparison/run/`. **The main run
  handler.** Validates the two regs, reads `scope_mode`/`topics`/`include_orphans`,
  creates the `ComparisonRun` (status=RUNNING) up front, audits, then builds the
  query (single‑topic→str so the taxonomy filter fires; multi‑topic→list), calls
  `compare_regulations(top_k=10, rerank=True, scope_mode="strict", ...)`, maps every
  obligation to a `ComparisonResult`, stashes `report_json`, sets status=COMPLETE,
  audits, and redirects to the workspace. On exception: status=FAILED with the
  message.
- **`class SubmitForReviewView(View)`** — `POST /comparison/runs/<pk>/submit-review/`.
  Captures the analyst note, stamps `submitted_for_review_at`/`submitted_by`,
  flips every `DRAFT` result to `REVIEWED` (so the reviewer queue picks them up),
  audits, clears the nav‑count cache. Idempotent.
- **`class ComparisonWorkspaceView(View)`** — `GET /comparison/runs/<pk>/`. Renders
  the 8‑tab workspace. `_build_context(run)` hydrates obligations (preferring
  `report_json`, falling back to `ComparisonResult` rows as `SimpleNamespace`s),
  builds the `report`, and calls `_build_analyst_aggregates`.
- **`_rel_to_equivalence(relationship)`** — reverse map (relationship → raw
  equivalence label) for rendering legacy runs that predate `report_json`. Lossy.
- **`_build_analyst_aggregates(obligations, reg_a, reg_b)`** — computes `stats`
  (count, verified, avg hallucination, equiv/conflict counts, per‑axis tallies),
  `axes`, `chart_data` (confidence/risk/similarity histograms, strictness bars,
  equivalence pie), and the `bbk` block (buckets + top_actions + compliance_impact).
  Returns `(stats, axes, chart_data, bbk)`.
- **`_build_compliance_impact(buckets, jur_a, jur_b)`** — deterministic
  one‑paragraph BBK narrative from the bucket counts, with same‑jurisdiction
  phrasing handling.
- **`class AnalystComparisonView(View)`** — `GET/POST /comparison/analyst/`. The
  legacy analyst page: form with 8 quick‑pick topics, maps a legacy topic →
  taxonomy `(topic, subcategory)`, builds a lexical query from the label, runs
  `compare_regulations(top_k=5, rerank=True, scope_mode="strict", topic, subcategory)`
  **synchronously** (blocks 1–2 min), persists via `_persist_run`, renders the full
  evidence view. `_persist_run` and `_render` mirror the main flow. *(There is more
  of this class — export views `ComparisonExecSummaryView` / `ComparisonRegisterView`
  live lower in the same file and produce the approved‑package PDF/XLSX.)*

## A6. `cjpca/apps/comparison/models.py` — persistence

- **Constants** — `PAIR_CONFIGS` (the three canonical jurisdiction pairs with
  labels/flags), `REL_COLORS`/`REL_LABELS`/`REL_BG` (relationship → UI styling).
- **`ComparisonAnalysis` / `ClausePair`** — V1 models, kept for backward compat.
- **`ComparisonRun`** — the run record. Fields per §9. Properties: `progress_pct`,
  `pair_label`, `topics_display`.
- **`ComparisonResult`** — the obligation row. Relationship + lifecycle choice sets;
  the evidence/chunk_id/hallucination columns; properties `confidence_pct`,
  `similarity_pct`, `rel_color`, `rel_bg`, `rel_label`, `is_orphan`.
- **`AuditEvent`** — per‑result audit trail (actor, action, lifecycle transition,
  diff, timestamp).

## A7. `cjpca/apps/comparison/topic_scan.py`

- **`scan_topic_coverage(reg_a_pk, reg_b_pk)`** — reads the `chunk_tags` side‑table
  via `topics_for_docs` for each regulation, buckets every taxonomy topic into
  `both_covered` / `only_in_a` / `only_in_b` with article counts and bar widths,
  and estimates pair count + runtime. This drives the picker's topic chips **and**
  the orphan ("Additional in A/B") rows. Uses the exact same tag data the reasoning
  layer's topic filter uses, so the chips reflect what the run will actually see.

## A8. `cjpca/apps/comparison/insights.py` — the Insights tab

- **Weights** — `_REL_WEIGHT` (conflicting 1.0 … equivalent 0.0),
  `_PRINCIPLE_CRITICALITY` (breach 1.0 … controller 0.3), `_BINS` (7 confidence
  histogram bins with colours).
- **`get_top_divergences(results, n=3)`** — scores each non‑equivalent row by
  `0.40·rel_weight + 0.30·confidence + 0.20·(1−similarity) + 0.10·principle_criticality`
  and returns the top `n`.
- **`compute_confidence_histogram(results)`** — bins confidences into `_BINS`,
  returns per‑bin label/count/height/colour.
- **`generate_ai_summary(run)`** — LLM call (via `reasoning.llm_shims`) for a
  ≤70‑word, 3‑sentence executive summary grounded in the top pairs + strictness
  scores; deterministic `_fallback_summary` on any failure.
- **`generate_bbk_implications(run, top_divergences)`** — LLM call for a 2‑sentence
  "what BBK should consider" note; `_fallback_implications` on failure.
- **`_serialize_pairs`, `_fallback_summary`, `_fallback_implications`** — the
  deterministic text builders used both to feed the prompt and to stand in if the
  LLM is unavailable.

## A9. `reasoning/taxonomy.py` — the compliance taxonomy

- **`TAXONOMY`** — the 12 topics → `{label, subcategories}` tree. **`UNCLASSIFIED`**
  is the reserved "no leaf fits" tag. **`CLASSIFIER_GUIDANCE`** is the disambiguation
  ruleset fed to the classifier LLM.
- Helpers: **`all_topics()`**, **`all_subcategories(topic)`**, **`is_valid(topic,
  subcategory)`**, **`topic_label(topic)`**, **`subcategory_label(topic, sub)`**,
  **`render_for_prompt()`** (renders the tree as a numbered list for the classifier
  prompt).

## A10. `reasoning/schemas.py` — the data contracts

- **Orchestrator schemas** (copilot path): `Citation`, `ReasoningStep`,
  `ReasonedAnswer` (with a `validate_grounding` model‑validator that warns on
  high‑confidence‑no‑citations), `SearchRequest`, `StreamingChunk`.
- **Report schemas** (the comparison path consumes these): `ObligationComparison`
  (§8), `ComparisonReport`, plus the mapping/gap equivalents
  (`PolicyCoverageItem`/`PolicyMappingReport`, `GapItem`/`GapAnalysisReport`). All
  fields default to safe values so a partial LLM output still parses; `_DISCLAIMER`
  is the shared "not legal advice" string.

## A11. `reasoning/config.py` — the knobs

- **`LLMConfig`** — model (`anthropic/claude-haiku-4-5` primary in config, but the
  PoC runtime makes Ollama primary), `temperature=0.1` (capped ≤0.3),
  `max_tokens=8000`, `timeout_sec=75`, `retry_attempts=1`, and the Ollama fallback
  settings (`qwen2.5:7b-instruct`, `num_ctx=8192`).
- **`RoutingConfig`** — prompt template per query route (copilot side).
- **`ValidationConfig`** — `min_confidence=0.6`, **`max_retries=0`** (the key
  perf setting — see §5), `hallucination_model`, `jurisdiction_strict`.
- **`CacheConfig`** — off by default. **`ReasoningConfig`** — composes them; env
  prefix `REASON_`, nested delimiter `__`. `cfg` is the singleton everything reads.

---

# APPENDIX B — Worked trace (concrete values)

A single "Bahrain PDPL vs India DPDPA, topic = consent" run, showing the data at
each hop:

```
POST /comparison/run/  reg_a_pk=75 reg_b_pk=88 topics=[lawful_basis] scope=custom
  │
  ├─ ComparisonRun(pk=42, status=running, pair_key="bahrain_india") created
  │
  ├─ query = "Lawful basis & consent"           (single topic → str)
  │  topic_filter = "lawful_basis"
  │
  ├─ compare_regulations(query="Lawful basis & consent",
  │      reg_a="bahrain", reg_b="india",
  │      doc_title_a="bahrain_pdpl_2018", doc_title_b="india_dpdp_2023",
  │      top_k=10, rerank=True, scope_mode="strict", topic="lawful_basis")
  │    │
  │    ├─ _scoped_retrieve(side A): hybrid_search(
  │    │     "Lawful basis & consent", jurisdiction="bahrain",
  │    │     doc_titles=["bahrain_pdpl_2018"], topic="lawful_basis")
  │    │   → [NodeWithScore(node_id=bh_art22, "The data manager shall not
  │    │      process personal data without the consent of the data owner…"), …]
  │    ├─ _scoped_retrieve(side B): same for india/india_dpdp_2023
  │    │
  │    ├─ format_nodes(A) →
  │    │     === REGULATION A — BAHRAIN ===
  │    │     [Chunk 1] (node_id=bh_art22) CITATION: Bahrain PDPL — Article 22
  │    │     The data manager shall not process personal data without…
  │    │
  │    ├─ comparison_graph.ainvoke(state):
  │    │     draft   → LLM returns JSON: obligations:[{topic:"Consent",
  │    │               source_chunk_a:1, reg_a_citation:"Bahrain PDPL — Article 22",
  │    │               reg_a_chunk_id:"bh_art22",
  │    │               reg_a_evidence:"shall not process personal data without the consent",
  │    │               equivalence:"Partially Equivalent", similarity_score:78,
  │    │               procedural_stricter:"A", …}]
  │    │     verify  → "shall not process… consent" IS a substring of bh_art22 ✓
  │    │               citation_verified=True; NLI(reg_a_requirement vs bh_art22)=0.12
  │    │               hallucination_risk=0.12; no rows dropped
  │    │     route   → no cite_issues (or max_retries=0) → finalize
  │    │     finalize→ ComparisonReport(obligations=[…], summary="…")
  │    │
  │    └─ report.regulation_a/b + query stamped on
  │
  ├─ _map_relationship("Partially Equivalent","A",78,90) → ("stricter_in_a",0.82,0.78)
  │    citation_verified=True → confidence NOT capped
  │
  ├─ ComparisonResult(run=42, citation_a="Bahrain PDPL — Article 22",
  │      relationship="stricter_in_a", confidence=0.82, similarity_score=0.78,
  │      evidence_a="shall not process… consent", chunk_id_a="bh_art22",
  │      hallucination_risk=0.12, lifecycle="draft")  bulk-created
  │
  ├─ run.report_json = <full pydantic dump>; status=complete
  │
  └─ redirect → /comparison/runs/42/  → 8-tab workspace renders:
        Obligations tab: 1 row, "Stricter in A" (navy badge), 82% confidence,
        78% similarity, green "verified" check, low-risk (0.12) indicator,
        click chunk_id → opens bahrain_pdpl_2018 at Article 22.
```

