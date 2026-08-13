"""Multi-topic classification of a single requirement.

The model is asked which official topics genuinely apply — plural — and its
answer is then run through `taxonomy.resolve_concept`, which is the only thing
entitled to say what an official topic is. This module never decides that
itself, and never touches TAXONOMY.

Two things it deliberately does NOT do:

  - force a topic. An empty answer is correct for a definitions clause, and a
    low-confidence guess is worse than nothing because it looks like a finding.
  - invent a topic. A concept the taxonomy does not cover comes back as an
    unresolved CONCEPT for a human to review later, not as a new tag.

Separate from extraction by construction: this reads a stored Requirement and
returns proposed assignments. It cannot delete, rewrite, or invalidate the
requirement, so a classification failure costs a classification and nothing
else — the legal text extracted from the regulation is untouched either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import taxonomy
from .taxonomy import ConceptResolution, resolve_concept, resolve_concepts

logger = logging.getLogger(__name__)

MODEL = "qwen2.5:7b"
CLASSIFIER_VERSION = "qwen2.5:7b/reqtopic-v1"
PROMPT_VERSION = "requirement_classifier.yaml/v1"

# A cap on MODEL OUTPUT, not on the data model. The database imposes no limit
# on how many topics a requirement may carry — the schema is multi-topic by
# design. This exists only to stop a confused model returning all twelve, which
# is never a real classification. Generous on purpose: three or four genuine
# topics is plausible, and clipping those would reintroduce the single-label
# assumption this whole phase exists to remove.
MAX_TOPICS = 8

# Same floor as reasoning.classifier and taxonomy.MIN_CONCEPT_CONFIDENCE.
MIN_CONFIDENCE = taxonomy.MIN_CONCEPT_CONFIDENCE


@dataclass
class ClassifiedConcept:
    """One resolved concept, with the model's own words kept alongside it."""
    resolution: ConceptResolution
    evidence:   str = ""
    # Only populated for a new-topic candidate.
    reason:     str = ""
    why_insufficient: str = ""
    is_candidate: bool = False

    @property
    def model_concept(self) -> str:
        return self.resolution.concept


@dataclass
class RequirementClassification:
    """Everything one classification pass produced.

    `ok` is False ONLY on a technical failure (model unreachable, unparseable
    reply). A model that cleanly answered "no topics apply" is a SUCCESS with
    an empty list — conflating the two would make a broken Ollama look like a
    corpus of untopiced requirements.
    """
    concepts:  list = field(default_factory=list)   # list[ClassifiedConcept]
    ok:        bool = True
    error:     str = ""
    model_version:    str = CLASSIFIER_VERSION
    taxonomy_version: str = ""

    def __post_init__(self):
        if not self.taxonomy_version:
            self.taxonomy_version = taxonomy.TAXONOMY_VERSION

    @property
    def matched(self) -> list:
        return [c for c in self.concepts if c.resolution.is_matched]

    @property
    def unresolved(self) -> list:
        return [c for c in self.concepts if c.resolution.is_unresolved]

    @property
    def unclassified(self) -> list:
        return [c for c in self.concepts
                if c.resolution.status == taxonomy.UNCLASSIFIED]


def _as_list(value) -> list:
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def _confidence_of(item: dict) -> float | None:
    """The model's stated confidence, or None if it did not state one.

    None is preserved rather than defaulted: inventing a confidence the model
    never gave would fabricate the very number the audit trail exists to
    record. A concept with no confidence is treated as unusable.
    """
    raw = item.get("confidence")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, val))


def build_prompt(requirement, *, max_topics: int = MAX_TOPICS) -> str:
    from .prompts.registry import load_prompt
    prompt = load_prompt("requirement_classifier.yaml")
    return prompt.render(
        requirement_text = (getattr(requirement, "text", "") or "")[:2000],
        source_quote     = (getattr(requirement, "source_quote", "") or "")[:1500],
        article_ref      = getattr(requirement, "article_ref", "") or "",
        regulation_name  = getattr(getattr(requirement, "regulation", None),
                                   "name", "") or "",
        taxonomy_listing = taxonomy.render_for_prompt(),
        max_topics       = max_topics,
    )


def classify_requirement(
    requirement,
    *,
    chat = None,
    embed_fn = None,
    max_topics: int = MAX_TOPICS,
    model: str = MODEL,
) -> RequirementClassification:
    """Propose topic assignments for one requirement. Never raises.

    `chat` is callable(prompt, model) -> dict, injectable so the whole path is
    testable without Ollama. `embed_fn` enables resolve_concept's semantic
    step; omitted, resolution stays exact/alias/normalized only.

    Returns a RequirementClassification. On technical failure it comes back
    with ok=False and NO concepts — never a partial or invented assignment,
    because a half-classified requirement is indistinguishable from a
    genuinely sparse one.
    """
    text = (getattr(requirement, "text", "") or "").strip()
    if not text:
        return RequirementClassification(
            ok=False, error="requirement has no text to classify")

    if chat is None:
        from .doc_intel import _chat_json
        chat = _chat_json

    try:
        data = chat(build_prompt(requirement, max_topics=max_topics), model)
    except Exception as exc:                       # network, timeout, anything
        logger.warning("classify_requirement: model call failed: %s", exc)
        return RequirementClassification(
            ok=False, error=f"model call failed: {type(exc).__name__}")

    if not isinstance(data, dict):
        return RequirementClassification(ok=False, error="non-object reply")
    if not data:
        # _chat_json returns {} for every failure mode it swallows.
        return RequirementClassification(ok=False, error="empty reply")
    if "topics" not in data and "new_topic_candidates" not in data:
        return RequirementClassification(
            ok=False, error="reply carried neither topics nor candidates")

    concepts: list[ClassifiedConcept] = []

    # ── official-topic assignments ──
    # Routed through resolve_concepts() so the bare-topic/subcategory
    # absorption rule established in Phase 0 applies here unchanged, rather
    # than being reimplemented (and drifting).
    items, meta = [], []
    for raw in _as_list(data.get("topics"))[:max_topics]:
        if not isinstance(raw, dict):
            continue
        concept = str(raw.get("concept") or raw.get("topic") or "").strip()
        if not concept:
            continue
        conf = _confidence_of(raw)
        items.append({
            "concept":     concept,
            "subcategory": str(raw.get("subcategory") or "").strip(),
            # A concept with no stated confidence is treated as below the
            # floor, so resolve_concept files it as unclassified rather than
            # letting an unstated number become an official assignment.
            "confidence":  0.0 if conf is None else conf,
        })
        meta.append(str(raw.get("evidence") or "").strip())

    for resolution, evidence in zip(resolve_concepts(items, embed_fn=embed_fn), meta):
        concepts.append(ClassifiedConcept(resolution=resolution, evidence=evidence))

    # ── proposed new topics ──
    # Resolved too, and on purpose: a model proposing "storage limitation" as
    # NEW has simply not recognised the taxonomy's own "retention". Resolving
    # first means such a proposal becomes an ordinary matched topic instead of
    # taxonomy spam, which is the difference between an expandable taxonomy and
    # an uncontrolled one.
    seen_leaves = {c.resolution.leaf for c in concepts if c.resolution.is_matched}
    for raw in _as_list(data.get("new_topic_candidates"))[:max_topics]:
        if not isinstance(raw, dict):
            continue
        concept = str(raw.get("concept") or "").strip()
        if not concept:
            continue
        conf = _confidence_of(raw)
        resolution = resolve_concept(
            concept,
            confidence = 0.0 if conf is None else conf,
            embed_fn   = embed_fn,
        )
        if resolution.is_matched and resolution.leaf in seen_leaves:
            continue                       # already assigned as a real topic
        if resolution.is_matched:
            seen_leaves.add(resolution.leaf)
        concepts.append(ClassifiedConcept(
            resolution       = resolution,
            evidence         = str(raw.get("evidence") or "").strip(),
            reason           = str(raw.get("reason") or "").strip(),
            why_insufficient = str(
                raw.get("why_existing_topics_are_insufficient") or "").strip(),
            is_candidate     = True,
        ))

    return RequirementClassification(concepts=concepts, ok=True)
