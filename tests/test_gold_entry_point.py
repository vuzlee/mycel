"""Nothing reads gold for a person except through `services/permission.py`."""

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "mycel"

#: Reads gold on behalf of nobody.
NOT_PERSON_FACING = {
    "domains/sync.py",
    "services/transform.py",
    "services/dashboard.py",
    "services/gather.py",
    "infra/vectors/indexer.py",
    "infra/postgres/repositories/gold.py",
    "infra/postgres/repositories/gold_stats.py",
}

GATES = ("require(", "readable(", "readable_projects(")
GOLD = ("GoldRepository(", "GoldStats(", "gather_progress(", "build_dashboard(", "list_projects(")


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
