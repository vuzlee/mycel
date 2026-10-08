"""Check an answer's `[cN]` markers against the passages it was given. No model involved.

A marker survives when its label is one of the passages sent. Any other marker is removed.

An answer that opens by saying the documents do not cover the question cites nothing,
whatever markers it carries: a refusal listed under sources reads as an answer with
evidence. The prompt asks for this too; the model does not always follow it.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

_MARKER = re.compile(r"\s?\[(c\d+)\]", re.IGNORECASE)

#: The opening of a refusal: "The documents do not cover…", "The documents provided don't
#: cover…", "The documents cover X, not Y, so they don't cover this". Only the first
#: sentence is read, so an answer that says "don't cover" further on keeps its markers.
_DECLINE = re.compile(
    r"^\W*the (?:provided |uploaded )?documents\b[^.!?\n]*\b(?:do not|don't|does not|doesn't)"
    r" (?:cover|contain|mention|say|address|include)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Checked:
    answer: str
    cited: list[str]
    #: Markers naming a passage that was not sent: invented. Not the ones a refusal loses.
    dropped: list[str]
    declined: bool = False


def declines(text: str) -> bool:
    """Whether the answer opens by saying the documents do not cover the question."""
    return bool(_DECLINE.search(text))


def check(text: str, labels: Collection[str]) -> Checked:
    """Keep markers whose label was sent, strip the rest. `cited` follows passage order."""
    if declines(text):
        return Checked(answer=_MARKER.sub("", text).strip(), cited=[], dropped=[], declined=True)
    dropped: list[str] = []

    def keep_or_drop(match: re.Match[str]) -> str:
        label = match.group(1).lower()
        if label in labels:
            return match.group(0).lower()
        dropped.append(label)
        return ""

    cleaned = _MARKER.sub(keep_or_drop, text).strip()
    cited = [label for label in labels if f"[{label}]" in cleaned]
    return Checked(answer=cleaned, cited=cited, dropped=sorted(set(dropped)))
