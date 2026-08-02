"""Minimal, safe markdown → HTML for Copilot answers.

No third-party dependency. The input is HTML-escaped FIRST, then a small set of
inline/block markdown constructs the model actually emits (bold, italic, inline
code, bullet + numbered lists, paragraphs) are turned into tags. Because we only
ever insert our own fixed tags around already-escaped text, the output is safe
to mark_safe — user/model content can never inject HTML.
"""
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE = re.compile(r"`([^`]+?)`")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _inline(text: str) -> str:
    text = _CODE.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


@register.filter(name="copilot_md")
def copilot_md(value):
    if not value:
        return ""
    lines = escape(str(value)).split("\n")
    html, list_buf, list_type = [], [], None

    def flush_list():
        nonlocal list_buf, list_type
        if list_buf:
            tag = "ol" if list_type == "ol" else "ul"
            html.append(f"<{tag} class='cp-md-list'>" + "".join(list_buf) + f"</{tag}>")
            list_buf, list_type = [], None

    para: list[str] = []

    def flush_para():
        if para:
            html.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    for ln in lines:
        mb, mn = _BULLET.match(ln), _NUMBERED.match(ln)
        if mb:
            flush_para()
            if list_type not in (None, "ul"):
                flush_list()
            list_type = "ul"
            list_buf.append("<li>" + _inline(mb.group(1)) + "</li>")
        elif mn:
            flush_para()
            if list_type not in (None, "ol"):
                flush_list()
            list_type = "ol"
            list_buf.append("<li>" + _inline(mn.group(1)) + "</li>")
        elif ln.strip() == "":
            flush_para()
            flush_list()
        else:
            flush_list()
            para.append(ln.strip())

    flush_para()
    flush_list()
    return mark_safe("".join(html))
