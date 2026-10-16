"""Which work answers may be replayed, and what their key depends on."""

from datetime import UTC, datetime
from typing import Any

import pytest

from mycel.core.chips import Chip
from mycel.domains import chat_cache
from mycel.infra.postgres.repositories.accounts import SyncStateRow

pytestmark = pytest.mark.anyio


@pytest.fixture
def synced(monkeypatch: pytest.MonkeyPatch) -> list[datetime | None]:
    """The last successful sync the version is built from."""
    at: list[datetime | None] = [datetime(2026, 10, 16, 9, tzinfo=UTC)]

    class _Repo:
        def __init__(self, session: Any) -> None: ...

        async def sync_state(self) -> SyncStateRow:
            return SyncStateRow(at[0], None, None)

    class _Scope:
        async def __aenter__(self) -> None: ...

        async def __aexit__(self, *exc: object) -> None: ...

    monkeypatch.setattr(chat_cache, "AccountRepository", _Repo)
    monkeypatch.setattr(chat_cache, "session_scope", _Scope)
    return at


async def test_a_jira_question_is_keyed_on_the_last_sync(synced: list[Any]) -> None:
    before = await chat_cache.version(frozenset({Chip.JIRA}))
    synced[0] = datetime(2026, 10, 16, 10, tzinfo=UTC)
    after = await chat_cache.version(frozenset({Chip.JIRA}))
    assert before and after and before != after


@pytest.mark.parametrize(
    "chips",
    [None, frozenset({Chip.KNOWLEDGE}), frozenset({Chip.JIRA, Chip.MAIL})],
)
async def test_sources_with_no_sync_to_key_on_are_not_cached(
    synced: list[Any], chips: frozenset[Chip] | None
) -> None:
    assert await chat_cache.version(chips) is None


def test_a_turn_that_drafted_a_write_is_not_kept() -> None:
    steps = [{"type": "tool_called", "payload": {"tool": "draft_jira_write"}}]
    assert not chat_cache.keepable(steps)


def test_a_turn_that_only_read_is_kept() -> None:
    steps = [{"type": "tool_called", "payload": {"tool": "hours_by_person"}}]
    assert chat_cache.keepable(steps)
