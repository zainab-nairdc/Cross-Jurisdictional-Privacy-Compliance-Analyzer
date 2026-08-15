# generator.py
# the llm-call layer. takes a query + retrieved chunks + a prompt template,
# returns a structured pydantic object.
#
# provider: LOCAL ONLY. CJPCA runs fully on-premise for the bank — regulation
# and policy text must never leave the environment — so the sole LLM provider
# is local Ollama (qwen2.5:7b by default, cfg.llm.fallback_model). There is no
# cloud/OpenRouter path; any OPENROUTER_API_KEY in the env is ignored.
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


def _build_ollama_llm():
    """Build the local Ollama client. This is the ONLY LLM provider.

    CJPCA runs fully on-premise: regulation and policy text must never leave
    the bank's environment, so there is no cloud/OpenRouter path by design.
    format='json' constrains output to a json object, which makes
    PydanticOutputParser robust on the local qwen2.5 model."""
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model           = cfg.llm.fallback_model,
        temperature     = cfg.llm.temperature,
        base_url        = cfg.llm.fallback_base_url,
        format          = "json",
        num_ctx         = cfg.llm.fallback_num_ctx,
        num_predict     = cfg.llm.max_tokens,
        # The timeout MUST go through client_kwargs. ChatOllama is a pydantic
        # model with extra='ignore', so an unknown kwarg (this used to be
        # `request_timeout=`) is silently DISCARDED — no error, no warning, and
        # no timeout. A generation could then run unbounded: on CPU-only
        # inference a num_predict=8000 call takes tens of minutes, which is
        # what made comparison runs look hung with no way to interrupt them.
        # client_kwargs is forwarded to the underlying ollama.Client, where
        # `timeout` is a real parameter.
        client_kwargs   = {"timeout": cfg.llm.timeout_sec},
        # Keep the model resident for 30 min between calls. Without this,
        # Ollama unloads after ~5 min idle and the next request pays a
        # 10-15s reload that can blow the request timeout mid-demo.
        keep_alive      = "30m",
    )


# Back-compat alias — some call sites import _build_ollama_fallback.
_build_ollama_fallback = _build_ollama_llm


def _build_llm():
    """CJPCA is fully local. Ollama is the sole provider — no OpenRouter, no
    cloud fallback, so no document text can leave the environment. Any
    OPENROUTER_API_KEY in the environment is deliberately ignored."""
    return _build_ollama_llm()


def _get_llm():
    """Build the local Ollama client fresh on every call — deliberately NOT
    cached.

    A cached ChatOllama binds its async httpx client to the FIRST asyncio event
    loop it runs in. Each top-level LLM invocation here runs under its own
    ``asyncio.run(...)`` (a comparison, then a mapping job, are separate loops),
    so a process-wide singleton means the second flow reuses a client bound to
    the first flow's now-closed loop and crashes with "Event loop is closed".
    That's exactly what broke policy mapping when it ran after a comparison in
    the same worker process.

    Construction is network-free and microsecond-cheap (it just wires up a
    langchain Runnable), so rebuilding per call is the simplest correct fix and
    has no meaningful cost."""
    return _build_llm()


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
