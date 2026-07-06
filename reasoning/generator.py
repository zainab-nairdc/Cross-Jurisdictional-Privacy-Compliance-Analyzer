# generator.py
# the llm-call layer. takes a query + retrieved chunks + a prompt template,
# returns a structured pydantic object.
#
# providers:
#   - primary:  openrouter (openai-compatible api at openrouter.ai) —
#               claude haiku 4.5 by default, swappable via REASON_LLM__MODEL.
#   - fallback: local ollama (llama3.2:1b by default). engages automatically
#               when openrouter raises any exception (network, auth, rate
#               limit, timeout, parse error). disable with
#               REASON_LLM__FALLBACK_ENABLED=false.
#
# parsing: PydanticOutputParser wrapped in OutputFixingParser. on a
# malformed response the wrapper makes the model fix its own json
# (capped at cfg.llm.retry_attempts) before giving up.

import os
import threading

# load .env at module import so OPENROUTER_API_KEY is available without
# forcing every caller to set it in their shell. .env is gitignored —
# secrets never get committed.
try:
    from dotenv import load_dotenv
    from pathlib import Path as _Path
    load_dotenv(_Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass    # python-dotenv is optional; if unavailable, fall back to real env

from langchain_classic.output_parsers import OutputFixingParser
from langchain_core.output_parsers    import PydanticOutputParser
from langchain_core.prompts           import PromptTemplate
from pydantic import BaseModel

from .config           import cfg
from .prompts.registry import load_prompt


_llm = None
_llm_lock = threading.Lock()


def _build_openrouter_llm():
    """build the primary openrouter-backed langchain client. openrouter is
    openai-compatible — same wire format, different base_url. one api key +
    one billing page gets you any model openrouter exposes (claude, gpt-4,
    llama, gemini, etc.) by changing cfg.llm.model.

    reads OPENROUTER_API_KEY from env."""
    from langchain_openai import ChatOpenAI  # lazy — only needed if a key is set
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. Get a key at "
            "https://openrouter.ai/keys and run:\n"
            "  $env:OPENROUTER_API_KEY = 'sk-or-...'"
        )
    return ChatOpenAI(
        model       = cfg.llm.model,
        temperature = cfg.llm.temperature,
        max_tokens  = cfg.llm.max_tokens,
        timeout     = cfg.llm.timeout_sec,
        api_key     = api_key,
        base_url    = "https://openrouter.ai/api/v1",
        # response_format constrains the model to return a json object.
        # most modern openrouter providers support this; ones that
        # don't ignore it gracefully. without this, some models
        # routinely return prose or empty strings that crash the parser.
        response_format = {"type": "json_object"},
        # openrouter wants attribution headers so site owners can see
        # which app is calling them. nice-to-have, not required.
        default_headers = {
            "HTTP-Referer": "https://github.com/cjpca",
            "X-Title":      "Cross-Jurisdictional Privacy Compliance Analyzer",
        },
    )


def _build_ollama_fallback():
    """build the local-ollama fallback. format='json' constrains output to
    a json object, which makes PydanticOutputParser more robust on small
    models like llama3.2:1b."""
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model           = cfg.llm.fallback_model,
        temperature     = cfg.llm.temperature,
        base_url        = cfg.llm.fallback_base_url,
        format          = "json",
        num_ctx         = cfg.llm.fallback_num_ctx,
        request_timeout = cfg.llm.timeout_sec,
        num_predict     = cfg.llm.max_tokens,
    )


def _build_llm():
    """PoC: local Ollama is the PRIMARY provider (no API key required).

    If an OPENROUTER_API_KEY happens to be set in the environment, OpenRouter
    is added as a *fallback* (the reverse of the original design) so the app
    still degrades gracefully. With no key set — the default here — the app
    runs fully local against Ollama.
    """
    primary = _build_ollama_fallback()  # local Ollama is now the primary

    if not os.environ.get("OPENROUTER_API_KEY"):
        return primary

    try:
        cloud_fallback = _build_openrouter_llm()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "OpenRouter fallback unavailable, running Ollama-only: %s", e
        )
        return primary

    return primary.with_fallbacks([cloud_fallback])


def _get_llm():
    """Thread-safe lazy singleton. Build once, reuse forever. callers don't
    see the provider chain underneath — they just get a langchain Runnable.
    after this returns the chain is: openrouter (claude haiku 4.5) →
    local ollama (llama3.2:1b) on any primary error.

    Double-checked locking so the fast path after init is lock-free, but
    concurrent first-callers don't both build an OpenRouter+Ollama chain."""
    global _llm
    if _llm is None:
        with _llm_lock:
            if _llm is None:
                _llm = _build_llm()
    return _llm


def _format_chunks(chunks: list[dict], max_chars: int = 6000) -> str:
    """compact context block. each chunk header carries node_id + doc_title +
    article_ref so the llm can identify the exact source and won't conflate
    one document's preamble with another document's topic."""
    out: list[str] = []
    total = 0
    for i, c in enumerate(chunks, 1):
        meta = c.get("metadata") or {}
        nid  = c.get("node_id") or meta.get("node_id", "?")
        # Prefer the chunk's own keys, fall back to metadata.
        doc_title    = c.get("doc_title")    or meta.get("doc_title")    or ""
        reg_name     = c.get("regulation_name") or meta.get("regulation_name") or doc_title
        article_ref  = c.get("article_ref")  or meta.get("article_ref")  or ""
        jurisdiction = c.get("jurisdiction") or meta.get("jurisdiction") or ""
        content      = c.get("content", "").strip()
        snippet      = content[:600]
        header_bits  = [f"[Chunk {i}] (node_id={nid})"]
        if reg_name:
            header_bits.append(f"DOC: {reg_name}")
        if article_ref:
            header_bits.append(f"ARTICLE: {article_ref}")
        if jurisdiction:
            header_bits.append(f"JURISDICTION: {jurisdiction}")
        header = " | ".join(header_bits)
        block  = f"{header}\n{snippet}"
        if total + len(block) > max_chars:
            out.append("...[truncated]")
            break
        out.append(block)
        total += len(block)
    return "\n---\n".join(out)


async def generate_structured(
    query:              str,
    chunks:             list[dict],
    route:              str,
    prompt_key:         str,
    response_model:     type[BaseModel],
    correction_context: str | None       = None,
    previous_draft:     BaseModel | None = None,
) -> BaseModel:
    """run one llm pass and parse the output into `response_model`.

    correction_context + previous_draft are filled in when this is called
    from orchestrator.correct_node — the prompt includes the failed attempt
    and the validation error so the llm can fix its own mistake."""
    prompt_template = load_prompt(prompt_key)
    prompt_text = prompt_template.format(
        query             = query,
        context           = _format_chunks(chunks),
        route             = route,
        correction_hint   = correction_context or "",
        previous_answer   = previous_draft.model_dump_json() if previous_draft else "",
    )

    parser = OutputFixingParser.from_llm(
        parser     = PydanticOutputParser(pydantic_object=response_model),
        llm        = _get_llm(),
        max_retries = cfg.llm.retry_attempts,
    )

    chain = PromptTemplate.from_template("{prompt}") | _get_llm() | parser
    return await chain.ainvoke({"prompt": prompt_text})
