"""Small text helpers shared by the scraper and the API."""
from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])")


def summarize(text: str | None, max_chars: int = 220) -> str | None:
    """First sentence(s) of `text`, about 2-3 lines on a phone.

    Whole sentences are kept while they fit in `max_chars`; a single
    over-long first sentence is cut at a word boundary with an ellipsis.
    """
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    out = ""
    for sentence in _SENTENCE_END.split(text):
        candidate = f"{out} {sentence}".strip()
        if out and len(candidate) > max_chars:
            break
        out = candidate
        if len(out) >= max_chars:
            break
    if len(out) > max_chars:
        out = out[: max_chars - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out
