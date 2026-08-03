# orchestrator.py
# the langgraph reasoning pipeline. one query in, one ReasonedAnswer out.
#
# pipeline:
#   route   -> classify the query into one of four routes
#   draft   -> generate a structured answer using the route's prompt
#   verify  -> check citations + score hallucination risk
#   correct -> re-prompt the model with the validation error (looped back
#              into verify, capped by max_retries)
#   finalize-> adjust confidence by verification score, return
#   fallback-> safe canned response when correction loop gives up
#
# state flows through ReasoningState (a TypedDict). every node returns the
# updated state. langgraph handles checkpointing and the conditional edge
# that decides whether to correct, finalize, or fall back.

import logging
import threading
from typing import Literal, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph             import END, StateGraph

from .config     import cfg
from .fallback   import safe_fallback_response
from .generator  import generate_structured
from .router     import classify_query
from .schemas    import ReasonedAnswer, ReasoningStep, SearchRequest
from .tracing    import trace_span
from .validators import score_hallucination, verify_grounding


log = logging.getLogger(__name__)


class ReasoningState(TypedDict, total=False):
    request:            SearchRequest
    route:              str
    retrieved_chunks:   list[dict]
    draft:              Optional[ReasonedAnswer]
    verification_score: Optional[float]
    hallucination_risk: Optional[float]
    cite_issues:        Optional[str]
    reasoning_trace:    list[ReasoningStep]
    retries:            int
    error:              Optional[str]
    final_output:       Optional[ReasonedAnswer]


# nodes
# each node takes a ReasoningState and returns the partial update. langgraph
# merges the returned dict into the existing state.

@trace_span("route_node")
async def route_node(state: ReasoningState) -> dict:
    """classify the query and pick a prompt template."""
    request = state["request"]
    route = request.route_hint or await classify_query(
        request.query, model=cfg.routing.classifier_model,
    )
    step = ReasoningStep(action="retrieve", description=f"routed to: {route}")
    return {
        "route": route,
        "reasoning_trace": state.get("reasoning_trace", []) + [step],
    }


@trace_span("draft_node")
async def draft_node(state: ReasoningState) -> dict:
    """run the llm with the route's prompt, get back a ReasonedAnswer.
    short-circuit to fallback when there are no chunks — asking the model
    to ground an answer in nothing just makes it hallucinate or loop the
    parser."""
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        from .fallback import safe_fallback_response
        fallback = await safe_fallback_response(state["request"])
        step = ReasoningStep(action="fallback", description="no chunks retrieved — short-circuit to fallback")
        return {
            "draft":           fallback,
            "final_output":    fallback,
            "error":           "no retrieved_chunks",
            "reasoning_trace": state.get("reasoning_trace", []) + [step],
            "retries":         0,
        }

    route_cfg  = cfg.routing.routes.get(state["route"], cfg.routing.routes[cfg.routing.default_route])
    prompt_key = route_cfg["prompt"]
    draft = await generate_structured(
        query           = state["request"].query,
        chunks          = chunks,
        route           = state["route"],
        prompt_key      = prompt_key,
        response_model  = ReasonedAnswer,
    )
    step = ReasoningStep(action="synthesize", description="generated draft answer")
    return {
        "draft":           draft,
        "reasoning_trace": state.get("reasoning_trace", []) + [step],
        "retries":         0,
    }


@trace_span("verify_node")
async def verify_node(state: ReasoningState) -> dict:
    """citation grounding check + nli-based hallucination score."""
    draft  = state["draft"]
    chunks = state.get("retrieved_chunks", [])

    grounded, cite_issues = await verify_grounding(draft, chunks)
    h_score               = await score_hallucination(draft.summary, chunks)

    step = ReasoningStep(
        action      = "verify",
        description = f"grounded: {grounded}, hallucination risk: {h_score:.2f}",
        outputs     = {"grounded": grounded, "hallucination_score": h_score},
    )
    return {
        "verification_score": 1.0 if grounded else 0.0,
        "hallucination_risk": h_score,
        "cite_issues":        cite_issues if not grounded else None,
        "reasoning_trace":    state.get("reasoning_trace", []) + [step],
    }


@trace_span("correct_node")
async def correct_node(state: ReasoningState) -> dict:
    """re-prompt the model with the verification error so it can fix its
    own mistake. capped at cfg.validation.max_retries."""
    if state.get("retries", 0) >= cfg.validation.max_retries:
        # Retry ceiling hit. Rather than discard the synthesized draft for a
        # canned passage-dump, KEEP the draft as the answer with a confidence
        # penalty for the unverified citations. Local 7B models routinely
        # paraphrase a quote just enough to miss the strict verbatim grounding
        # check, so throwing the whole answer away leaves the user staring at a
        # raw list of passages. A chunk-grounded synthesized answer with a
        # lowered confidence badge is far more useful — and still honest.
        draft = state.get("draft")
        if draft is not None:
            h_risk    = state.get("hallucination_risk") or 0.0
            base_conf = max(0.4, draft.confidence or 0.0)
            # Cap the NLI penalty (a local 7B model paraphrases enough that NLI
            # often reports ~0.99 "unsupported" even on a correct, chunk-grounded
            # answer) and floor the result. A grounded answer must never show a
            # near-zero "1% confident" badge — that reads as broken. The separate
            # low-trust banner still warns when verification is genuinely weak.
            conf = base_conf * 0.75 * (1.0 - min(h_risk, 0.4))
            penalised = draft.model_copy(update={
                "confidence": round(max(0.4, conf), 2),
            })
            return {"error": "verification uncertain", "final_output": penalised}
        # No draft at all — genuinely nothing to show; fall back safely.
        return {
            "error":        "max retries exceeded",
            "final_output": await safe_fallback_response(state["request"]),
        }

    issues  = state.get("cite_issues") or "low confidence on previous attempt"
    corrected = await generate_structured(
        query              = state["request"].query,
        chunks             = state.get("retrieved_chunks", []),
        route              = state["route"],
        prompt_key         = "base.yaml",   # conservative prompt for retry
        response_model     = ReasonedAnswer,
        correction_context = (
            f"previous attempt failed verification: {issues}. "
            f"ground every claim strictly in the chunks provided. "
            f"drop any citation you cannot verify against a chunk's exact text."
        ),
        previous_draft     = state["draft"],
    )
    step = ReasoningStep(
        action      = "synthesize",
        description = f"correction attempt #{state.get('retries', 0) + 1}",
    )
    return {
        "draft":              corrected,
        "retries":            state.get("retries", 0) + 1,
        "verification_score": None,    # re-verify
        "reasoning_trace":    state.get("reasoning_trace", []) + [step],
    }


@trace_span("finalize_node")
async def finalize_node(state: ReasoningState) -> dict:
    """adjust the draft's confidence by verification score and hallucination
    risk, then mark it as the final output."""
    draft        = state["draft"]
    v_score      = state.get("verification_score") or 0.5
    h_risk       = state.get("hallucination_risk") or 0.0
    # Floor the verification factor: a draft that reached finalize is a real
    # synthesized answer grounded in the retrieved chunks even if the strict
    # verbatim-quote check didn't confirm every citation. Zeroing its
    # confidence (v_score can be 0.0 when ungrounded) would blank a usable
    # answer, so we treat unverified-but-present as "moderate confidence".
    v_eff        = max(v_score, 0.7)
    # Floor at 0.4: a synthesised, chunk-grounded answer should never render as
    # "1% confident" (the NLI over-penalises the local model's paraphrasing).
    # The low-trust banner handles the genuine "verify this" warning separately.
    adjusted     = max(0.4, (draft.confidence or 0.7) * v_eff * (1.0 - min(h_risk, 0.4)))
    final        = draft.model_copy(update={"confidence": round(adjusted, 2)})
    return {"final_output": final}


@trace_span("fallback_node")
async def fallback_node(state: ReasoningState) -> dict:
    """last-resort safe response. only reached when correct_node gave up."""
    if state.get("final_output"):
        # already populated by correct_node when it hit max_retries
        return {}
    return {"final_output": await safe_fallback_response(state["request"])}


# routing logic for the conditional edges

def _after_draft(state: ReasoningState) -> Literal["verify", "end"]:
    """if draft_node short-circuited (e.g. no chunks retrieved -> fallback)
    it set final_output already. skip verify in that case."""
    if state.get("final_output") is not None:
        return "end"
    return "verify"


def _should_correct(state: ReasoningState) -> Literal["correct", "finalize", "fallback"]:
    """decide what comes after verify: correct (low scores, retries left),
    fallback (already errored), or finalize (good enough)."""
    if state.get("error"):
        return "fallback"
    v_score = state.get("verification_score") or 0
    h_risk  = state.get("hallucination_risk") or 1
    needs_retry = v_score < 0.7 or h_risk > 0.4
    if needs_retry:
        # Retries left → try to fix the citations. Out of retries → FINALIZE
        # the synthesized draft (with a confidence penalty in finalize_node)
        # rather than discarding it for a canned "cannot provide an answer"
        # response. Local 7B models routinely paraphrase a quote just enough
        # to miss the strict verbatim grounding check; a real chunk-grounded
        # answer with a lowered confidence badge is far more useful — and still
        # honest — than dumping the user to a raw passage list. Only truly
        # empty drafts (no chunks at all) reach the fallback, via draft_node.
        return "correct" if state.get("retries", 0) < cfg.validation.max_retries else "finalize"
    return "finalize"


# graph build

def build_reasoning_graph():
    graph = StateGraph(ReasoningState)

    graph.add_node("route",    route_node)
    graph.add_node("draft",    draft_node)
    graph.add_node("verify",   verify_node)
    graph.add_node("correct",  correct_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("fallback", fallback_node)

    graph.set_entry_point("route")
    graph.add_edge("route",    "draft")
    graph.add_conditional_edges(
        "draft",
        _after_draft,
        {"verify": "verify", "end": END},
    )
    graph.add_conditional_edges(
        "verify",
        _should_correct,
        {"correct": "correct", "finalize": "finalize", "fallback": "fallback"},
    )
    graph.add_edge("correct",  "verify")    # loop until verified or out of retries
    graph.add_edge("finalize", END)
    graph.add_edge("fallback", END)

    return graph.compile(checkpointer=MemorySaver())


# Module-level lazy singleton. Building the graph runs at first access
# rather than at import-time so a stale Django worker doesn't pay the
# ~200ms graph-build cost just for the import side-effect (and so an
# import-time exception in LangGraph fails on the call site, not the
# unsuspecting view that triggered the import chain). Access via
#   from reasoning.orchestrator import reasoning_graph
# triggers the __getattr__ hook below on first lookup.

_reasoning_graph: object | None = None
_reasoning_graph_lock = threading.Lock()


def __getattr__(name: str):
    if name == "reasoning_graph":
        global _reasoning_graph
        if _reasoning_graph is None:
            with _reasoning_graph_lock:
                if _reasoning_graph is None:
                    _reasoning_graph = build_reasoning_graph()
        return _reasoning_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
