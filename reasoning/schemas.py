# schemas.py
# pydantic models used by both the langgraph reasoning pipeline and the
# legacy analyzer.py workflows. two groups:
#
# 1. langgraph orchestrator schemas (Citation, ReasoningStep, ReasonedAnswer,
#    SearchRequest, StreamingChunk) — used by the route/draft/verify/correct
#    graph in orchestrator.py.
#
# 2. analyzer report schemas (ObligationComparison, ComparisonReport,
#    PolicyCoverageItem, PolicyMappingReport, GapItem, GapAnalysisReport) —
#    used by analyzer.py's three specialised workflows. these are the shapes
#    the django apps consume.

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# langgraph orchestrator schemas

class Citation(BaseModel):
    chunk_id:        str = Field(default="", description="unique identifier from retrieval layer")
    jurisdiction:    str = Field(default="")
    regulation_name: str = Field(default="")
    article_ref:     Optional[str] = None
    # exact_quote should be a verbatim 10+-char substring of the cited chunk,
    # but we accept empty here so the parser still succeeds when the model
    # forgets — verify_grounding catches it and triggers correction.
    exact_quote:     str = Field(default="", description="verbatim text from source")
    page_hint:       Optional[str] = None

    @field_validator("exact_quote")
    @classmethod
    def strip_and_validate(cls, v):
        return " ".join((v or "").split())


class ReasoningStep(BaseModel):
    action:      Literal["retrieve", "compare", "extract", "verify", "synthesize", "fallback"]
    description: str
    inputs:      dict = Field(default_factory=dict)
    outputs:     dict = Field(default_factory=dict)
    timestamp:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReasonedAnswer(BaseModel):
    summary:        str = Field(description="concise, jurisdiction-aware answer")
    citations:      list[Citation] = Field(default_factory=list)
    confidence:     float = Field(ge=0, le=1)
    reasoning_trace: list[ReasoningStep] = Field(default_factory=list)
    route_used:     str
    warnings:       list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_grounding(self):
        if self.confidence < 0.5 and not self.citations:
            # not an error — low-confidence-no-citations is a valid fallback
            # state, just mark it explicitly
            self.warnings.append("low confidence with no citations")
        if self.confidence >= 0.8 and len(self.citations) == 0:
            self.warnings.append("high confidence without citations — review grounding")
        return self


class SearchRequest(BaseModel):
    query:             str = Field(min_length=3, max_length=500)
    jurisdiction:      Optional[str] = None
    jurisdictions:     Optional[list[str]] = None
    doc_type:          Optional[str] = None
    doc_title:         Optional[str] = None
    route_hint:        Optional[Literal["comparative", "compliance", "extraction", "general"]] = None
    require_citations: bool = True
    stream:            bool = False


class StreamingChunk(BaseModel):
    token:           str
    citation_hint:   Optional[str] = None
    confidence_delta: Optional[float] = None
    is_final:        bool = False


# analyzer report schemas
# the three specialised workflows in analyzer.py produce these. fields default
# to safe values so a partially-correct llm output still parses; analyzer
# stamps the input fields (query, jurisdiction etc.) on after the chain runs.

_DISCLAIMER = (
    "AI-assisted analytical output. Not legal advice. Verify against primary "
    "sources and consult counsel before acting on these findings."
)


class ObligationComparison(BaseModel):
    """one row in a regulation-vs-regulation comparison report.

    citation fields come in pairs:
      - reg_a_citation / reg_b_citation     : the citation label (e.g. "PDPA Order 43 — Article 4")
      - reg_a_chunk_id / reg_b_chunk_id     : the chunk node_id (for click-through to source)
      - reg_a_evidence / reg_b_evidence     : the verbatim quote (10-200 char substring of the chunk)
    citation_verified is True only when chunk_id + evidence both check out.
    """
    topic:                 str
    source_chunk_a:        Optional[int] = None
    source_chunk_b:        Optional[int] = None
    # citation labels (the [Chunk N] CITATION: header text)
    reg_a_citation:        str = Field(default="")
    reg_b_citation:        str = Field(default="")
    # chunk ids — populated by the verifier post-draft so the UI can deep-link
    reg_a_chunk_id:        str = Field(default="")
    reg_b_chunk_id:        str = Field(default="")
    # doc_title — which file the viewer should open (for highlighting)
    reg_a_doc_title:       str = Field(default="")
    reg_b_doc_title:       str = Field(default="")
    # verbatim text excerpts
    reg_a_evidence:        str = Field(default="")
    reg_b_evidence:        str = Field(default="")
    equivalence:           str = Field(default="Different")
    similarity_score:      int = Field(default=0,  ge=0, le=100)
    confidence_score:      int = Field(default=70, ge=0, le=100)
    reg_a_requirement:     str = Field(default="")
    reg_b_requirement:     str = Field(default="")
    key_difference:        str = Field(default="")
    # Strictness is split into three orthogonal axes — the previous single
    # `stricter_jurisdiction` field collapsed all of these into one verdict
    # which led the LLM into absolute-language judgements. Each axis accepts
    # 'A', 'B', 'Equivalent', or 'Not Assessable'.
    procedural_stricter:   str = Field(default="Not Assessable")
    substantive_stricter:  str = Field(default="Not Assessable")
    enforcement_stricter:  str = Field(default="Not Assessable")
    # Roll-up label kept for legacy templates / serializers / arc viz. The
    # prompt populates it from the three axes (majority vote, ties = 'Neither').
    stricter_jurisdiction: str = Field(default="Neither")
    notes:                 str = Field(default="")
    citation_verified:     bool = Field(default=False)
    # NLI hallucination risk for the AI's prose summary on this row.
    # 0.0 = fully entailed by the cited chunk, 1.0 = unsupported / contradicted.
    # populated by the verifier post-draft.
    hallucination_risk:    float = Field(default=0.0, ge=0.0, le=1.0)


class ComparisonReport(BaseModel):
    obligations:  list[ObligationComparison] = Field(default_factory=list)
    summary:      str = Field(default="")
    query:        str | list[str] = Field(default="")
    regulation_a: str = Field(default="")
    regulation_b: str = Field(default="")
    disclaimer:   str = Field(default=_DISCLAIMER)


class PolicyCoverageItem(BaseModel):
    """one row in a policy-coverage report.

    citations on both sides:
      - regulation: regulation_citation (label) + regulation_chunk_id + regulation_evidence
      - policy:     policy_section (label) + policy_chunk_id + policy_evidence (already 'policy_excerpt')
    citation_verified is True only when the regulation-side citation grounds.
    """
    regulatory_obligation:  str
    regulation_citation:    str = Field(default="")
    regulation_chunk_id:    str = Field(default="")
    regulation_doc_title:   str = Field(default="")
    regulation_evidence:    str = Field(default="")
    policy_section:         str = Field(default="None identified")
    policy_chunk_id:        str = Field(default="")
    policy_doc_title:       str = Field(default="")
    # policy_excerpt was already the verbatim quote; keep the name for compat.
    policy_excerpt:         str = Field(default="")
    coverage_status:        str = Field(default="Requires Review")
    gap_description:        str = Field(default="")
    remediation_suggestion: str = Field(default="")
    citation_verified:      bool  = Field(default=False)
    hallucination_risk:     float = Field(default=0.0, ge=0.0, le=1.0)
    # the taxonomy topic this row was routed under (auto-route only). Lets the
    # coverage rollup attribute each obligation to a topic without re-deriving.
    topic:                  str = Field(default="")


class SkippedTopic(BaseModel):
    """A topic the policy legislates on but no in-scope regulation addresses.

    Reported so the UI can show it as *skipped* — explicitly NOT a compliance
    gap. Conflating "no law covers this" with "the policy fails a law" is the
    single most damaging error this tool can make, so skipped topics are kept
    structurally separate from gaps rather than folded into the not-covered
    count."""
    topic:         str = Field(default="")
    label:         str = Field(default="")
    policy_chunks: int = Field(default=0)


class PolicyMappingReport(BaseModel):
    items:        list[PolicyCoverageItem] = Field(default_factory=list)
    summary:      str = Field(default="")
    # str | list[str] mirrors ComparisonReport.query — a list means the
    # caller asked for a full multi-topic coverage assessment rather than a
    # single-topic mapping.
    query:        str | list[str] = Field(default="")
    jurisdiction: str = Field(default="")
    # topics the policy covers but the in-scope regulations do not legislate
    # on — skipped, never counted as gaps.
    skipped_topics: list[SkippedTopic] = Field(default_factory=list)
    disclaimer:   str = Field(default=_DISCLAIMER)


class GapItem(BaseModel):
    """one row in a cross-jurisdictional gap analysis.

    citation fields:
      - regulatory_source (label) + regulatory_chunk_id + regulatory_evidence
      - internal_policy_reference (label) + policy_chunk_id + policy_evidence
    citation_verified is True only when the regulatory-side citation grounds.
    """
    gap_id:                    str = Field(default="GAP-000")
    jurisdiction:              str = Field(default="All")
    regulatory_source:         str = Field(default="")
    regulatory_chunk_id:       str = Field(default="")
    regulatory_doc_title:      str = Field(default="")
    regulatory_evidence:       str = Field(default="")
    obligation_summary:        str = Field(default="")
    internal_policy_reference: str = Field(default="None")
    policy_chunk_id:           str = Field(default="")
    policy_doc_title:          str = Field(default="")
    policy_evidence:           str = Field(default="")
    coverage_status:           str = Field(default="Requires Review")
    gap_description:           str = Field(default="")
    priority:                  str = Field(default="Medium")
    remediation_suggestion:    str = Field(default="")
    citation_verified:         bool  = Field(default=False)
    hallucination_risk:        float = Field(default=0.0, ge=0.0, le=1.0)


class GapAnalysisReport(BaseModel):
    gaps:          list[GapItem] = Field(default_factory=list)
    summary:       str = Field(default="")
    topic:         str = Field(default="")
    jurisdictions: list[str] = Field(default_factory=list)
    disclaimer:    str = Field(default=_DISCLAIMER)
