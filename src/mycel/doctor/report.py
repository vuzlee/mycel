from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    OK = "ok"
    BROKEN = "broken"
    OFF = "off"


@dataclass(frozen=True, slots=True)
class Check:
    """One line of the report."""

    group: str
    name: str
    state: State
    detail: str


MARKS = {State.OK: "ok  ", State.BROKEN: "FAIL", State.OFF: "off "}


def render(checks: list[Check]) -> str:
    """The report as text, grouped, in the order the checks were declared."""
    lines: list[str] = []
    for group in dict.fromkeys(c.group for c in checks):
        lines.append(group)
        for check in (c for c in checks if c.group == group):
            lines.append(f"  {MARKS[check.state]}  {check.name:<14} {check.detail}")
        lines.append("")

    broken = sum(1 for c in checks if c.state is State.BROKEN)
    off = sum(1 for c in checks if c.state is State.OFF)
    if broken:
        lines.append(f"{broken} broken, {off} off on purpose.")
    else:
        lines.append(f"Nothing broken. {off} feature(s) off on purpose.")
    return "\n".join(lines)
