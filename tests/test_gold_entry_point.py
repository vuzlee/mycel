"""Nothing reads gold for a person except through `services/permission.py`.

The database limits only `run_sql`; every other read is limited by its caller remembering a
check, and the next endpoint to forget would read every project. So the rule is checked on
the source: a module that serves a person and touches gold must go through `require` or
`readable` (or pass `readable_projects` down, as `run_sql` and `rag_search` do).
"""

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "mycel"

#: Reads gold on behalf of nobody: the sync, the transform, the indexer, and the services
#: whose only callers are the gated ones below.
NOT_PERSON_FACING = {
    "domains/sync.py",
    "services/transform.py",
    "services/dashboard.py",
    "services/gather.py",
    "infra/vectors/indexer.py",
    "infra/postgres/repositories/gold.py",
}

GATES = ("require(", "readable(", "readable_projects(")
GOLD = ("GoldRepository(", "gather_progress(", "build_dashboard(", "list_projects(")


def _person_facing_gold_readers() -> list[Path]:
    out = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in NOT_PERSON_FACING:
            continue
        text = path.read_text()
        if any(call in text for call in GOLD):
            out.append(path)
    return out


def test_there_is_something_to_check() -> None:
    assert _person_facing_gold_readers(), "the scan found no gold reader — the rule is untested"


@pytest.mark.parametrize("path", _person_facing_gold_readers(), ids=lambda p: p.name)
def test_every_person_facing_gold_read_is_gated(path: Path) -> None:
    text = path.read_text()
    assert any(gate in text for gate in GATES), (
        f"{path.relative_to(SRC)} reads gold for a person without services/permission.py"
    )
