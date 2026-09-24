"""Render the animated README demo: the landing page's scripted run, as an SVG.

Why SVG and not a GIF or an MP4. A GIF of text is a blurry GIF of text, it weighs a few
megabytes for thirty seconds, and it is the wrong thing to keep in a repository: nobody
can diff it, and the day a tool label changes somebody has to find the machine that made
it. This file is generated from the same data the web demo uses, in a script that ships
beside it, and it is a few kilobytes of markup.

Animated with SMIL. GitHub strips `<style>` out of an embedded SVG, so every value is an
attribute and every timeline is one `<animate>` over the whole loop using `values` and
`keyTimes` — no `fill="freeze"`, no chained `begin`, nothing that has to be reset when
the loop comes round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 880, 468
LOOP = 36.0
SLOT = LOOP / 3

# There is no font here to measure, so the line breaks are decided on an estimated
# character width. Only the breaks are: within a line the words are `<tspan>`s in normal
# flow, so the renderer sets the spacing and nothing depends on the guess being right.
BODY = 15.0
CHAR = 7.6
WRAP_CHARS = 78


@dataclass(frozen=True)
class Figure:
    label: str
    value: str
    bar: float
    step: int


@dataclass(frozen=True)
class Scene:
    question: str
    steps: list[str]
    answer: str
    figures: list[Figure] = field(default_factory=list)


LABELS = {
    "summariser": "Summarising the project",
    "analyst": "Asking the analyst",
    "run_sql": "Analysing the data",
    "percent_change": "Doing the maths",
    "researcher": "Asking the researcher",
    "read_mail": "Reading the mailbox",
    "web_search": "Searching the web",
}

SCENES = [
    Scene(
        question="How is MYC going this week?",
        steps=["summariser"],
        answer=(
            "**On track.** Nine issues closed and two slipped a day. "
            "One to watch: MYC-21 is due Friday and has not started."
        ),
        figures=[
            Figure("Closed", "9", 100, 1),
            Figure("In flight", "4", 45, 2),
            Figure("Late", "1", 12, 4),
        ],
    ),
    Scene(
        question="Who logged the most hours this month?",
        steps=["analyst", "run_sql", "percent_change"],
        answer=(
            "**Ada, 47h** — 31h of it on MYC-17, then Grace at 38h. "
            "The team is up 12% on last month."
        ),
        figures=[
            Figure("Ada", "47h", 100, 1),
            Figure("Grace", "38h", 81, 2),
            Figure("Alan", "29h", 62, 3),
        ],
    ),
    Scene(
        question="Anything important in my mail today?",
        steps=["researcher", "read_mail", "web_search"],
        answer=(
            "**Two worth opening.** Atlassian is deprecating an endpoint you call, "
            "and your vendor has been waiting on you since Tuesday."
        ),
    ),
]


@dataclass(frozen=True)
class Palette:
    ground: str
    surface: str
    sunk: str
    rule: str
    ink: str
    muted: str
    faint: str
    accent: str


LIGHT = Palette(
    "#faf9fc", "#ffffff", "#f2eff8", "#e7e3f0", "#17141f", "#6f6782", "#9a92ab", "#6d3fd1"
)
DARK = Palette(
    "#0b0910", "#14101d", "#1c1728", "#241f30", "#f0edf7", "#8f87a3", "#6b6380", "#b79cff"
)


def words(answer: str) -> list[tuple[str, bool]]:
    """Split into words, resolving the bold markers up front.

    Streaming the raw string would put `**On` on screen for one frame, and an image that
    flashes its own syntax is worse than one that does not animate at all.
    """
    out: list[tuple[str, bool]] = []
    for i, part in enumerate(answer.split("**")):
        for word in part.split():
            out.append((word, i % 2 == 1))
    return out


def wrap(tokens: list[tuple[str, bool]]) -> list[list[tuple[str, bool]]]:
    """Break the words into lines at roughly the column width."""
    lines: list[list[tuple[str, bool]]] = [[]]
    used = 0
    for word, strong in tokens:
        if used + len(word) > WRAP_CHARS and lines[-1]:
            lines.append([])
            used = 0
        lines[-1].append((word, strong))
        used += len(word) + 1
    return lines


def timeline(spans: list[tuple[float, float]]) -> tuple[str, str]:
    """One opacity track over the whole loop, as `values` and `keyTimes`.

    Each span is a window the element is visible in, with a short fade at either end.
    Everything outside every span is zero, so a loop needs no resetting.
    """
    stops: list[tuple[float, float]] = [(0.0, 0.0)]
    for start, end in spans:
        stops += [(start, 0.0), (start + 0.28, 1.0), (end, 1.0), (end + 0.36, 0.0)]
    stops.append((LOOP, 0.0))
    stops.sort(key=lambda s: s[0])
    keys = ";".join(f"{min(t, LOOP) / LOOP:.5f}" for t, _ in stops)
    vals = ";".join(f"{v:g}" for _, v in stops)
    return vals, keys


def fade(spans: list[tuple[float, float]]) -> str:
    vals, keys = timeline(spans)
    return (
        f'<animate attributeName="opacity" dur="{LOOP:g}s" repeatCount="indefinite" '
        f'values="{vals}" keyTimes="{keys}"/>'
    )


def grow(width: float, start: float, end: float) -> str:
    """A bar that is zero until the answer lands, then runs out to its width."""
    stops = [
        (0.0, 0.0),
        (start, 0.0),
        (start + 0.75, width),
        (end, width),
        (end + 0.36, 0.0),
        (LOOP, 0.0),
    ]
    keys = ";".join(f"{min(t, LOOP) / LOOP:.5f}" for t, _ in stops)
    vals = ";".join(f"{v:.1f}" for _, v in stops)
    return (
        f'<animate attributeName="width" dur="{LOOP:g}s" repeatCount="indefinite" '
        f'values="{vals}" keyTimes="{keys}" calcMode="spline" '
        f'keySplines="{";".join(["0.2 0.7 0.3 1"] * (len(stops) - 1))}"/>'
    )


def shade(p: Palette, step: int) -> str:
    """Four steps down the one hue, as flat opacity on the accent — `color-mix` is a CSS
    function and there is no CSS here."""
    return {1: "1", 2: "0.68", 3: "0.44", 4: "0.24"}[step]


def render(p: Palette, label: str) -> str:
    out: list[str] = []
    add = out.append

    add(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-label="Mycel answering three questions about a Jira project">'
    )
    add(f"<!-- Generated by scripts/tools/render_demo.py — {label}. Do not edit by hand. -->")
    add(f'<rect width="{W}" height="{H}" rx="16" fill="{p.ground}"/>')
    add(
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="15.5" '
        f'fill="none" stroke="{p.rule}"/>'
    )

    # Chrome: three dots and the project, so the frame reads as a window without a word.
    add(f'<rect x="1" y="1" width="{W - 2}" height="46" rx="15.5" fill="{p.surface}"/>')
    add(f'<rect x="1" y="32" width="{W - 2}" height="15" fill="{p.surface}"/>')
    add(f'<line x1="1" y1="47" x2="{W - 1}" y2="47" stroke="{p.rule}"/>')
    for i in range(3):
        add(f'<circle cx="{26 + i * 17}" cy="24" r="4.5" fill="{p.rule}"/>')
    add(
        f'<text x="88" y="28" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
        f'font-size="11" letter-spacing="0.5" fill="{p.faint}">MYC</text>'
    )
    add(f'<circle cx="124" cy="24" r="3" fill="{p.accent}">')
    add(
        '<animate attributeName="opacity" dur="2.4s" repeatCount="indefinite" '
        'values="1;0.25;1" keyTimes="0;0.5;1"/></circle>'
    )

    for index, scene in enumerate(SCENES):
        base = index * SLOT
        ends = base + SLOT - 1.4

        asked = base + 0.4
        step_at = [asked + 1.1 + i * 0.72 for i in range(len(scene.steps))]
        writes = (step_at[-1] if step_at else asked) + 1.05

        add('<g transform="translate(0 0)">')

        # The question, right-aligned in a bubble: the one thing on screen the reader
        # supplies, so it is the one thing that does not look like output.
        q_width = len(scene.question) * CHAR + 44
        add(f'<g opacity="0">{fade([(asked, ends)])}')
        add(
            f'<rect x="{W - 34 - q_width}" y="74" width="{q_width}" height="42" rx="21" '
            f'fill="{p.sunk}"/>'
        )
        add(
            f'<text x="{W - 56}" y="100" text-anchor="end" font-family="system-ui,sans-serif" '
            f'font-size="{BODY}" fill="{p.ink}">{escape(scene.question)}</text>'
        )
        add("</g>")

        # The steps. Each one lights as it starts and stays lit: an earlier draft dimmed
        # the finished ones back down, which read as the run forgetting what it had done.
        for i, tool in enumerate(scene.steps):
            y = 152 + i * 30
            add(f'<g opacity="0">{fade([(step_at[i], ends)])}')
            add(
                f'<circle cx="42" cy="{y - 5}" r="6.5" fill="none" '
                f'stroke="{p.accent}" stroke-width="1.6"/>'
            )
            add(f'<circle cx="42" cy="{y - 5}" r="3" fill="{p.accent}"/>')
            add(
                f'<text x="60" y="{y}" font-family="system-ui,sans-serif" font-size="13.5" '
                f'fill="{p.muted}">{escape(LABELS[tool])}</text>'
            )
            add("</g>")

        # The answer, a word at a time, from the same markers the web demo parses.
        top = 152 + len(scene.steps) * 30 + 34
        tokens = words(scene.answer)
        spoken = 0
        for row, line in enumerate(wrap(tokens)):
            y = top + row * 25
            add(
                f'<text x="34" y="{y}" xml:space="preserve" font-family="system-ui,sans-serif" '
                f'font-size="{BODY}" fill="{p.muted}">'
            )
            for i, (word, strong) in enumerate(line):
                at = writes + spoken * 0.075
                spoken += 1
                weight = ' font-weight="600"' if strong else ""
                fill = f' fill="{p.ink}"' if strong else ""
                lead = "" if i == 0 else " "
                add(
                    f'<tspan{weight}{fill} opacity="0">{lead}{escape(word)}'
                    f"{fade([(at, ends)])}</tspan>"
                )
            add("</text>")

        # The figures, as the small dashboard the answer is built on.
        if scene.figures:
            lands = writes + spoken * 0.075 + 0.2
            base_y = top + 25 * len(wrap(tokens)) + 22
            add(f'<g opacity="0">{fade([(lands, ends)])}')
            add(
                f'<line x1="34" y1="{base_y}" x2="{34 + WRAP_CHARS * CHAR:.0f}" '
                f'y2="{base_y}" stroke="{p.rule}"/>'
            )
            add("</g>")
            for i, figure in enumerate(scene.figures):
                y = base_y + 26 + i * 25
                track = 400.0
                add(f'<g opacity="0">{fade([(lands + i * 0.09, ends)])}')
                add(
                    f'<text x="34" y="{y + 4}" font-family="system-ui,sans-serif" font-size="12" '
                    f'fill="{p.muted}">{escape(figure.label)}</text>'
                )
                add(
                    f'<rect x="130" y="{y - 3}" width="{track}" height="7" '
                    f'rx="3.5" fill="{p.sunk}"/>'
                )
                run = grow(track * figure.bar / 100, lands + i * 0.09, ends)
                add(
                    f'<rect x="130" y="{y - 3}" width="0" height="7" rx="3.5" '
                    f'fill="{p.accent}" opacity="{shade(p, figure.step)}">{run}</rect>'
                )
                add(
                    f'<text x="{130 + track + 14}" y="{y + 4}" '
                    f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="12" '
                    f'fill="{p.ink}">{escape(figure.value)}</text>'
                )
                add("</g>")

        add("</g>")

    add("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    assets = Path(__file__).resolve().parents[2] / "assets"
    (assets / "demo-light.svg").write_text(render(LIGHT, "light"), encoding="utf-8")
    (assets / "demo-dark.svg").write_text(render(DARK, "dark"), encoding="utf-8")
    print("wrote assets/demo-light.svg and assets/demo-dark.svg")


if __name__ == "__main__":
    main()
