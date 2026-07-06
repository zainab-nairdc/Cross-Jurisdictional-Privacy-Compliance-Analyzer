"""
concept_tags.py — Django template tag for Visual 8 server-side concept highlighting.

Usage in templates:
  {% load concept_tags %}
  {% highlight_concepts chunk concepts %}
"""
import re
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.comparison.concepts import CONCEPT_SEEDS, build_concept_pattern

register = template.Library()


@register.simple_tag
def highlight_concepts(text: str, concepts: list) -> str:
    """
    Wrap all concept synonym matches in colored <span class="concept-span"> tags.

    Uses a single-pass algorithm that collects all non-overlapping match positions
    across all concepts (first match wins on overlap), then builds the output string.
    """
    if not text:
        return mark_safe("")

    # Collect all matches: (start, end, concept_dict, matched_text)
    all_matches = []
    for concept in concepts:
        cid = concept.get("id", "")
        if cid not in CONCEPT_SEEDS:
            continue
        try:
            pattern = build_concept_pattern(cid)
        except Exception:
            continue
        for m in pattern.finditer(text):
            all_matches.append((m.start(), m.end(), concept, m.group(0)))

    # Sort by start position; on ties prefer longer match
    all_matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    # Remove overlapping matches (first / longest at each position wins)
    clean: list = []
    last_end = 0
    for start, end, concept, matched in all_matches:
        if start >= last_end:
            clean.append((start, end, concept, matched))
            last_end = end

    # Build output
    parts: list = []
    prev = 0
    for start, end, concept, matched in clean:
        parts.append(escape(text[prev:start]))
        cl  = concept["color_light"]
        ct  = concept["color_text"]
        cid = concept["id"]
        parts.append(
            f'<span class="concept-span" data-concept="{cid}" '
            f'style="background:{cl};color:{ct};padding:0 3px;border-radius:2px;">'
            f'{escape(matched)}</span>'
        )
        prev = end
    parts.append(escape(text[prev:]))

    return mark_safe("".join(parts))
