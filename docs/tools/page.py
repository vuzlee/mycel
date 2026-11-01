"""Build a flow page from its YAML: title, figure, failure table, files, related links.

    python docs/tools/page.py docs/flows/*.yaml    # writes docs/flows/<name>.html next to each

The YAML adds to what flow.py reads:
  page:     {title, lede: [bullets], eyebrow}
  failures: [[case, what happens, file], ...]
  notes:    [[term, value], ...]          # a small table under the figure, optional
  related:  [[label, href], ...]
"""

import html
import sys
from pathlib import Path
from typing import Any

import yaml
from book import PAGES, pager
from flow import ROOT, check, draw

HEAD = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Mycel</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&family=Instrument+Serif&display=swap">
<link rel="stylesheet" href="../page.css">
"""

NAV = (
    '<nav class="topnav"><a href="../index.html">Handbook</a>'
    '<a href="../overview/architecture.html">Architecture</a>'
    '<a href="../overview/config.html">Config</a>'
    '<a href="../overview/database.html">Database</a></nav>'
)


def e(s: str) -> str:
    """Escape, but keep `code` spans written with backticks."""
    parts = html.escape(s).split("`")
    return "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))


def file_cell(path: str) -> str:
    if not path or "/" not in path:
        return e(path)
    short = path.replace("src/mycel/", "")
    return (
        f'<a class="file" href="vscode://file{ROOT / path.split(":")[0]}">{html.escape(short)}</a>'
    )


def table(head: list[str], rows: list[list[str]], files_col: int | None = None) -> str:
    th = "".join(f"<th>{e(h)}</th>" for h in head)
    body = ""
    for r in rows:
        cells = [file_cell(c) if i == files_col else e(c) for i, c in enumerate(r)]
        body += (
            f'<tr><td class="who">{cells[0]}</td>'
            + "".join(f"<td>{c}</td>" for c in cells[1:])
            + "</tr>"
        )
    return f'<table class="tbl"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def files_list(spec: dict[str, Any]) -> list[list[str]]:
    seen, rows = set(), []
    for b in spec["boxes"]:
        if b["file"] not in seen:
            seen.add(b["file"])
            rows.append([b["file"], b["role"]])
    return rows


STEP = (
    '<g class="hv" data-tip="{tip}&#10;step {num}">'
    '<rect x="{x}" y="{y}" width="150" height="56" rx="2"'
    ' fill="var(--surface)" stroke="var(--line)"/>'
    '<text x="{tx}" y="{y1}" font-family="var(--mono)" font-size="9" fill="var(--ink-faint)">'
    "{num} · {folder}</text>"
    '<text x="{tx}" y="{y2}" font-family="var(--mono)" font-size="11" fill="var(--ink)">'
    "{name}</text></g>"
)
ARROW = '<path d="M{x0} {y} H{x1}" stroke="var(--ink-faint)" marker-end="url(#st)"/>'
STEP_DEFS = (
    '<defs><marker id="st" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"'
    ' orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>'
)


def steps_figure(steps: list[list[str]]) -> str:
    """A change recipe as boxes, one per file, in order; hover shows the full path."""
    per, w, gap = 5, 150, 22
    out = []
    for i, (num, path, _do) in enumerate(steps):
        x, y = 16 + i % per * (w + gap), 16 + i // per * 90
        short = path.replace("src/mycel/", "")
        folder = short.rsplit("/", 1)[0] if "/" in short else ""
        folder = folder if len(folder) <= 20 else "…" + folder[-19:]
        out.append(
            STEP.format(
                tip=html.escape(short, quote=True),
                num=html.escape(num),
                x=x,
                y=y,
                tx=x + 10,
                y1=y + 18,
                y2=y + 38,
                folder=html.escape(folder),
                name=html.escape(path.split("/")[-1]),
            )
        )
        if i % per < per - 1 and i < len(steps) - 1:
            out.append(ARROW.format(x0=x + w, y=y + 28, x1=x + w + gap))
    h = 16 + (len(steps) + per - 1) // per * 90
    return (
        f'<svg class="diagram" viewBox="0 0 {16 + per * (w + gap)} {h}" role="img"'
        f' aria-label="Files to change, in order">{STEP_DEFS}{"".join(out)}</svg>'
    )


def build(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())
    if spec.get("boxes"):
        check(spec)
    p = spec["page"]
    lede = "".join(f"<li>{e(x)}</li>" for x in p.get("lede", []))
    out = [HEAD.format(title=html.escape(p["title"])), "<body>", NAV, '<div class="page">']
    out.append(
        f'<header class="hero"><p class="eyebrow">{e(p.get("eyebrow", "Flow"))}</p>'
        f'<h1>{e(p["title"])}</h1><div class="hero-lede"><ul class="bul">{lede}'
        + ("<li>Hover a box for its file · click to open it</li>" if spec.get("boxes") else "")
        + "</ul></div></header>"
    )
    out.append("<section>")
    if spec.get("boxes"):
        out.append('<figure class="tipfig"><div class="tip" role="tooltip"></div>')
        out.append(f'<div class="scroll-x">{draw(spec)}</div></figure>')
    if spec.get("steps") and not spec.get("boxes"):
        out.append('<figure class="tipfig"><div class="tip" role="tooltip"></div>')
        out.append(f'<div class="scroll-x">{steps_figure(spec["steps"])}</div></figure>')
    if spec.get("words"):
        out.append('<h3 class="tbl-title">Words</h3>' + table(["Word", "Means"], spec["words"]))
    if spec.get("steps"):
        out.append(
            '<h3 class="tbl-title">Files to change, in order</h3>'
            + table(["#", "File", "Do"], spec["steps"], files_col=1)
        )
    for name, head, rows in [(t["title"], t["head"], t["rows"]) for t in spec.get("tables", [])]:
        out.append(f'<h3 class="tbl-title">{e(name)}</h3>' + table(head, rows))
    if spec.get("mistakes"):
        out.append(
            '<h3 class="tbl-title">Easy to get wrong</h3>'
            + table(["Mistake", "Result"], spec["mistakes"])
        )
    if spec.get("notes"):
        out.append('<h3 class="tbl-title">Key facts</h3>' + table(["What", "Value"], spec["notes"]))
    if spec.get("failures"):
        out.append(
            '<h3 class="tbl-title">When it goes wrong</h3>'
            + table(["Case", "What happens", "Where"], spec["failures"], files_col=2)
        )
    if spec.get("boxes"):
        out.append(
            "<details><summary>Every file in this flow</summary>"
            + table(["File", "Does"], [[f, r] for f, r in files_list(spec)], files_col=0)
            + "</details>"
        )
    out.append("</section>")
    href = str(path.with_suffix(".html").relative_to(ROOT / "docs"))
    if href in {h for _, (_, h, *_) in PAGES}:
        out.append(pager(href))
    rel = " · ".join(f'<a href="{h}">{e(lbl)}</a>' for lbl, h in spec.get("related", []))
    out.append(
        f'<footer><span>{rel}</span><span class="mono">{path.relative_to(ROOT)}</span></footer>'
    )
    out.append('</div><script src="../tip.js"></script></body>')
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    for a in argv:
        path = Path(a).resolve()
        out = path.with_suffix(".html")
        out.write_text(build(path))
        print(f"{path} → {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
