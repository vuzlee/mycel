# ruff: noqa: E501  (HTML and SVG templates read better unwrapped)
"""The handbook as a book: index.html (Start-here figure + contents) and prev/next on every page.

    python docs/tools/book.py    # rewrites docs/index.html and the pager in hand-written pages

Order and figure come from docs/book.yaml. Generated pages get their pager from page.py.
"""

import html
import re
import sys

import yaml
from flow import ROOT

DOCS = ROOT / "docs"
BOOK = yaml.safe_load((DOCS / "book.yaml").read_text())
PAGES = [(i, p) for i, part in enumerate(BOOK["parts"], 1) for p in part["pages"]]
MARK = re.compile(r"<!-- pager -->.*?<!-- /pager -->", re.S)


def number(href: str) -> str:
    """Chapter.page, e.g. 3.2."""
    seen: dict[int, int] = {}
    for part, p in PAGES:
        seen[part] = seen.get(part, 0) + 1
        if p[1] == href:
            return f"{part}.{seen[part]}"
    raise KeyError(href)


def pager(href: str) -> str:
    """Prev · contents · next, with links relative to the page at `href`."""
    up = "../" * href.count("/")
    hrefs = [p[1] for _, p in PAGES]
    i = hrefs.index(href)
    link = lambda j, arrow: (  # noqa: E731
        f'<a href="{up}{hrefs[j]}">{arrow} {html.escape(PAGES[j][1][0])}</a>'
        if 0 <= j < len(hrefs)
        else "<span></span>"
    )
    return (
        f'<!-- pager --><nav class="pager">{link(i - 1, "‹")}'
        f'<a class="at" href="{up}index.html">{number(href)} · contents</a>'
        f"{link(i + 1, '›').replace('› ', '').replace('</a>', ' ›</a>')}</nav><!-- /pager -->"
    )


def figure() -> str:
    x = lambda c: 116 + 190 * c  # noqa: E731
    y = lambda r: 16 + 72 * r  # noqa: E731
    out = []
    lane = 'font-family="var(--mono)" font-size="9" fill="var(--ink-faint)" letter-spacing="1.2"'
    line = 'fill="none" stroke="var(--ink-faint)" marker-end="url(#fa)"'
    for c, name in enumerate(["DATA IN", "MODEL", "OPERATE", "CHANGE IT"]):
        out.append(f'<text x="{x(c)}" y="{y(2) - 8}" {lane}>{name}</text>')
    cols: dict[int, list[int]] = {}
    for _, (_, _, _, _, (c, r)) in PAGES:
        if r >= 2 and c < 3:
            cols.setdefault(c, []).append(r)
    top = x(1) + 75
    for c in (0, 1, 2):
        out.append(f'<path d="M{top} {y(0) + 44} V{y(1) - 14} H{x(c) + 75} V{y(1) - 2}" {line}/>')
        out.append(f'<path d="M{x(c) + 75} {y(1) + 44} V{y(2) - 20}" {line}/>')
        for a, b in zip(sorted(cols[c]), sorted(cols[c])[1:], strict=False):
            out.append(f'<path d="M{x(c) + 75} {y(a) + 44} V{y(b) - 2}" {line}/>')
    out.append(f'<path d="M{x(3)} {y(1) + 22} H{x(2) + 152}" {line}/>')
    for part, (label, href, _q, dirs, (c, r)) in PAGES:
        hot = (
            'fill="var(--accent-soft)" stroke="var(--accent)"'
            if r == 0
            else 'fill="var(--surface)" stroke="var(--line)"'
        )
        dash = ' stroke-dasharray="4 3"' if part == len(BOOK["parts"]) else ""
        out.append(
            f'<a href="{href}" class="hv" data-tip="{html.escape(dirs)}\n{number(href)} · {html.escape(_q)}">'
            f'<rect x="{x(c)}" y="{y(r) + 6 * (r > 1)}" width="150" height="44" rx="2" {hot}{dash}/>'
            f'<text x="{x(c) + 10}" y="{y(r) + 6 * (r > 1) + 18}" font-family="var(--mono)" font-size="9.5" fill="var(--ink-faint)">{number(href)}</text>'
            f'<text x="{x(c) + 10}" y="{y(r) + 6 * (r > 1) + 34}" font-family="var(--mono)" font-size="{11 if len(label) < 20 else 10}" fill="var(--ink)">{html.escape(label)}</text></a>'
        )
    h = y(max(r for _, p in PAGES for r in [p[4][1]])) + 60
    return (
        f'<svg class="diagram" viewBox="0 0 852 {h}" role="img" aria-label="Reading order: '
        "Architecture, then Config, Database, Run and Setup, then three independent branches, "
        'change recipes last"><defs><marker id="fa" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 '
        f'L 0 10 z" fill="currentColor"/></marker></defs>{"".join(out)}</svg>'
    )


def contents() -> str:
    out = []
    for i, part in enumerate(BOOK["parts"], 1):
        rows = "".join(
            f'<tr><td>{number(h)}</td><td><a href="{h}">{html.escape(t)}</a></td>'
            f"<td>{html.escape(q)}</td></tr>"
            for t, h, q, _, _ in part["pages"]
        )
        out.append(
            f'<h3 class="tbl-title">{i} · {html.escape(part["name"])}</h3>'
            f'<table class="tbl toc"><tbody>{rows}</tbody></table>'
        )
    return "\n".join(out)


def index() -> str:
    first = PAGES[0][1]
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{BOOK["title"]}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&family=Instrument+Serif&display=swap">
<link rel="stylesheet" href="page.css">
<body>
<nav class="topnav"><a href="index.html">Handbook</a><a href="overview/architecture.html">Architecture</a><a href="overview/config.html">Config</a><a href="overview/database.html">Database</a></nav>
<div class="page">
<header class="hero"><p class="eyebrow">{BOOK["title"]}</p><h1>Start here</h1><div class="hero-lede"><ul class="bul"><li>Read top to bottom; boxes side by side read in parallel</li><li>Data in, Model, Operate are independent; inside one, follow the arrows</li><li>Every page ends with ‹ previous · next ›; hover a box for its folders</li></ul></div></header>
<section>
<figure class="tipfig"><div class="tip" role="tooltip"></div>
<div class="scroll-x">{figure()}</div></figure>
<nav class="pager"><span></span><a href="{first[1]}">Begin: {html.escape(first[0])} ›</a></nav>
</section>
<section>
<h2>Contents</h2>
{contents()}
<details><summary>Keeping this handbook right</summary>
<table class="tbl"><thead><tr><th>Do</th><th>Command</th></tr></thead><tbody>
<tr><td class="who">check every link, file, figure edge and page order</td><td><code>uv run python docs/tools/check.py</code></td></tr>
<tr><td class="who">rebuild a flow page after editing its YAML</td><td><code>uv run python docs/tools/page.py docs/flows/&lt;name&gt;.yaml</code></td></tr>
<tr><td class="who">change the order or add a page</td><td>edit <code>docs/book.yaml</code>, then <code>uv run python docs/tools/book.py</code></td></tr>
</tbody></table></details>
</section>
<footer><span>Order and figure from <code>docs/book.yaml</code>.</span><span class="mono">docs/index.html</span></footer>
</div>
<script src="tip.js"></script>
</body>
"""


def hand_pages() -> list[str]:
    """Pages not built by page.py; their pager is patched in place."""
    return [h for _, (_, h, *_) in PAGES if not (DOCS / h).with_suffix(".yaml").exists()]


def patched(href: str) -> str:
    s = (DOCS / href).read_text()
    if MARK.search(s):
        return MARK.sub(lambda _: pager(href), s)
    i = s.rindex("<footer") if "<footer" in s else s.rindex("</main>")
    return s[:i] + pager(href) + "\n" + s[i:]


def main() -> int:
    (DOCS / "index.html").write_text(index())
    for h in hand_pages():
        (DOCS / h).write_text(patched(h))
    print(f"index.html + {len(hand_pages())} hand-written pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
