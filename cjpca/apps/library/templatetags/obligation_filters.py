"""Template filter for highlighting obligation verbs inside snippets.

Used by `pages/obligations.html` to make the binding-verb visible inside
the chunk preview. Same word list the obligation register uses to
populate `r.verb` server-side.

Usage:
  {% load obligation_filters %}
  {{ r.snippet|highlight_obligation_verb|safe }}
"""
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe


register = template.Library()


# Same regex as ObligationRegisterView's filter. Keep these in sync.
_OBLIGATION_RE = re.compile(
    r'\b(shall not|may not|shall|must|mandatory|prohibited|required to|is required)\b',
    re.IGNORECASE,
)


@register.filter
def highlight_obligation_verb(text: str) -> str:
    """Wrap every obligation verb match in a <strong> tag with a navy
    underline so the analyst's eye lands on it instantly."""
    if not text:
        return ''
    escaped = escape(text)
    highlighted = _OBLIGATION_RE.sub(
        lambda m: f'<strong style="color:#002583;background:#FFB800;'
                  f'padding:0 3px;border-radius:2px;">{m.group(0)}</strong>',
        escaped,
    )
    return mark_safe(highlighted)
