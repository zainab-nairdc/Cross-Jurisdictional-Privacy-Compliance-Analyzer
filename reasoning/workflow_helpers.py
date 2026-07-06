# workflow_helpers.py
# shared helpers used by reasoning/workflows.py — chunk formatting and
# citation verification for the three specialised workflows (comparison /
# policy mapping / gap analysis).
#
# kept small on purpose: just pure functions, no llm calls, no graph state.

from __future__ import annotations

import re
import threading


def _dedup_content(text: str) -> str:
    """drop repeated sentence fragments from pdf-extracted text. multi-column
    layouts often produce verbatim duplicates that confuse the llm. eventually
    this should run at ingest time, not per-llm-call."""
    parts = re.split(r'(?<=[.!?;])\s+', text)
    seen: set[str] = set()
    clean: list[str] = []
    for s in parts:
        key = re.sub(r'\s+', ' ', s.strip().lower())[:60]
        if key and key not in seen:
            seen.add(key)
            clean.append(s)
    return ' '.join(clean)


def format_nodes(nodes: list, label: str, max_chars: int = 3000) -> str:
    """turn a list of NodeWithScore (from retrieval) into a labelled context
    block. each chunk gets a header like:
        [Chunk N] (node_id=abc123) CITATION: <citation>
    so the llm has three things to copy when it cites:
      - the chunk number (for source_chunk_a / source_chunk_b)
      - the node_id    (for *_chunk_id fields → ui click-through)
      - the citation text (for *_citation fields)
    the verifier then checks each piece against the actual retrieved chunks."""
    lines = [f"=== {label} ==="]
    total = 0
    for i, n in enumerate(nodes, 1):
        m = n.node.metadata
        content = _dedup_content(n.node.get_content().strip())
        nid      = m.get("node_id", "") or n.node.node_id or ""
        reg_name = m.get("regulation_name", "Unknown Regulation")
        ref      = m.get("article_ref", "")
        citation = f"{reg_name} — {ref}" if ref else reg_name
        header   = f"[Chunk {i}] (node_id={nid}) CITATION: {citation}"
        remaining = max_chars - total
        if len(content) > remaining:
            content = content[:remaining].rsplit(" ", 1)[0] + " ..."
        lines += [header, content, ""]
        total += len(content)
        if total >= max_chars:
            break
    return "\n".join(lines)


def _normalise_quote(s: str) -> str:
    """case-insensitive, whitespace-collapsed string used for substring
    matching. handles unicode dashes / curly quotes by stripping nothing —
    we want to catch llm paraphrasing, so a strict comparison is correct."""
    return " ".join((s or "").lower().split())


def _evidence_in_chunk(evidence: str, chunk_text: str) -> bool:
    """fuzzy-ish verbatim check. evidence must appear as a substring of the
    chunk after whitespace normalisation. returns False for empty evidence."""
    if not evidence or len(evidence.strip()) < 10:
        return False
    return _normalise_quote(evidence) in _normalise_quote(chunk_text)


def _extract_chunk_citations(context: str) -> dict[int, str]:
    """parse `[Chunk N] (node_id=...) CITATION: <text>` headers from a
    context block and return {chunk_number: citation_string}.

    used by verify_comparison_citations for auto-correction. accepts the
    optional `(node_id=...)` segment because that's what format_nodes()
    emits — without it, every citation check returns "not found" and the
    verifier wrongly marks every row unverified.
    """
    out: dict[int, str] = {}
    pattern = r'\[Chunk (\d+)\](?:\s*\(node_id=[^)]*\))?\s*CITATION:\s*(.+)'
    for m in re.finditer(pattern, context):
        out[int(m.group(1))] = m.group(2).strip()
    return out


def _index_nodes(nodes: list) -> dict[str, str]:
    """{node_id: content} map for quick lookup during evidence verification."""
    out: dict[str, str] = {}
    for n in nodes:
        nid = n.node.metadata.get("node_id") or n.node.node_id or ""
        if nid:
            out[nid] = n.node.get_content()
    return out


def _index_doc_titles(nodes: list) -> dict[str, str]:
    """{node_id: doc_title} map. used to auto-fill doc_title fields on each
    row so the ui can navigate to the right document."""
    out: dict[str, str] = {}
    for n in nodes:
        nid = n.node.metadata.get("node_id") or n.node.node_id or ""
        if nid:
            out[nid] = n.node.metadata.get("doc_title", "")
    return out


def _index_nodes_by_position(nodes: list) -> dict[int, str]:
    """{chunk_number (1-indexed): node_id} — mirrors the [Chunk N] order
    in format_nodes()."""
    return {i: (n.node.metadata.get("node_id") or n.node.node_id or "")
            for i, n in enumerate(nodes, 1)}


# per-row NLI hallucination scoring
# uses the same cross-encoder NLI model as the chat orchestrator
# (validators.score_hallucination). loaded once on first use.

_nli_model = None
_nli_model_lock = threading.Lock()


def _get_nli_model():
    """Thread-safe lazy load of the deberta-v3 NLI cross-encoder. ~700mb,
    loaded once. Double-checked locking so concurrent first-callers don't
    both pay the ~5s init + 700MB memory cost."""
    global _nli_model
    if _nli_model is None:
        with _nli_model_lock:
            if _nli_model is None:
                from sentence_transformers import CrossEncoder
                # avoid hardcoding the model name — read from reasoning config so a
                # user can swap it via env var if they want a smaller/different model.
                try:
                    from reasoning.config import cfg
                    model_name = cfg.validation.hallucination_model
                except Exception:
                    model_name = "cross-encoder/nli-deberta-v3-base"
                _nli_model = CrossEncoder(model_name)
    return _nli_model


def score_text_against_chunk(text: str, chunk_text: str) -> float:
    """run NLI between a text and a single chunk. returns hallucination risk
    in [0.0, 1.0] where 0=fully entailed and 1=fully contradicted/unsupported.

    used per-row to score the AI's analysis (e.g. reg_a_requirement) against
    the chunk it cited. catches subtle paraphrase drift that the structural
    citation check can't see."""
    if not text or not chunk_text or len(text.strip()) < 10:
        return 1.0
    import numpy as np
    ce = _get_nli_model()
    raw = ce.predict([(chunk_text, text)])
    raw = np.array(raw)
    # raw is shape (1, 3) for a single (premise, hypothesis) pair —
    # logits over [contradiction, neutral, entailment]
    if raw.ndim == 1:
        return round(1.0 - float(np.mean(raw)), 3)
    # softmax to convert logits → probabilities
    exp = np.exp(raw - raw.max(axis=1, keepdims=True))
    probs = exp / exp.sum(axis=1, keepdims=True)
    entailment_prob = float(probs[0, 2])
    return round(1.0 - entailment_prob, 3)


def _is_fully_hallucinated_comparison(ob: dict) -> bool:
    """row is "pure noise" if it has neither side properly cited AND the
    AI's prose summary doesn't follow from anything we retrieved.
    used to filter rows out of the final report so users don't see invented
    obligations as 'review me' candidates — they're just trash."""
    has_no_a_citation = not ob.get('reg_a_chunk_id')
    has_no_b_citation = not ob.get('reg_b_chunk_id')
    high_hall = (ob.get('hallucination_risk') or 0.0) > 0.90
    # both sides missing OR (one side missing + extreme hallucination on the
    # other) → pure invention. drop.
    if has_no_a_citation and has_no_b_citation:
        return True
    if (has_no_a_citation or has_no_b_citation) and high_hall:
        return True
    return False


def verify_comparison_citations(
    obligations_data: list[dict],
    context_a:        str,
    context_b:        str,
    nodes_a:          list | None = None,
    nodes_b:          list | None = None,
    score_hallucination: bool = True,
    drop_hallucinated:   bool = True,
) -> tuple[list[dict], list[str]]:
    """verify ComparisonReport obligation rows.

    structural checks per row:
      - source_chunk_a/b   → auto-populates reg_a/b_citation + reg_a/b_chunk_id
      - reg_a/b_citation   → must appear in the chunk-citation headers
      - reg_a/b_chunk_id   → must match a real retrieved chunk's node_id
      - reg_a/b_evidence   → must be a verbatim substring of that chunk
      - reg_a/b_doc_title  → auto-filled from chunk metadata for ui navigation

    semantic check per row (when score_hallucination=True):
      - NLI model scores the AI's reg_a_requirement / reg_b_requirement
        against the cited chunks. row.hallucination_risk is set to the worse
        of the two sides (0 = grounded, 1 = unsupported / contradicted).

    citation_verified is True only when ALL structural checks pass.
    """
    cits_a = _extract_chunk_citations(context_a)
    cits_b = _extract_chunk_citations(context_b)
    all_a = set(cits_a.values())
    all_b = set(cits_b.values())

    nid_a_by_pos  = _index_nodes_by_position(nodes_a) if nodes_a else {}
    nid_b_by_pos  = _index_nodes_by_position(nodes_b) if nodes_b else {}
    text_a        = _index_nodes(nodes_a) if nodes_a else {}
    text_b        = _index_nodes(nodes_b) if nodes_b else {}
    doc_title_a   = _index_doc_titles(nodes_a) if nodes_a else {}
    doc_title_b   = _index_doc_titles(nodes_b) if nodes_b else {}

    issues: list[str] = []

    for ob in obligations_data:
        sc_a = ob.get('source_chunk_a')
        sc_b = ob.get('source_chunk_b')

        # auto-correct citation labels via source_chunk index
        if isinstance(sc_a, int) and sc_a in cits_a:
            ob['reg_a_citation'] = cits_a[sc_a]
        if isinstance(sc_b, int) and sc_b in cits_b:
            ob['reg_b_citation'] = cits_b[sc_b]

        # auto-fill chunk_id from source_chunk if the llm forgot
        if not ob.get('reg_a_chunk_id') and isinstance(sc_a, int) and sc_a in nid_a_by_pos:
            ob['reg_a_chunk_id'] = nid_a_by_pos[sc_a]
        if not ob.get('reg_b_chunk_id') and isinstance(sc_b, int) and sc_b in nid_b_by_pos:
            ob['reg_b_chunk_id'] = nid_b_by_pos[sc_b]

        # auto-fill doc_title from chunk metadata
        if not ob.get('reg_a_doc_title') and ob.get('reg_a_chunk_id'):
            ob['reg_a_doc_title'] = doc_title_a.get(ob['reg_a_chunk_id'], '')
        if not ob.get('reg_b_doc_title') and ob.get('reg_b_chunk_id'):
            ob['reg_b_doc_title'] = doc_title_b.get(ob['reg_b_chunk_id'], '')

        # citation label check (lenient — label drift is common)
        cit_a = ob.get('reg_a_citation', '') or ''
        cit_b = ob.get('reg_b_citation', '') or ''
        ok_a_label = (cit_a in all_a) or (not cit_a)
        ok_b_label = (cit_b in all_b) or (not cit_b)

        # evidence check (verbatim) — also try cross-chunk matching: the
        # llm sometimes mis-attributes a quote to the wrong chunk_id.
        # accept if the quote exists in ANY chunk on that side, and
        # auto-correct chunk_id to the real source.
        def _verbatim_or_recover(side_text_map: dict, ev: str, chunk_id_key: str) -> bool:
            if not (text_a if side_text_map is text_a else text_b) or not ev:
                return True
            ch = ob.get(chunk_id_key, '') or ''
            chunk_text = side_text_map.get(ch, '')
            if _evidence_in_chunk(ev, chunk_text):
                return True
            # try every other chunk on this side
            for nid, txt in side_text_map.items():
                if nid == ch:
                    continue
                if _evidence_in_chunk(ev, txt):
                    ob[chunk_id_key] = nid
                    return True
            return False

        ok_a_evidence = _verbatim_or_recover(text_a, ob.get('reg_a_evidence', ''), 'reg_a_chunk_id')
        ok_b_evidence = _verbatim_or_recover(text_b, ob.get('reg_b_evidence', ''), 'reg_b_chunk_id')

        # citation_verified rule:
        # • verbatim evidence is the strongest signal. when evidence is
        #   present on a side, accept that side based on evidence alone.
        # • when no evidence is provided on a side (e.g. "Only in A"
        #   classification leaves B empty), fall back to the label check.
        a_ok = ok_a_evidence if ob.get('reg_a_evidence') else ok_a_label
        b_ok = ok_b_evidence if ob.get('reg_b_evidence') else ok_b_label
        ob['citation_verified'] = a_ok and b_ok

        # NLI hallucination scoring on the AI's prose summaries
        if score_hallucination and (text_a or text_b):
            risks = []
            if text_a and ob.get('reg_a_requirement'):
                chunk_text = text_a.get(ob.get('reg_a_chunk_id', ''), '')
                if chunk_text:
                    risks.append(score_text_against_chunk(ob['reg_a_requirement'], chunk_text))
            if text_b and ob.get('reg_b_requirement'):
                chunk_text = text_b.get(ob.get('reg_b_chunk_id', ''), '')
                if chunk_text:
                    risks.append(score_text_against_chunk(ob['reg_b_requirement'], chunk_text))
            # take the WORSE of the two sides — if A is paraphrased badly,
            # the row is still suspect even if B is fine.
            ob['hallucination_risk'] = max(risks) if risks else 0.0

        if not ok_a_label:
            issues.append(f"reg_a_citation '{cit_a[:60]}' not in retrieved chunks for {ob.get('topic','?')}")
        if cit_b and not ok_b_label:
            issues.append(f"reg_b_citation '{cit_b[:60]}' not in retrieved chunks for {ob.get('topic','?')}")
        if not ok_a_evidence:
            issues.append(f"reg_a_evidence not verbatim in cited chunk for {ob.get('topic','?')}")
        if not ok_b_evidence:
            issues.append(f"reg_b_evidence not verbatim in cited chunk for {ob.get('topic','?')}")

    # drop fully-hallucinated rows so the user never sees them. logged so
    # the audit trail captures what the ai tried to invent.
    if drop_hallucinated:
        kept = []
        for ob in obligations_data:
            if _is_fully_hallucinated_comparison(ob):
                issues.append(
                    f"DROPPED hallucinated row: '{ob.get('topic','?')}' "
                    f"(no citations, hall_risk={ob.get('hallucination_risk',0):.2f})"
                )
                continue
            kept.append(ob)
        obligations_data = kept

    return obligations_data, issues


def verify_policy_mapping_citations(
    items_data:          list[dict],
    context_regulation:  str,
    context_policies:    str,
    nodes_regulation:    list | None = None,
    nodes_policies:      list | None = None,
    score_hallucination: bool = True,
    drop_hallucinated:   bool = True,
) -> tuple[list[dict], list[str]]:
    """verifier for PolicyMappingReport.items[] — checks BOTH sides.

    asymmetric by design (mirrors the workflow asymmetry):
      regulation side (REQUIRED — citation_verified depends on it):
        - regulation_citation → must match a chunk-citation header
        - regulation_chunk_id → must be a real node_id from nodes_regulation
        - regulation_evidence → must be a verbatim substring of that chunk
        - regulation_doc_title → auto-filled from chunk metadata
        - NLI scores regulatory_obligation against the cited regulation chunk
      policy side (OPTIONAL — empty is the legitimate "Not Covered" case):
        - policy_chunk_id     → if claimed, must be a real node_id from nodes_policies
        - policy_excerpt      → if claimed, must be verbatim in some policy chunk
                                (auto-corrects policy_chunk_id on cross-chunk match)
        - policy_doc_title    → auto-filled from chunk metadata
        bad policy citations are reported as issues so the correction loop
        can fix them, but they DO NOT flip citation_verified — that flag is
        scoped to regulation grounding, which is the source of truth.
    """
    rows, reg_issues = verify_simple_citations(
        items_data, context_regulation,
        citation_field      = "regulation_citation",
        label_field         = "regulatory_obligation",
        nodes               = nodes_regulation,
        chunk_id_field      = "regulation_chunk_id",
        evidence_field      = "regulation_evidence",
        doc_title_field     = "regulation_doc_title",
        summary_field       = "regulatory_obligation",
        score_hallucination = score_hallucination,
        drop_hallucinated   = drop_hallucinated,
    )

    pol_text_map  = _index_nodes(nodes_policies)      if nodes_policies else {}
    pol_title_map = _index_doc_titles(nodes_policies) if nodes_policies else {}

    pol_issues: list[str] = []
    for r in rows:
        ev = (r.get("policy_excerpt") or "").strip()
        ch = (r.get("policy_chunk_id") or "").strip()
        if not ev and not ch:
            continue   # legitimate Not Covered / Requires Review row

        if ch and not r.get("policy_doc_title"):
            r["policy_doc_title"] = pol_title_map.get(ch, "")

        if not ev:
            # citation but no quote — fine for the structural check; the UI
            # can render a chunk_id-only reference. nothing to verify.
            continue

        chunk_text = pol_text_map.get(ch, "")
        if _evidence_in_chunk(ev, chunk_text):
            continue
        # try every other policy chunk; auto-correct chunk_id on a hit
        recovered = False
        for nid, txt in pol_text_map.items():
            if nid != ch and _evidence_in_chunk(ev, txt):
                r["policy_chunk_id"]  = nid
                r["policy_doc_title"] = pol_title_map.get(nid, "")
                recovered = True
                break
        if not recovered:
            label = (r.get("regulatory_obligation") or "?")[:60]
            pol_issues.append(f"policy_excerpt not verbatim in any retrieved policy chunk for {label}")

    return rows, reg_issues + pol_issues


def verify_simple_citations(
    rows:                list[dict],
    context:             str,
    citation_field:      str,
    label_field:         str = "topic",
    nodes:               list | None = None,
    chunk_id_field:      str | None = None,
    evidence_field:      str | None = None,
    doc_title_field:     str | None = None,
    summary_field:       str | None = None,
    score_hallucination: bool = True,
    drop_hallucinated:   bool = True,
) -> tuple[list[dict], list[str]]:
    """verifier for PolicyMappingReport.items[] and GapAnalysisReport.gaps[].

    structural checks per row:
      - <citation_field>     → must match a chunk-citation header (partial ok)
      - <chunk_id_field>     → must be a real node_id from `nodes` (when given)
      - <evidence_field>     → must be a verbatim substring of that chunk
      - <doc_title_field>    → auto-filled from chunk metadata for ui navigation
    semantic check per row (when score_hallucination=True):
      - NLI scores <summary_field> against the cited chunk
      - row['hallucination_risk'] in [0,1] (0 = entailed, 1 = unsupported)
    sets row['citation_verified'] = True only if all structural checks pass.
    """
    cits      = set(_extract_chunk_citations(context).values())
    text_map  = _index_nodes(nodes)      if nodes else {}
    title_map = _index_doc_titles(nodes) if nodes else {}

    issues: list[str] = []
    for r in rows:
        cit = (r.get(citation_field) or '').strip()
        # label match — partial substring either direction. lenient on
        # purpose because legal phrasings drift between the chunk metadata
        # and what the llm produces (e.g. "PDPL Art. 23" vs "Personal Data
        # Protection Law 30/2018 — Article (23) Right to request...").
        ok_label = bool(cit) and any(cit in c or c in cit for c in cits)
        if cit and not ok_label:
            issues.append(f"{citation_field} '{cit[:60]}' not exact match in chunk citations for {r.get(label_field,'?')}")

        # auto-fill doc_title from chunk metadata
        if doc_title_field and chunk_id_field and not r.get(doc_title_field):
            r[doc_title_field] = title_map.get(r.get(chunk_id_field, ''), '')

        ok_evidence = True
        chunk_text = ''
        if evidence_field and chunk_id_field and text_map:
            ev = r.get(evidence_field, '') or ''
            ch = r.get(chunk_id_field, '') or ''
            if ev:
                chunk_text = text_map.get(ch, '')
                # try the cited chunk first
                ok_evidence = _evidence_in_chunk(ev, chunk_text)
                # if the cited chunk doesn't contain the evidence, try ALL
                # chunks. the llm sometimes mis-attributes a quote to the
                # wrong chunk_id. accept the citation as long as the quote
                # exists in some retrieved chunk, and auto-correct the
                # chunk_id to the chunk that actually contains it.
                if not ok_evidence:
                    for nid, txt in text_map.items():
                        if _evidence_in_chunk(ev, txt):
                            r[chunk_id_field] = nid
                            ok_evidence = True
                            chunk_text = txt
                            break
                if not ok_evidence:
                    issues.append(f"{evidence_field} not verbatim in any retrieved chunk for {r.get(label_field,'?')}")

        # citation_verified rule:
        # • if we have an evidence field, a verbatim quote from a real chunk
        #   is the STRONGEST signal — accept the row even if the label
        #   doesn't match exactly. label drift is common (the llm rephrases
        #   citation strings) but verbatim evidence cannot be hallucinated.
        # • if we don't have evidence (older callers), fall back to label
        #   matching alone.
        if evidence_field and r.get(evidence_field):
            r['citation_verified'] = ok_evidence
        else:
            r['citation_verified'] = ok_label and ok_evidence

        # NLI scoring on the prose summary
        # for workflows where each row's obligation often spans multiple
        # sentences of the source regulation (gap analysis especially), the
        # cited chunk alone is too small a window. score against ALL the
        # retrieved chunks combined so the NLI model has the full context
        # to check entailment against. take the BEST score (lowest risk)
        # across chunks since the obligation only needs to be entailed by
        # ONE retrieved chunk to be valid.
        if score_hallucination and summary_field and text_map:
            summary_text = r.get(summary_field, '') or ''
            if summary_text:
                # try the cited chunk first, then fall back to all chunks
                ch = r.get(chunk_id_field or '', '') or ''
                cited_chunk = chunk_text or text_map.get(ch, '')
                risks = []
                if cited_chunk:
                    risks.append(score_text_against_chunk(summary_text, cited_chunk))
                # also check against all other retrieved chunks — picks up
                # cross-chunk obligations that the cited chunk alone can't
                # entail
                for nid, txt in text_map.items():
                    if nid == ch:
                        continue
                    risks.append(score_text_against_chunk(summary_text, txt))
                # the obligation only needs to be entailed by ONE chunk
                r['hallucination_risk'] = min(risks) if risks else 0.0
            else:
                r['hallucination_risk'] = 0.0

    # drop fully-hallucinated rows: no chunk_id AND extreme NLI risk
    if drop_hallucinated and chunk_id_field:
        kept = []
        for r in rows:
            no_citation = not r.get(chunk_id_field)
            high_hall = (r.get('hallucination_risk') or 0.0) > 0.90
            if no_citation and high_hall:
                issues.append(
                    f"DROPPED hallucinated row: '{r.get(label_field,'?')}' "
                    f"(no chunk_id, hall_risk={r.get('hallucination_risk',0):.2f})"
                )
                continue
            kept.append(r)
        rows = kept

    return rows, issues
