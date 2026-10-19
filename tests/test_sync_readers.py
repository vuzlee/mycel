"""The sync reads Jira on connected people's tokens: each project once, a bad token skipped."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

import mycel.plugins.jira.sync as sync
from mycel.plugins.jira import oauth as jira_oauth
from mycel.services.fetch import FetchResult

pytestmark = pytest.mark.anyio


def test_each_project_is_read_once_by_the_first_who_may_browse_it() -> None:
    plan = sync.readers({2: frozenset({"B", "C"}), 1: frozenset({"A", "B"})})
    assert plan == {1: ["A", "B"], 2: ["C"]}


def test_someone_who_adds_no_project_reads_nothing() -> None:
    assert sync.readers({1: frozenset({"A"}), 2: frozenset({"A"}), 3: frozenset()}) == {1: ["A"]}


async def test_a_revoked_token_is_skipped_and_the_rest_still_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read: list[list[str]] = []

    async def token_for(user_id: int) -> tuple[str, str]:
        if user_id == 1:
            raise jira_oauth.NotConnected("revoked")
        return "token", "cloud"

    async def fetch(_: Any, __: Any, projects: list[str], ___: Any) -> FetchResult:
        read.append(projects)
        return FetchResult(issues=len(projects), worklogs=0, keys=projects)

    @asynccontextmanager
    async def scope() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(jira_oauth, "token_for", token_for)
    monkeypatch.setattr(sync, "fetch_jira", fetch)
    monkeypatch.setattr(sync, "session_scope", scope)

    result = await sync._fetch_all({1: ["A"], 2: ["B"]}, None)

    assert read == [["B"]]
    assert result.keys == ["B"]
