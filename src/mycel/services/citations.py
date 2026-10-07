"""Check an answer's `[cN]` markers against the passages it was given. No model involved.

A marker survives when its label is one of the passages sent. Any other marker is removed.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

_MARKER = re.compile(r"\s?\[(c\d+)\]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Checked:
    answer: str
    cited: list[str]
    dropped: list[str]


def check(text: str, labels: Collection[str]) -> Checked:
    """Keep markers whose label was sent, strip the rest. `cited` follows passage order."""
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
