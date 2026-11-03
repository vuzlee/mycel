"""The shared glossary: one meaning per word; a page's Words table names at most six of them.

docs/glossary.yaml holds [word, meaning, page that teaches it]. A generated page lists keys
under `words:`; a hand-written page carries them in `<!-- words: a | b -->…<!-- /words -->`,
which book.py fills in.
"""

import html
import re

import yaml
from flow import ROOT

DOCS = ROOT / "docs"
MAX = 6
GLOSSARY = {
    w: (means, page)
    for w, means, page in yaml.safe_load((DOCS / "glossary.yaml").read_text())["words"]
}
MARK = re.compile(r"<!-- words: (.*?) -->.*?<!-- /words -->", re.S)


def e(s: str) -> str:
    """Escape, but keep `code` spans written with backticks."""
    parts = html.escape(s).split("`")
    return "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))


def slug(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", word.lower()).strip("-") or "w"


def row(word: str, here: str) -> str:
    """One glossary row; the meaning links to the page that teaches it, unless that is `here`."""
    means, page = GLOSSARY[word]
    up = "../" * here.count("/")
    more = ""
    if page and page != here:
        more = f' <a class="taught" href="{up}{page}">→ {html.escape(title_of(page))}</a>'
    return (
        f'<tr id="{slug(word)}"><td class="who"><a href="{up}glossary.html#{slug(word)}">'
        f"{e(word)}</a></td><td>{e(means)}{more}</td></tr>"
    )


def table(keys: list[str], here: str) -> str:
    rows = "".join(row(k, here).replace(f' id="{slug(k)}"', "", 1) for k in keys)
    return (
        '<h3 class="tbl-title">Words</h3><table class="tbl words"><thead><tr><th>Word</th>'
        f"<th>Means</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def block(keys: list[str], here: str) -> str:
    """The marked block a hand-written page carries."""
    return f"<!-- words: {' | '.join(keys)} -->{table(keys, here)}<!-- /words -->"


def misses(keys: list[str], where: str) -> list[str]:
    out = [f"{where}: word {k!r} is not in glossary.yaml" for k in keys if k not in GLOSSARY]
    if len(keys) > MAX:
        out.append(f"{where}: {len(keys)} words, at most {MAX}; the rest live in the glossary")
    return out


def title_of(href: str) -> str:
    from book import PAGES

    return next((p[0] for _, p in PAGES if p[1] == href), href)
