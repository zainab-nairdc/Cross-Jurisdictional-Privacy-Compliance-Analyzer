# llm_shims.py
# free-text llm helpers used outside the structured-output pipeline.
#
# the orchestrator + generator handle structured (pydantic-validated) outputs
# for the main workflows. these shims handle the few spots that need raw
# free-text completions or tolerant json extraction:
#   • apps/comparison/insights.py  — AI summary + BBK implications cards
#   • tests/eval.py                — faithfulness eval scoring
#   • tests/eval_ragas.py          — sample answer collection

from __future__ import annotations

import json
import logging
import re

from .generator        import _get_llm
from .workflow_helpers import format_nodes as _format_nodes_impl

log = logging.getLogger(__name__)


def _call_llm(prompt: str, max_tokens: int = 4096, retries: int = 1) -> str:
    """free-text completion against the configured llm (openrouter +
    claude haiku 4.5 by default).

    Returns the model's text response (not parsed). Callers that want
    structured output should use the orchestrator or workflow_helpers
    instead — this shim is for plain-text answers only.
    """
    last_exc: Exception | None = None
    llm = _get_llm()
    for attempt in range(1, retries + 2):
        try:
            response = llm.invoke(prompt)
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            last_exc = e
            log.warning(
                "_call_llm attempt %d failed: %s — %s",
                attempt, e, "retrying" if attempt <= retries else "giving up",
            )
    # The for-loop always either returned or stored last_exc; if we reach
    # here, the LLM exhausted retries.
    raise last_exc  # type: ignore[misc]


def _extract_json(raw: str) -> dict | list:
    """tolerant json extractor. tries:
       1. parse the whole string
       2. strip markdown fences and parse
       3. find outermost { ... } or [ ... ] and parse that
    raises ValueError if all three fail."""
    if not raw:
        raise ValueError("empty response from llm")
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        idx = cleaned.find(start_char)
        if idx == -1:
            continue
        end_idx = cleaned.rfind(end_char)
        if end_idx <= idx:
            continue
        try:
            return json.loads(cleaned[idx : end_idx + 1])
        except json.JSONDecodeError:
            continue
    raise ValueError(f"no valid JSON in llm response:\n{raw[:400]}")


# format_nodes lives in workflow_helpers; re-exported here for the test
# scripts that import everything from this module.
_format_nodes = _format_nodes_impl
