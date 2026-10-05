"""Check an answer's citations against the passages it was given. No model involved.

A citation survives when its label is one of the passages sent and its quote occurs in
that passage. Markers in the text with no surviving citation are removed.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from mycel.agents.schemas import NotebookAnswer

_MARKER = re.compile(r"\s?\[(c\d+)\]")


@dataclass(frozen=True, slots=True)
class Checked:
    answer: str
    cited: list[str]
    dropped: list[str]
    quotes: dict[str, str]


_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def _normalise(text: str) -> str:
    text = _LINK.sub(r"\1", text)
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"[*_`#|]", " ", text)
    return " ".join(text.lower().split())


def check(answer: NotebookAnswer, passages: Mapping[str, str]) -> Checked:
    """Keep the citations that hold, strip markers for the ones that do not."""
    valid: dict[str, str] = {}
    for citation in answer.citations:
        label = citation.id.strip().strip("[]").lower()
        text = passages.get(label)
        if text is not None and _normalise(citation.quote) in _normalise(text):
            valid.setdefault(label, citation.quote)

    dropped: list[str] = []

    def keep_or_drop(match: re.Match[str]) -> str:
        label = match.group(1).lower()
        if label in valid:
            return match.group(0)
        dropped.append(label)
        return ""

    cleaned = _MARKER.sub(keep_or_drop, answer.answer)
    cited = [label for label in passages if f"[{label}]" in cleaned]
    return Checked(answer=cleaned.strip(), cited=cited, dropped=sorted(set(dropped)), quotes=valid)
