"""Generate Section 3.2.2 Design Diagrams (Stage 2) as a Word document.

Output: thesis_docs/3_2_2_design_diagrams.docx

Contents:
  1. Section 3.2.2 Design Diagrams heading
  2. 3.2.2.1 UML notation in use            (1 paragraph)
  3. 3.2.2.2 Actors and use cases           + Figure D2
  4. 3.2.2.3 Deployment topology            + Figure D3
  5. 3.2.2.4 End-to-end pipeline            + Figure A2.3
  6. 3.2.2.5 Where to find the rest         (forward pointer)
  7. PAGE BREAK
  8. Appendix 2.3 — Per-phase mechanics     (6 figures + captions)
  9. Appendix 2.5 — Lifecycle states        (3 figures + captions)

Word budget for the body (3.2.2.1 to 3.2.2.5): under 600 words.
Style follows the Stage 1 generator (navy headings, 2 cm margins).
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Cm, Pt, RGBColor


NAVY = RGBColor(0x00, 0x25, 0x83)
DARK_GRAY = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x6B, 0x72, 0x80)


def set_run_style(run, *, bold=False, italic=False, color=NAVY, size=11):
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)


def add_paragraph(doc, text, *, bold=False, italic=False, color=DARK_GRAY,
                  size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    run = p.add_run(text)
    set_run_style(run, bold=bold, italic=italic, color=color, size=size)
    return p


def add_heading(doc, text, *, level=1):
    """level=1 -> Heading 2 (e.g. 3.2), level=2 -> Heading 3 (e.g. 3.2.2),
    level=3 -> Heading 4 (e.g. 3.2.2.1)."""
    style_map = {1: 'Heading 2', 2: 'Heading 3', 3: 'Heading 4'}
    size_map = {1: 14, 2: 12, 3: 11}
    h = doc.add_paragraph(style=style_map[level])
    run = h.add_run(text)
    run.font.color.rgb = NAVY
    run.font.bold = True
    run.font.size = Pt(size_map[level])
    return h


def add_figure_caption(doc, label: str, caption: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(14)
    r1 = p.add_run(label + ' ')
    set_run_style(r1, bold=True, color=NAVY, size=10)
    r2 = p.add_run(caption)
    set_run_style(r2, italic=True, color=MUTED, size=10)


def add_image(doc, image_path: Path, width_cm: float = 16.0):
    if not image_path.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f'[MISSING IMAGE: {image_path.name}]')
        set_run_style(run, bold=True, italic=True, color=MUTED, size=10)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(image_path), width=Cm(width_cm))


def add_page_break(doc):
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / '3_2_2_design_diagrams.docx'

    # Versioned filename if the existing file is locked open in Word.
    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'3_2_2_design_diagrams_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    diagrams_dir = base / 'diagrams'
    fig_d2          = diagrams_dir / 'Figure_4_UseCase.png'
    fig_d3          = diagrams_dir / 'Figure_5_Deployment.png'
    fig_backbone    = diagrams_dir / 'Figure_6_AI_Pipeline_Backbone.png'
    fig_a2_3a       = diagrams_dir / 'Figure_A2_3a_AnalystMapping_Sequence.png'
    fig_a2_3b       = diagrams_dir / 'Figure_A2_3b_Copilot_Sequence.png'
    fig_a2_3c       = diagrams_dir / 'Figure_A2_3c_ReviewerCascade_Sequence.png'
    fig_a2_3d       = diagrams_dir / 'Figure_A2_3d_Ingestion_Activity.drawio.png'
    fig_a2_3e       = diagrams_dir / 'Figure_A2_3e_Retrieval_Flow.png'
    fig_a2_3f       = diagrams_dir / 'Figure_A2_3f_Reasoning_Loop.png'
    fig_a2_5a       = diagrams_dir / 'Figure_A2_5a_MappingAnalysis_State.png'
    fig_a2_5b       = diagrams_dir / 'Figure_A2_5b_ObligationMapping_State.png'
    fig_a2_5c       = diagrams_dir / 'Figure_A2_5c_ComparisonRun_State.png'

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    # ── 3.2.2 Design Diagrams ────────────────────────────────────────────────
    add_heading(doc, '3.2.2 Design Diagrams', level=2)

    # 3.2.2.1 UML notation in use  ~65 words
    add_heading(doc, '3.2.2.1 UML notation in use', level=3)
    add_paragraph(
        doc,
        'Five UML diagram families are used in this chapter. Use case '
        'diagrams show who interacts with the system and what they can '
        'do. Deployment diagrams show where the code runs. Sequence '
        'diagrams trace a single flow step by step. Activity diagrams '
        'show branching and parallel work. State diagrams show the '
        'lifecycle of a record from creation to approval.',
    )

    # 3.2.2.2 Actors and use cases  ~141 words
    add_heading(doc, '3.2.2.2 Actors and use cases', level=3)
    add_paragraph(
        doc,
        'Figure 4 names the three human actors. The Compliance Analyst '
        'uploads documents, runs a policy mapping, and chats with the '
        'assistant. The Legal Reviewer validates each analysis before '
        'it can be exported, edits severity and due dates, and downloads '
        'the approved report. The Administrator manages user accounts, '
        'configures the model and the term dictionary, and reviews any '
        'chunks the prompt-injection scanner flags for inspection. '
        'Three relationships use UML stereotypes. The «include» from '
        'Run policy mapping to Verify citations signals that every '
        'mapping ends in a verification step. The «extend» from '
        'Auto-detect relevant regulations to Run policy mapping marks '
        'the optional shortcut that picks regulations automatically. '
        'The «include» from Download approved report to Generate audit '
        'hash signals that every export carries a tamper-evidence stamp. '
        'The mechanics of each use case are traced in Appendix 2.3.',
    )
    add_image(doc, fig_d2, width_cm=15.0)
    add_figure_caption(
        doc,
        'Figure 4.',
        'Use case diagram showing the three actors (Analyst, Reviewer, '
        'Administrator) and the system services they reach. The '
        'stereotyped «include» and «extend» links highlight three '
        'design rules: every mapping ends in verification, every export '
        'carries an audit hash, and regulation routing can run '
        'automatically. Mechanics for each use case appear in Figures '
        'A2.3a, A2.3b, and A2.3c.',
    )

    # 3.2.2.3 Deployment topology  ~116 words
    add_heading(doc, '3.2.2.3 Deployment topology', level=3)
    add_paragraph(
        doc,
        'Figure 5 shows the deployment as a single host running four '
        'containers behind one trust boundary. The browser talks to '
        'Django over HTTPS. Django runs the web layer and dispatches '
        'background work to in-process workers. The workers read and '
        'write to the corpus, which is split between ChromaDB for '
        'meaning-based lookup and SQLite for keyword-based lookup. The '
        'local language model runs in a separate Ollama process and '
        'answers only to Django over a localhost socket. The dashed '
        'boundary marks the trust perimeter: nothing inside speaks to '
        'the public internet, and no document or query leaves the host. '
        'This single-host shape is driven by the confidentiality policy '
        'and is justified in §3.2.4.',
    )
    add_image(doc, fig_d3, width_cm=15.0)
    add_figure_caption(
        doc,
        'Figure 5.',
        'Deployment view: one on-premises host runs Django, the workers, '
        'ChromaDB, SQLite, and Ollama behind one trust boundary. The '
        'shape keeps every document and every query inside the host, '
        'which is the controlling constraint from the confidentiality '
        'policy. The reasoning behind this choice is unpacked in §3.2.4.',
    )

    # 3.2.2.4 End-to-end pipeline  ~156 words
    add_heading(doc, '3.2.2.4 End-to-end pipeline', level=3)
    add_paragraph(
        doc,
        'Figure 6 puts the whole system on one page. The pipeline '
        'has two halves. The offline half runs once per document. An '
        'administrator uploads a file, the ingestion phase reads and '
        'chunks it, learns each chunk, and saves the result into both '
        'the meaning index (ChromaDB) and the word index (SQLite '
        'FTS5). The corpus then sits on disk until needed. The online '
        'half runs once per user question. The retrieval phase looks '
        'up the best chunks from both indexes, blends and reranks the '
        'results, and passes the top chunks to the reasoning phase. '
        'The reasoning phase drafts an answer with the local model, '
        'verifies the answer against the chunks, corrects it if '
        'verification fails, and finalises it with citations and a '
        'confidence score. The verified answer goes back to the user. '
        'The mechanics of each phase appear in Figure A2.3d (ingestion), '
        'Figure A2.3e (retrieval), and Figure A2.3f (reasoning).',
    )
    add_image(doc, fig_backbone, width_cm=16.0)
    add_figure_caption(
        doc,
        'Figure 6.',
        'End-to-end pipeline drawn as two halves: an offline ingestion '
        'path that fills the corpus, and an online retrieval-and-'
        'reasoning path that answers each question. The split keeps '
        'every per-question step fast and lets the slow ingestion work '
        'happen in the background. The internal steps of each phase '
        'are drawn in Figures A2.3d, A2.3e, and A2.3f.',
    )

    # 3.2.2.5 Where to find the rest  ~41 words
    add_heading(doc, '3.2.2.5 Where to find the rest', level=3)
    add_paragraph(
        doc,
        'Sequence-level traces for the three main user journeys '
        '(analyst mapping, copilot answer, reviewer cascade) appear as '
        'Figures A2.3a to A2.3c in Appendix 2.3. Lifecycle state '
        'machines for the three workflow records appear as Figures '
        'A2.5a to A2.5c in Appendix 2.5.',
    )

    # ── PAGE BREAK → Appendix ─────────────────────────────────────────────────
    add_page_break(doc)

    # ── Appendix 2.3 ──────────────────────────────────────────────────────────
    add_heading(doc, 'Appendix 2.3 — Per-phase mechanics', level=2)
    add_paragraph(
        doc,
        'The figures below expand each phase introduced in §3.2.2. '
        'Sequence diagrams trace one user journey from start to end; '
        'activity diagrams trace the internal steps of one phase.',
    )

    # A2.3a Analyst sequence
    add_image(doc, fig_a2_3a, width_cm=15.0)
    add_figure_caption(
        doc,
        'Figure A2.3a.',
        'Sequence diagram of a full analyst-led policy mapping. The '
        'analyst submits the form and Django creates the parent '
        'MappingAnalysis row plus one ObligationMapping child row per '
        'regulatory obligation in scope. Each loop iteration then runs '
        'retrieval and reasoning over a single obligation, which keeps '
        'every language-model call grounded in just that obligation’s '
        'evidence and bounds the context window per call. When the '
        'verifier inside the reasoning step rejects an answer, the '
        'reasoning graph attempts a correction; if retries exhaust, '
        'a deterministic fallback is returned and the row is flagged '
        'low confidence. The trade-off is longer total wall-clock time '
        'per analysis, accepted because each per-obligation result is '
        'independently auditable and re-runnable from its row. '
        'Verification and correction details are in Figure A2.3f; the '
        'lifecycle states the analysis moves through are in Figure '
        'A2.5a.',
    )

    # A2.3b Copilot sequence
    add_image(doc, fig_a2_3b, width_cm=15.0)
    add_figure_caption(
        doc,
        'Figure A2.3b.',
        'Sequence diagram of one Copilot round-trip. The user asks a '
        'question, an intent router classifies it as a comparison '
        'lookup, a policy-gap lookup, a regulatory lookup, or a mixed '
        'query, and the dispatcher then pulls the matching approved '
        'evidence instead of running a fresh retrieval from scratch. '
        'Routing to existing approved data is what keeps Copilot '
        'answers cheap, fast, and traceable: a comparison question '
        'reuses an approved ComparisonResult; a policy question reuses '
        'an approved ObligationMapping; a regulatory question falls '
        'through to hybrid retrieval. If no approved evidence exists '
        'for the question type, the dispatcher falls back to live '
        'hybrid retrieval and labels the answer as ungrounded so the '
        'reviewer can spot it. The trade-off is one extra '
        'classification call per question, accepted because it cuts '
        'overall answer latency and keeps every Copilot response '
        'pointing at something a reviewer has already signed off. '
        'Hybrid retrieval is in Figure A2.3e; the reasoning loop is '
        'in Figure A2.3f.',
    )

    # A2.3c Reviewer cascade sequence
    add_image(doc, fig_a2_3c, width_cm=15.0)
    add_figure_caption(
        doc,
        'Figure A2.3c.',
        'Sequence diagram of reviewer validation with cascade. '
        'Approving the parent analysis automatically approves every '
        'child finding that is currently in DRAFT or REVIEWED, then '
        'invalidates the sidebar cache so badge counts reflect the new '
        'state. The cascade exists so reviewers don’t have to click '
        'through every child finding when the parent decision is the '
        'real call. Cascaded children are stamped with '
        'human_override = True so the audit log distinguishes "reviewer '
        'specifically read this finding" from "reviewer approved the '
        'parent and accepted defaults". Children already rejected by '
        'an earlier action stay rejected; the cascade does not '
        'override an explicit reject. The trade-off is less per-finding '
        'scrutiny when bulk-approving, mitigated by the override flag '
        'surfacing review depth in reports. State machines for both '
        'levels are in Figures A2.5a and A2.5b.',
    )

    # A2.3d Ingestion activity
    add_image(doc, fig_a2_3d, width_cm=16.0)
    add_figure_caption(
        doc,
        'Figure A2.3d.',
        'Activity diagram of the six-stage ingestion pipeline with '
        'three swim lanes (Administrator, Django web layer, Ingestion '
        'pipeline). The lane split makes the trust boundary visible: '
        'only the administrator can release a quarantined chunk, and '
        'the pipeline cannot decide on its own. The OCR branch fires '
        'only when text extraction returns fewer than fifty characters, '
        'so digital PDFs skip the slower scanning step. The '
        'quarantine branch routes any chunk flagged by the '
        'prompt-injection regex scanner to administrator review before '
        'it touches the indexes; rejected chunks write to the audit '
        'log instead. The trade-off is one manual step per flagged '
        'chunk, accepted because a silent auto-reject could lose '
        'legitimate content without leaving a trace. The Document and '
        'IngestionJob lifecycle states the pipeline drives through are '
        'in Figure A2.5a.',
    )

    # A2.3e Retrieval activity
    add_image(doc, fig_a2_3e, width_cm=14.0)
    add_figure_caption(
        doc,
        'Figure A2.3e.',
        'Activity diagram of hybrid retrieval. The cleaned query fans '
        'out to a keyword search (SQLite FTS5 BM25, top-20) and a '
        'meaning search (ChromaDB HNSW, top-20) in parallel; both lists '
        'are then merged with Reciprocal Rank Fusion using k = 60 and '
        'reranked by a cross-encoder. Both methods are needed: keyword '
        'search catches the exact legal acronyms (DPO, PDPL, GDPR) '
        'that vector embeddings struggle with, and meaning search '
        'catches the paraphrases that keyword search misses. If the '
        'reranked list is empty and the user picked a specific '
        'document, the pipeline falls back to that document’s opening '
        'chunks for summary-style answers. The trade-off is doubling '
        'the index-load cost per query, accepted because the literature '
        'flags single-method retrieval as the main hybrid-retrieval '
        'failure mode in legal corpora. The full algorithm is unpacked '
        'in §3.2.3.',
    )

    # A2.3f Reasoning activity
    add_image(doc, fig_a2_3f, width_cm=14.0)
    add_figure_caption(
        doc,
        'Figure A2.3f.',
        'Activity diagram of the reasoning loop. The local language '
        'model drafts an answer, a verifier runs two checks against '
        'the retrieved chunks (citation grounding — does every quoted '
        'clause appear verbatim in a chunk? — and natural-language '
        'entailment — do the claims follow from the chunks?), and a '
        'corrector retries the prompt with the verifier’s complaint if '
        'either check fails. The retry budget is three by default; '
        'first two failures go to correct, the third triggers '
        'fallback. Fallback returns a deterministic safe summary of '
        'the chunks themselves rather than letting the model keep '
        'guessing, and marks confidence as low. The trade-off is up '
        'to three times the single-shot latency, accepted because the '
        'system exists to prevent unverified answers in a legal '
        'context — that is the failure mode the design is built '
        'around. The verifier and fallback algorithms are detailed in '
        '§3.2.3.',
    )

    # ── PAGE BREAK → Appendix 2.5 ─────────────────────────────────────────────
    add_page_break(doc)

    # ── Appendix 2.5 ──────────────────────────────────────────────────────────
    add_heading(doc, 'Appendix 2.5 — Lifecycle states', level=2)
    add_paragraph(
        doc,
        'The state machines below show the lifecycle of the three '
        'workflow records the system tracks. Each transition is a '
        'controlled action; nothing changes state silently.',
    )

    # A2.5a Mapping analysis state
    add_image(doc, fig_a2_5a, width_cm=14.0)
    add_figure_caption(
        doc,
        'Figure A2.5a.',
        'State machine for a MappingAnalysis record. RUNNING moves to '
        'COMPLETE if every per-obligation call succeeded, or to FAILED '
        'if any obligation failed irrecoverably; only COMPLETE rows '
        'can move on to REVIEW. The transitions enforce a one-way '
        'audit trail: once a record is APPROVED, it cannot be silently '
        'mutated, and any correction needs a fresh DRAFT run that '
        'leaves the old row in the log. A reject from REVIEW sends '
        'the record back to DRAFT so the analyst can edit and '
        'resubmit; FAILED runs can also be retried from DRAFT, but '
        'the failed row stays in place for audit. The trade-off is '
        'that an analyst cannot fix a typo after approval — they '
        'have to start a new analysis — accepted because the audit '
        'trail value outweighs the friction. The driving sequence is '
        'in Figure A2.3a; child-finding states are in Figure A2.5b.',
    )

    # A2.5b Obligation mapping state
    add_image(doc, fig_a2_5b, width_cm=14.0)
    add_figure_caption(
        doc,
        'Figure A2.5b.',
        'State machine for an ObligationMapping record, which is one '
        'row of findings under a MappingAnalysis. Findings can reach '
        'APPROVED two ways: a reviewer explicitly approves the child '
        '(human_override = False), or the parent analysis is approved '
        'and the cascade promotes eligible children (human_override = '
        'True). The override flag distinguishes "the reviewer read '
        'this row" from "the reviewer accepted the defaults", so audit '
        'reports can show review depth at the finding level. A child '
        'already in REJECTED stays rejected even when the parent is '
        'approved; the cascade never overrides an explicit reject. '
        'The trade-off is less per-finding scrutiny when bulk '
        'approving, mitigated by surfacing the override flag in '
        'reports. The cascade sequence is in Figure A2.3c; parent '
        'states are in Figure A2.5a.',
    )

    # A2.5c Comparison run state
    add_image(doc, fig_a2_5c, width_cm=14.0)
    add_figure_caption(
        doc,
        'Figure A2.5c.',
        'State machine for a ComparisonRun record, which represents '
        'one cross-jurisdictional comparison across one or more '
        'regulation pairs. PARTIALLY_FAILED exists because a '
        'comparison spans multiple pairs and a single failed pair '
        'should not sink the whole run; each pair carries its own '
        'success or failure status, and the parent rolls up to '
        'PARTIALLY_FAILED only when some pairs succeeded and some '
        'failed. FAILED is reserved for the case where every pair '
        'failed. Reviewers can still approve a PARTIALLY_FAILED run '
        'after inspecting the per-pair breakdown; rejecting sends the '
        'whole run to REJECTED regardless of pair outcomes. The '
        'trade-off is one extra state for reviewers to learn, '
        'accepted because the alternative — a binary success or '
        'failure — would force a re-run of every pair just because '
        'one failed. The comparison engine and the per-pair logic are '
        'in §3.2.3.',
    )

    doc.save(out_path)
    print(f'Wrote: {out_path}')


if __name__ == '__main__':
    main()
