"""A Jira or auth failure clears a person's access; a bug in our own code raises."""

from contextlib import asynccontextmanager
from typing import Any

import pytest

import mycel.services.access as access
import mycel.services.jira_oauth as jira_oauth

pytestmark = pytest.mark.anyio


def _setup(monkeypatch: pytest.MonkeyPatch, error: Exception) -> list[frozenset[str]]:
    written: list[frozenset[str]] = []

    async def token_for(user_id: int) -> Any:
        raise error

    class Repo:
        def __init__(self, session: object) -> None: ...

        async def replace_projects(self, user_id: int, projects: frozenset[str]) -> None:
            written.append(projects)

    @asynccontextmanager
    async def scope():  # type: ignore[no-untyped-def]
        yield None

    monkeypatch.setattr(jira_oauth, "token_for", token_for)
    monkeypatch.setattr(access, "AccountRepository", Repo)
    monkeypatch.setattr(access, "session_scope", scope)
    return written


class TestRefresh:
    async def test_not_connected_clears_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        written = _setup(monkeypatch, jira_oauth.NotConnected("gone"))

        assert await access.refresh(1) == frozenset()
        assert written == [frozenset()]

    async def test_a_bug_raises_and_keeps_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        written = _setup(monkeypatch, KeyError("typo"))

        with pytest.raises(KeyError):
            await access.refresh(1)
        assert written == []
