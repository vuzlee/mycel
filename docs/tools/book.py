# ruff: noqa: E501  (HTML and SVG templates read better unwrapped)
"""The handbook as a book: index.html (Start-here figure + contents) and prev/next on every page.

    python docs/tools/book.py    # rewrites index.html, glossary.html, and nav, words, pager in hand-written pages

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
TOPNAV = re.compile(r'<nav class="topnav">.*?</nav>', re.S)
#: The same top bar on every page: home, the three overview pages, the glossary.
NAV_LINKS = [
    ("Handbook", "index.html"),
    ("Architecture", "overview/architecture.html"),
    ("Config", "overview/config.html"),
    ("Database", "overview/database.html"),
    ("Glossary", "glossary.html"),
]


def topnav(href: str) -> str:
    up = "../" * href.count("/")
    here = ' aria-current="page"'
    links = "".join(f'<a href="{up}{h}"{here if h == href else ""}>{t}</a>' for t, h in NAV_LINKS)
    return f'<nav class="topnav">{links}</nav>'


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
    """Overview pages in a row, read left to right; under them one column per part."""
    w, gap, h, step = 150, 22, 44, 62
    x = lambda c: 16 + (w + gap) * c  # noqa: E731
    y = lambda r: 16 + step * r + 40 * (r > 0)  # noqa: E731
    lane = 'font-family="var(--mono)" font-size="10" fill="var(--ink-soft)" letter-spacing="1.2"'
    line = 'fill="none" stroke="var(--ink-faint)" marker-end="url(#fa)"'
    first, *rest = BOOK["parts"]
    out = []

    def box(label: str, href: str, q: str, dirs: str, bx: float, by: float, hot: bool) -> str:
        look = (
            'fill="var(--accent-soft)" stroke="var(--accent)"'
            if hot
            else 'fill="var(--surface)" stroke="var(--line)"'
        )
        size = 11 if len(label) < 20 else 10
        return (
            f'<a href="{href}" class="hv" data-tip="{html.escape(dirs)}\n{number(href)} · '
            f'{html.escape(q)}"><rect x="{bx}" y="{by}" width="{w}" height="{h}" rx="2" {look}/>'
            f'<text x="{bx + 10}" y="{by + 18}" font-family="var(--mono)" font-size="10" '
            f'fill="var(--ink-soft)">{number(href)}</text><text x="{bx + 10}" y="{by + 34}" '
            f'font-family="var(--mono)" font-size="{size}" fill="var(--ink)">'
            f"{html.escape(label)}</text></a>"
        )

    for i, (label, href, q, dirs, _) in enumerate(first["pages"]):
        out.append(box(label, href, q, dirs, x(i), y(0), i < 2))
        if i:
            out.append(f'<path d="M{x(i) - gap} {y(0) + h / 2} H{x(i) - 2}" {line}/>')
    rows = 0
    for c, part in enumerate(rest):
        out.append(
            f'<text x="{x(c)}" y="{y(1) - 10}" {lane}>{html.escape(part["name"].upper())}</text>'
        )
        for r, (label, href, q, dirs, _) in enumerate(part["pages"]):
            out.append(box(label, href, q, dirs, x(c), y(1 + r), False))
            if r:
                out.append(f'<path d="M{x(c) + w / 2} {y(r) + h} V{y(1 + r) - 2}" {line}/>')
        rows = max(rows, len(part["pages"]))
    return (
        f'<svg class="diagram" viewBox="0 0 {x(len(rest))} {y(rows) + h + 16}" role="img" '
        'aria-label="Reading order: the overview row left to right, then each part top to '
        'bottom"><defs><marker id="fa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" '
        f'fill="currentColor"/></marker></defs>{"".join(out)}</svg>'
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
{topnav("index.html")}
<div class="page">
<header class="hero"><p class="eyebrow">{BOOK["title"]}</p><h1>Start here</h1><div class="hero-lede"><ul class="bul"><li>Read the top row first: Architecture, then Ask a question</li><li>Then any column; inside one, top to bottom</li><li>Every page ends with ‹ previous · next ›; words link to the Glossary</li></ul></div></header>
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


def glossary() -> str:
    from words import GLOSSARY, row

    rows = "".join(row(w, "glossary.html") for w in GLOSSARY)
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Glossary · Mycel</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&family=Instrument+Serif&display=swap">
<link rel="stylesheet" href="page.css">
<body>
{topnav("glossary.html")}
<div class="page">
<header class="hero"><p class="eyebrow">{BOOK["title"]}</p><h1>Glossary</h1><div class="hero-lede"><ul class="bul"><li>Every word the handbook uses, one meaning each</li><li>→ opens the page that teaches it</li></ul></div></header>
<section>
<table class="tbl words"><thead><tr><th>Word</th><th>Means</th></tr></thead><tbody>{rows}</tbody></table>
</section>
<footer><span class="mono">docs/glossary.yaml</span></footer>
</div>
</body>
"""


def hand_pages() -> list[str]:
    """Pages not built by page.py; their pager is patched in place."""
    return [h for _, (_, h, *_) in PAGES if not (DOCS / h).with_suffix(".yaml").exists()]


def patched(href: str) -> str:
    """The page with this book's top bar, Words table and pager."""
    from words import MARK as WORDS
    from words import block

    s = (DOCS / href).read_text()
    s = TOPNAV.sub(lambda _: topnav(href), s, count=1)
    if '<nav class="topnav">' not in s:
        s = s.replace("<body>\n", f"<body>\n{topnav(href)}\n", 1)
    s = WORDS.sub(lambda m: block(m.group(1).split(" | "), href), s)
    if MARK.search(s):
        return MARK.sub(lambda _: pager(href), s)
    i = s.rindex("<footer") if "<footer" in s else s.rindex("</main>")
    return s[:i] + pager(href) + "\n" + s[i:]


def main() -> int:
    (DOCS / "index.html").write_text(index())
    (DOCS / "glossary.html").write_text(glossary())
    for h in hand_pages():
        (DOCS / h).write_text(patched(h))
    print(f"index.html + {len(hand_pages())} hand-written pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
