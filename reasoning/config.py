# config.py
# settings for the reasoning layer. the langgraph orchestrator runs against
# openrouter (managed claude haiku 4.5 by default) with a local ollama
# model as the automatic fallback. override the primary model by setting
# REASON_LLM__MODEL=anthropic/claude-3-5-sonnet etc.

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    """openrouter-backed primary + local-ollama fallback. one managed
    provider keeps the call path simple and the citation quality high;
    the local fallback kicks in transparently when openrouter errors
    (api down, rate limit, auth, network, timeout) so the analyzer keeps
    working with no internet.

    swap the primary model by setting REASON_LLM__MODEL — openrouter
    accepts "vendor/model" identifiers (e.g. "anthropic/claude-haiku-4-5",
    "openai/gpt-4o-mini"). disable the fallback entirely by setting
    REASON_LLM__FALLBACK_ENABLED=false."""

    # claude-haiku-4-5 via openrouter: ~$0.05 for the 8-query eval, sub-5s
    # per query, near-perfect verbatim citation.
    model:          str = "anthropic/claude-haiku-4-5"
    temperature:    float = Field(default=0.1, ge=0, le=1)
    # 8000 covers the biggest output we ask for — a full ComparisonReport
    # with 6-10 obligations × ~500 tokens each + summary. only a ceiling;
    # no extra cost if the model doesn't use it.
    max_tokens:     int = 8000
    # Per-call ceiling. This value did NOT apply until the generator was fixed
    # to pass it via client_kwargs (it was handed to ChatOllama as an unknown
    # `request_timeout=` kwarg and silently dropped), so calls ran unbounded.
    #
    # 75s was tuned for GPU inference. On CPU-only Ollama a num_predict=8000
    # generation legitimately takes many minutes, and 75s would abort every
    # substantial call — so the default is a bound that prevents a hang without
    # failing honest slow work. Drop it back to ~75 on a GPU box, or override
    # per-environment with REASON_LLM__TIMEOUT_SEC.
    timeout_sec:    int = 600
    retry_attempts: int = 1

    # local fallback. kicks in automatically if the primary openrouter call
    # raises any exception (network, auth, rate limit, timeout, parse error).
    fallback_enabled:  bool = True
    # llama3.2:1b was too weak for the structured ComparisonReport prompt — it
    # echoed the schema's field descriptions verbatim instead of extracting.
    # qwen2.5:7b-instruct follows the structured-extraction prompt reliably and
    # fits an 8 GB GPU (Q4). Override with REASON_LLM__FALLBACK_MODEL if needed.
    # Must match an Ollama tag EXACTLY — Ollama does not resolve "7b-instruct"
    # to the "7b" tag, it 404s with "model not found", which surfaced as a
    # failed comparison run. `ollama list` is the source of truth.
    fallback_model:    str  = "qwen2.5:7b"
    fallback_base_url: str  = "http://localhost:11434"
    fallback_num_ctx:  int  = 8192

    @field_validator("temperature")
    @classmethod
    def enforce_low_temp_for_reasoning(cls, v):
        # reasoning needs determinism. cap at 0.3 even if a caller asks higher.
        return min(v, 0.3)


class RoutingConfig(BaseSettings):
    """which prompt template each query type uses."""
    routes: dict[str, dict] = {
        "comparative": {"prompt": "comparative.yaml", "parallel": True},
        "compliance":  {"prompt": "compliance.yaml", "strict_citations": True},
        "extraction":  {"prompt": "base.yaml",       "structured_only": True},
        "general":     {"prompt": "base.yaml"},
    }
    default_route:    str = "general"
    classifier_model: str = "BAAI/bge-small-en-v1.5"


class ValidationConfig(BaseSettings):
    """thresholds for the verify step. answers below these get sent to
    correct_node for a re-prompt.

    max_retries used to be 2 (3 LLM attempts total per topic). that was the
    cause of multi-minute hangs on the policy mapping screen: with
    timeout_sec=75 and llm.retry_attempts=1, the worst case was
    75 * (1+2) * (1+1) = 450s = 7.5 min PER TOPIC. in practice the LLM rarely
    produces a better answer on retry — re-prompting it with the same chunks
    just nudges it into the same shape. setting max_retries=0 keeps the draft
    on the first attempt, records the verify+hallucination scores on each row
    so the UI can flag unreliable ones, and caps wall time at 75s per topic.
    """
    min_confidence:        float = 0.6
    max_retries:           int   = 0
    require_citations:     bool  = True
    # nli model is heavy (~700mb). loaded lazily, only on first verify call.
    hallucination_model:   str   = "cross-encoder/nli-deberta-v3-base"
    jurisdiction_strict:   bool  = True


class CacheConfig(BaseSettings):
    enabled:    bool = False    # off by default — turn on once we trust the cache key
    ttl_sec:    int  = 3600
    key_prefix: str  = "reasoning:v1"


class ReasoningConfig(BaseSettings):
    llm:        LLMConfig        = LLMConfig()
    routing:    RoutingConfig    = RoutingConfig()
    validation: ValidationConfig = ValidationConfig()
    cache:      CacheConfig      = CacheConfig()

    project_root: Path = Path(__file__).resolve().parent.parent
    prompts_dir:  Path = project_root / "reasoning" / "prompts"

    class Config:
        env_prefix          = "REASON_"
        env_nested_delimiter = "__"


cfg = ReasoningConfig()
