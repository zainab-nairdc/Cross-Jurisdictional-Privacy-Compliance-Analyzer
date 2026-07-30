"""Query the Arabic collection: English question in, English answer out.

The retrieved context is Arabic — the LLM (qwen2.5:7b, strong Arabic reader)
reads the Arabic law and answers in English, citing only the article numbers
present in the retrieved context. This is the "Arabic in, English out" pattern:
the Arabic stays the authoritative source; English is generated at answer time.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import OLLAMA_URL

import ollama

from .embed import embed_query
from . import store

ANSWER_MODEL = "qwen2.5:7b"


def retrieve(question: str, k: int = 5, source: str | None = None) -> list[dict]:
    """Embed the (English or Arabic) query with bge-m3 and pull top-k Arabic
    chunks. Cross-lingual: an English query matches Arabic provisions."""
    return store.query(embed_query(question), k=k, source=source)


def _relative_filter(hits: list[dict], margin: float = 0.15) -> list[dict]:
    """Keep only hits close to the top score, so a weak off-topic chunk (e.g. a
    stray penalties hit on a transfer question) is dropped. Always keep >=1."""
    if not hits:
        return hits
    top = hits[0]["score"]
    kept = [h for h in hits if h["score"] >= top - margin]
    return kept or hits[:1]


def _citation(h: dict) -> str:
    art = h.get("article_number")
    if h.get("chunk_type") == "definition" and h.get("term"):
        return f"Article {art} (Definitions) — term: {h['term']}"
    title = h.get("article_title") or ""
    return f"Article {art}{f' — {title}' if title else ''}"


def _build_context(hits: list[dict]) -> str:
    return "\n\n".join(f"[{_citation(h)}]\n{h['text']}" for h in hits)


def _build_prompt(question: str, context: str, law_name: str) -> str:
    law = law_name or "the applicable personal-data-protection law"
    return f"""You are a precise legal assistant for {law}.
Answer in ENGLISH using ONLY the Arabic legal context below.

RULES - follow exactly:
1. Ground EVERY statement in a specific article. Cite the exact Article number
   shown in [brackets]. Never invent article numbers, amounts, dates, or lists.
2. Amounts in these laws are written as digits AND spelled out in words
   (e.g. "مليون" = one million, "ملايين" = millions, "خمسة ملايين" = five
   million). The WORDS are authoritative: if the parenthetical digits look
   truncated or disagree with the words, follow the WORDS. Example: "(1000)
   مليون ريال" means one million riyals (1,000,000) - the word "مليون" wins over
   the truncated "(1000)". State the amount in full, e.g. "1,000,000".
3. Keep each article's rule SEPARATE. When several articles specify penalties,
   state each one on its own line as:
   "Article N: <amount> for violating <the exact articles/acts that article lists>."
   NEVER merge, swap, or share an amount between articles.
4. If the context does not answer the question, say so plainly. Do not guess.
5. Be concise and faithful to the wording; do not add interpretation the text
   does not state.

Question:
{question}

Context (each chunk is labelled with its Article number):
{context}

Answer (in English - every claim tied to its exact article, numbers copied verbatim):"""


def answer(question: str, k: int = 5, source: str | None = None,
           model: str = ANSWER_MODEL) -> dict:
    """Retrieve + generate. Returns the English answer, the citations used, and
    the raw hits so a caller/UI can show the Arabic source alongside."""
    hits = _relative_filter(retrieve(question, k=k, source=source))
    if not hits:
        return {"answer": "No relevant Arabic provisions were found for this question.",
                "citations": [], "hits": []}

    law_name = hits[0].get("law_name") or ""
    prompt = _build_prompt(question, _build_context(hits), law_name)
    resp = ollama.Client(host=OLLAMA_URL).chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},
    )
    # The model first writes literal translations (its reasoning scratchpad),
    # then the final answer after an ANSWER: marker. Show only the answer; the
    # translation step is what fixes hard clauses (e.g. Arabic double-negatives)
    # by letting the model reason in English rather than parse Arabic directly.
    full = resp["message"]["content"]
    if "ANSWER:" in full:
        final = full.split("ANSWER:", 1)[1].strip()
    elif "ANSWER" in full:
        final = full.split("ANSWER", 1)[1].lstrip(":").strip()
    else:
        final = full.strip()

    citations = []
    for h in hits:
        art = h.get("article_number")
        citations.append(
            f"Art. {art}: {h['term']}" if h.get("chunk_type") == "definition" and h.get("term")
            else f"Art. {art}"
        )
    return {
        "answer": final,
        "citations": citations,
        "hits": hits,
    }
