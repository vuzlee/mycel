"""One golden case, and the checks it asserts.

A case is a prompt the summariser is given plus what a person decided a good answer must
contain. Not a full expected output: two acceptable summaries word the same headline
differently, and a diff against one of them scores the wording rather than the substance.
What is checked is what would be *wrong* to get wrong — the verdict, which tickets are
late, whether a truncated window admits it.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mycel.agents.schemas import ProgressSummary

#: A headline is read on its own by someone who opens nothing else, so the schema asks for
#: one sentence. Longer than this and it is a paragraph wearing a headline's name.
HEADLINE_MAX = 140


@dataclass(frozen=True)
class Check:
    """One thing that must hold, and whether it held."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class Case:
    """One prompt and the substance its answer must carry."""

    name: str
    prompt: str
    #: The window's verdict. The single most consequential field: a late project called
    #: `on_track` is the failure the whole report exists to prevent.
    health: str | None = None
    #: Issue keys that must appear in `at_risk`. Extra rows are allowed — judging *more*
    #: things risky is a defensible call; missing a late one is not.
    at_risk_keys: list[str] = field(default_factory=list)
    #: Keys that must appear in `shipped`.
    shipped_keys: list[str] = field(default_factory=list)
    #: Keys that must not appear anywhere. Work the prompt never mentioned, mostly: this
    #: is the invention check.
    absent_keys: list[str] = field(default_factory=list)
    #: People who must have a row in `load`.
    load_people: list[str] = field(default_factory=list)
    #: Substrings the `notes` list must carry, lowercased before comparing. A truncated
    #: window that does not say so is a summary claiming completeness it does not have.
    notes_contain: list[str] = field(default_factory=list)

    def check(self, got: ProgressSummary) -> list[Check]:
        """Score one answer. Every check is independent; none short-circuits the rest."""
        checks = [
            Check(
                "headline is one sentence",
                0 < len(got.headline) <= HEADLINE_MAX,
                f"{len(got.headline)} chars",
            )
        ]

        if self.health is not None:
            checks.append(Check("health", got.health == self.health, f"got {got.health}"))

        everywhere = _keys(got.shipped) | _keys(got.in_flight) | _keys(got.at_risk)
        for expected, actual, label in (
            (self.at_risk_keys, _keys(got.at_risk), "at_risk"),
            (self.shipped_keys, _keys(got.shipped), "shipped"),
        ):
            for key in expected:
                checks.append(Check(f"{label} has {key}", key in actual))

        for key in self.absent_keys:
            checks.append(Check(f"invented {key}", key not in everywhere))

        people = {line.person.lower() for line in got.load}
        for person in self.load_people:
            checks.append(Check(f"load has {person}", person.lower() in people))

        notes = " ".join(got.notes).lower()
        for fragment in self.notes_contain:
            checks.append(Check(f"notes mention {fragment!r}", fragment.lower() in notes))

        return checks


def load_all(directory: Path) -> list[Case]:
    """Every `.yaml` in the golden set, by filename."""
    return [_case(path) for path in sorted(directory.glob("*.yaml"))]


def _case(path: Path) -> Case:
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    expect: dict[str, Any] = raw.get("expect") or {}
    return Case(
        name=path.stem,
        prompt=raw["prompt"],
        health=expect.get("health"),
        at_risk_keys=list(expect.get("at_risk_keys") or []),
        shipped_keys=list(expect.get("shipped_keys") or []),
        absent_keys=list(expect.get("absent_keys") or []),
        load_people=list(expect.get("load_people") or []),
        notes_contain=list(expect.get("notes_contain") or []),
    )


def _keys(lines: list[Any]) -> set[str]:
    return {line.key.strip().upper() for line in lines}
