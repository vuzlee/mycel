"""Every handbook check in one command; exit 1 on any miss.

    python docs/tools/check.py

- every link and script/stylesheet path resolves inside docs/, every #anchor exists
- every data-path and every vscode:// link names a file that exists
- every flow figure's boxes exist and every edge is seen in the code (docs/tools/flow.py)
- every flow page and the architecture figure match their YAML (rebuild with page.py / flow.py)
- prints, without failing, each flow whose files were committed after the flow was
"""

import re
import subprocess
import sys
from pathlib import Path

import yaml
from flow import ROOT, check, draw
from page import build

DOCS = ROOT / "docs"
FLOWS = sorted([*(DOCS / "flows").glob("*.yaml"), *(DOCS / "change").glob("*.yaml"), *(DOCS / "operate").glob("*.yaml")])
#: Pages that embed a flow figure in place, besides the flow pages themselves.
EMBEDS = {"overview/architecture.html": ("flows/ask.yaml", '<section id="s07">')}


def links() -> list[str]:
    misses = []
    for f in DOCS.rglob("*.html"):
        if f.name.endswith(".svg.html"):
            continue
        s = f.read_text()
        for h in re.findall(r'(?:href|src)="([^"]+)"', s):
            if h.startswith(("http", "mailto:", "vscode:", "#")):
                continue
            path, _, anchor = h.partition("#")
            target = (f.parent / path).resolve()
            if DOCS not in target.parents or not target.exists():
                misses.append(f"{f.relative_to(DOCS)}: broken link {h}")
            elif anchor and f'id="{anchor}"' not in target.read_text():
                misses.append(f"{f.relative_to(DOCS)}: no #{anchor} in {path}")
        for p in re.findall(r'data-path="([^"]+)"', s):
            if not (ROOT / p).exists():
                misses.append(f"{f.relative_to(DOCS)}: data-path {p} does not exist")
        for p in re.findall(r'href="vscode://file([^"]+)"', s):
            if not Path(p.split(":")[0]).exists():
                misses.append(f"{f.relative_to(DOCS)}: vscode link {p} does not exist")
    return misses


def flows() -> list[str]:
    misses = []
    for y in FLOWS:
        spec = yaml.safe_load(y.read_text())
        if spec.get("boxes"):
            misses += [f"{y.name}: {m}" for m in check(spec)]
        named = [r[1] for r in spec.get("steps", [])] + [r[2] for r in spec.get("failures", [])]
        for f in named:
            if "/" in f and not (ROOT / f.split(":")[0]).exists():
                misses.append(f"{y.name}: no file {f}")
        page = y.with_suffix(".html")
        if "page" in spec and (not page.exists() or page.read_text() != build(y)):
            misses.append(
                f"{page.name}: out of date — python docs/tools/page.py {y.relative_to(ROOT)}"
            )
    for page, (yml, anchor) in EMBEDS.items():
        spec = yaml.safe_load((DOCS / yml).read_text())
        check(spec)
        s = (DOCS / page).read_text()
        i = s.index("<svg", s.index(anchor))
        if s[i : s.index("</svg>", i) + 6] != draw(spec):
            misses.append(
                f"{page}: figure differs from {yml} — python docs/tools/flow.py docs/{yml}"
            )
    return misses


def last_commit(path: Path) -> int:
    """Unix time of the last commit that touched `path`; 0 when it has none."""
    out = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return int(out) if out else 0


def stale() -> list[str]:
    """Flow pages whose files changed after the page did: worth a look, not an error."""
    notes = []
    for y in FLOWS:
        spec = yaml.safe_load(y.read_text())
        files = {b["file"] for b in spec.get("boxes", [])} | {r[1] for r in spec.get("steps", [])}
        page = last_commit(y)
        newer = sorted(f for f in files if "/" in f and last_commit(ROOT / f) > page)
        if newer:
            notes.append(
                f"{y.relative_to(DOCS)}: code changed since — {', '.join(newer[:3])}"
                + (f" (+{len(newer) - 3})" if len(newer) > 3 else "")
            )
    return notes


def main() -> int:
    misses = links() + flows()
    for m in misses:
        print(m)
    for n in stale():
        print(f"stale? {n}")
    print(f"{len(misses)} misses · {len(FLOWS)} flows")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
