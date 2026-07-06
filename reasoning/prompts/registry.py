# registry.py
# prompt template loader. every prompt lives as a yaml file in this folder
# with a single 'template' field holding the text. load_prompt returns a
# str.format-compatible Template (jinja2) so callers can fill in placeholders
# like {query}, {context}, {route}, {correction_hint}, {previous_answer}.

import sys
from pathlib import Path

import yaml
from jinja2 import Template

# the project's reasoning/config.py is one level up.
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from reasoning.config import cfg


def load_prompt(prompt_key: str) -> Template:
    """load `<prompts_dir>/<prompt_key>` and return a jinja Template.
    callers can call .render(**fields) on it — same interface as a normal
    PromptTemplate-style format() call."""
    path = cfg.prompts_dir / prompt_key
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if "template" not in data:
        raise KeyError(f"prompt file {path} missing 'template' field")

    template = Template(data["template"])

    # patch in a .format(**kwargs) method so generator.py can call either
    # interface — keeps the old format(...) call sites working alongside
    # new render(...) ones.
    def _format(**kwargs) -> str:
        return template.render(**kwargs)
    template.format = _format

    return template
