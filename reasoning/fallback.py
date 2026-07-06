# fallback.py
# what we return when the reasoning pipeline can't produce a grounded answer
# (max retries exhausted, no chunks retrieved, etc.). low confidence,
# no fabricated citations, and a hint at where to look manually.

import re
from datetime import datetime, timezone

from .schemas import ReasonedAnswer, ReasoningStep, SearchRequest

# Word-boundary regex so trailing punctuation ("breach;" -> "breach")
# doesn't sneak into the keyword list. Matches alphanumeric runs of 5+ chars.
_KEYWORD_RE = re.compile(r"\b\w{5,}\b", re.UNICODE)


async def safe_fallback_response(request: SearchRequest) -> ReasonedAnswer:
    """build a safe, non-hallucinated response when reasoning fails.
    confidence is intentionally low (0.3) so downstream consumers can
    decide to surface a "we couldn't answer" message rather than the body."""
    body = (
        "I cannot provide a fully grounded answer with the current context. "
        "Please refine your query or consult the following sources directly:\n\n"
    )

    # very rough keyword-based suggestion list. just so the user sees a
    # next step rather than an empty answer. these strings are static — no
    # llm call, no hallucination risk.
    keywords = [w.lower() for w in _KEYWORD_RE.findall(request.query)]
    suggestions: list[str] = []
    if any(k in keywords for k in ["data", "privacy", "personal"]):
        suggestions.append("- Bahrain PDPL (Personal Data Protection Law)")
        suggestions.append("- Kuwait DPPR (Data Privacy Protection Regulation)")
        suggestions.append("- India DPDP Act 2023")
    if any(k in keywords for k in ["bank", "financial", "kyc"]):
        suggestions.append("- Central Bank of Bahrain Rulebook")
        suggestions.append("- RBI KYC Master Direction")
    if any(k in keywords for k in ["cyber", "security", "incident"]):
        suggestions.append("- RBI Cybersecurity Framework for Banks")
        suggestions.append("- Kuwait CORF (Cyber Operational Resilience Framework)")
    if any(k in keywords for k in ["bbk", "internal", "policy"]):
        suggestions.append("- BBK internal policies (LGL-001, OPS-012, etc.)")

    if suggestions:
        body += "\n".join(suggestions)
    else:
        body += "- Review the full text of applicable regulations in your jurisdiction."

    return ReasonedAnswer(
        summary    = body,
        citations  = [],
        confidence = 0.3,
        reasoning_trace = [ReasoningStep(
            action      = "fallback",
            description = "safe response generated due to insufficient grounding",
            timestamp   = datetime.now(timezone.utc),
        )],
        route_used = request.route_hint or "general",
        warnings   = ["answer not fully grounded — verify with primary sources"],
    )
