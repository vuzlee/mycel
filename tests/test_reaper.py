"""The reaper's rule: only clusters tagged as a session and past their expiry."""

import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
FRESH = datetime(2026, 11, 1, 11, tzinfo=UTC)
OLD = datetime(2026, 11, 1, 7, tzinfo=UTC)


@pytest.fixture(scope="module")
def reaper() -> types.ModuleType:
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda name: None  # type: ignore[attr-defined]
    sys.modules.setdefault("boto3", boto3)
    path = Path(__file__).parents[1] / "deploy/aws/bootstrap/reaper/reaper.py"
    spec = importlib.util.spec_from_file_location("reaper", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("tags", "created", "want"),
    [
        ({"mycel-session": "mycel", "mycel-expires": "2026-11-01T11:59:00Z"}, FRESH, True),
        ({"mycel-session": "mycel", "mycel-expires": "2026-11-01T12:01:00Z"}, OLD, False),
        ({"mycel-expires": "2026-11-01T11:00:00Z"}, OLD, False),
        ({"mycel-session": "mycel"}, FRESH, False),
        ({"mycel-session": "mycel"}, OLD, True),
        ({"mycel-session": "mycel", "mycel-expires": "soon"}, OLD, True),
    ],
    ids=["past", "extended", "not-a-session", "no-expiry-fresh", "no-expiry-old", "unreadable"],
)
def test_expired(
    reaper: types.ModuleType, tags: dict[str, str], created: datetime, want: bool
) -> None:
    assert reaper.expired(tags, created, NOW) is want
