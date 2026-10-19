"""Which source folders the handbook covers, and which it does not yet.

    python docs/tools/coverage.py      # prints covered and uncovered folders; never fails

A folder is covered when a page's figure has a box in it, or a page lists it below. Coverage is
by folder, not by file: a page explains a flow, and a flow crosses many files.
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

#: Folders a page explains without drawing a box in them.
EXPLAINED = {
    "src/mycel/core": "overview/config.html",
    "src/mycel/infra/postgres/models": "overview/database.html",
    "src/mycel/infra/postgres/repositories": "overview/database.html",
    "src/mycel/etl": "change/add-gold-column.html",
    "src/mycel/agents/tools": "change/add-tool.html",
    "src/mycel/agents/prompts": "change/add-tool.html",
    "config/environments": "overview/config.html",
    "config/agents": "overview/config.html",
    "migrations/versions": "overview/database.html",
    "src/mycel/infra/documents": "flows/upload.html",
    "src/mycel/etl/checks": "flows/jira-sync.html",
    "web/src/context": "flows/sign-in.html",
    "src/mycel/plugins/google": "flows/connect.html",
    "src/mycel/agents": "overview/architecture.html",
    "src/mycel/mcp": "change/add-tool.html",
    "web/src/components": "overview/architecture.html",
    # Dev-machine helpers, never imported by the app.
    "src/mycel/devtools": "operate/run.html",
}


def folders() -> set[str]:
    """Every folder under src/mycel and web/src that holds code."""
    out = set()
    for base, exts in (("src/mycel", (".py",)), ("web/src", (".ts", ".tsx"))):
        for f in (ROOT / base).rglob("*"):
            if f.suffix in exts and "__pycache__" not in f.parts and ".test." not in f.name:
                out.add(str(f.parent.relative_to(ROOT)))
    return out


def covered() -> dict[str, str]:
    """Folder → the first page that covers it."""
    seen: dict[str, str] = dict(EXPLAINED)
    for y in sorted(DOCS.rglob("*.yaml")):
        spec = yaml.safe_load(y.read_text()) or {}
        page = str(y.with_suffix(".html").relative_to(DOCS))
        files = [b["file"] for b in spec.get("boxes", [])]
        files += [r[1] for r in spec.get("steps", [])] + [r[2] for r in spec.get("failures", [])]
        for f in files:
            if "/" in f:
                seen.setdefault(str(Path(f).parent), page)
    return seen


def main() -> int:
    have, all_ = covered(), folders()
    hit = sorted(f for f in all_ if f in have)
    miss = sorted(f for f in all_ if f not in have)
    print(f"{len(hit)} of {len(all_)} code folders covered")
    for f in miss:
        print(f"  not yet: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
