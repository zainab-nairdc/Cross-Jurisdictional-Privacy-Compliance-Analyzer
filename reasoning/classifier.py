"""Per-chunk taxonomy classifier.

Wraps a single LLM call that tags a chunk with one (topic, subcategory)
pair from `reasoning.taxonomy`. Used at ingest time and by the
`classify_chunks` management command for backfilling already-indexed
chunks.

The classifier is deliberately schema-strict: outputs are validated
against the taxonomy module, and any tag not in the controlled vocabulary
is rejected and replaced with "unclassified". Better to under-tag than
to pollute the index with invented tags.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel, Field

from langchain_classic.output_parsers import OutputFixingParser
from langchain_core.output_parsers    import PydanticOutputParser

from . import taxonomy
from .config           import cfg
from .generator        import _get_llm
from .prompts.registry import load_prompt

log = logging.getLogger(__name__)


class ChunkTag(BaseModel):
    """LLM output for a single chunk classification."""
    topic:       str   = Field(default=taxonomy.UNCLASSIFIED)
    subcategory: str   = Field(default="")
    confidence:  float = Field(default=0.0, ge=0.0, le=1.0)
    reason:      str   = Field(default="")


def _normalise(tag: ChunkTag) -> ChunkTag:
    """Coerce LLM output into a guaranteed-valid (topic, subcategory) pair.

    Catches:
      - inventing topics that aren't in the taxonomy
      - inventing subcategories that don't sit under the chosen topic
      - returning an empty topic
      - "unclassified" with a non-empty subcategory
    Anything that fails coercion becomes (UNCLASSIFIED, '') so the index stays clean.
    """
    topic = (tag.topic or "").strip().lower()
    sub   = (tag.subcategory or "").strip().lower()

    # The LLM occasionally returns subcategory in `topic/sub` form (e.g.
    # "lawful_basis/consent") even though the prompt asks for the bare tag.
    # Split it out so we don't throw away an otherwise-valid classification.
    if "/" in sub:
        sub_topic, _, sub_only = sub.partition("/")
        if sub_topic == topic or sub_topic == "":
            sub = sub_only
    if "/" in topic:
        # Same defensive parse on the topic side.
        topic = topic.split("/", 1)[0]

    if topic == taxonomy.UNCLASSIFIED:
        return ChunkTag(topic=taxonomy.UNCLASSIFIED, subcategory="",
                        confidence=tag.confidence, reason=tag.reason)

    if not taxonomy.is_valid(topic):
        log.warning("classifier returned unknown topic %r — falling back to unclassified", topic)
        return ChunkTag(topic=taxonomy.UNCLASSIFIED, subcategory="",
                        confidence=0.0, reason=f"rejected unknown topic {topic!r}")

    if sub and not taxonomy.is_valid(topic, sub):
        log.warning("classifier returned topic=%s with unknown subcategory=%r — keeping topic, dropping sub",
                    topic, sub)
        sub = ""

    # Confidence floor: below 0.3, the model is essentially guessing.
    if tag.confidence < 0.3:
        return ChunkTag(topic=taxonomy.UNCLASSIFIED, subcategory="",
                        confidence=tag.confidence,
                        reason=f"low-confidence guess ({tag.topic}/{tag.subcategory}): {tag.reason}")

    return ChunkTag(topic=topic, subcategory=sub,
                    confidence=tag.confidence, reason=tag.reason)


async def classify_chunk_async(
    chunk_text:   str,
    doc_title:    str = "",
    jurisdiction: str = "",
) -> ChunkTag:
    """Classify one chunk. Async because the underlying LLM call is async.
    Always returns a ChunkTag — never raises (network/parse failures collapse
    to UNCLASSIFIED so the backfill loop can keep going)."""
    if not chunk_text or len(chunk_text.strip()) < 30:
        return ChunkTag(topic=taxonomy.UNCLASSIFIED, subcategory="",
                        confidence=0.0, reason="chunk too short to classify")

    prompt = load_prompt("chunk_classifier.yaml")
    text   = prompt.format(
        chunk_text       = chunk_text[:2000],   # cap to keep the prompt cheap
        doc_title        = doc_title or "",
        jurisdiction     = jurisdiction or "",
        taxonomy_listing = taxonomy.render_for_prompt(),
        guidance         = taxonomy.CLASSIFIER_GUIDANCE.strip(),
    )

    parser = OutputFixingParser.from_llm(
        parser      = PydanticOutputParser(pydantic_object=ChunkTag),
        llm         = _get_llm(),
        max_retries = cfg.llm.retry_attempts,
    )
    try:
        raw   = await _get_llm().ainvoke(text)
        body  = raw.content if hasattr(raw, "content") else str(raw)
        draft = parser.parse(body)
    except Exception as e:
        log.warning("classify_chunk_async failed: %s", e)
        return ChunkTag(topic=taxonomy.UNCLASSIFIED, subcategory="",
                        confidence=0.0, reason=f"classifier error: {e}")

    return _normalise(draft)


def classify_chunk(
    chunk_text:   str,
    doc_title:    str = "",
    jurisdiction: str = "",
) -> ChunkTag:
    """Sync wrapper around classify_chunk_async.

    Use this from Django views, management commands, and ingestion hooks —
    anywhere there is NO event loop already running in the current thread.
    If you're inside an async function, await classify_chunk_async() directly.

    Implementation: probe for a running loop with the modern API. If none,
    asyncio.run() handles its own loop lifecycle. If there is one, we run
    on a worker thread because nesting asyncio.run inside a running loop
    would raise, and the old run_coroutine_threadsafe(coro, current_loop)
    pattern silently deadlocks when current_loop is on the same thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop running in this thread — the normal case.
        return asyncio.run(classify_chunk_async(chunk_text, doc_title, jurisdiction))

    # We're inside an event loop. Run on a worker thread with its own loop.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(
            asyncio.run,
            classify_chunk_async(chunk_text, doc_title, jurisdiction),
        )
        return fut.result()
