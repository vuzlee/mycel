"""The index against a real Qdrant — the half `test_vectors.py` cannot prove."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from mycel.core.config import get_settings
from mycel.infra.postgres.repositories.gold import WorkItemRow
from mycel.infra.vectors import client, collections, indexer, search

pytestmark = pytest.mark.anyio

QDRANT_URL = os.environ.get("QDRANT_URL", "")

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not QDRANT_URL, reason="QDRANT_URL is unset; see this file's docstring"),
]


def _item(key: str, title: str, updated: datetime, project: str = "MYC") -> WorkItemRow:
    return WorkItemRow(
        source="jira",
        project=project,
        issue_id=key,
        issue_key=key,
        kind="Task",
        parent_key=None,
        title=title,
        status="In Progress",
        status_category="doing",
        priority=None,
        sprint_id=None,
        sprint_name=None,
        sprint_state=None,
        assignee_account_id=None,
        assignee_name=None,
        original_estimate_seconds=None,
        time_spent_seconds=None,
        due_at=None,
        created_at=updated,
        resolved_at=None,
        labels=[],
        updated_at=updated,
    )


@pytest.fixture
async def clean() -> AsyncIterator[None]:
    """A collection with nothing in it, dropped again afterwards."""
    get_settings.cache_clear()
    collection = collections.work_items(get_settings().embedding_model)
    qdrant = client.client()
    if await qdrant.collection_exists(collection.name):
        await qdrant.delete_collection(collection.name)
    yield
    if await qdrant.collection_exists(collection.name):
        await qdrant.delete_collection(collection.name)
    await client.close()


WHEN = datetime(2026, 10, 1, tzinfo=UTC)


class TestTheIndex:
    async def test_running_it_twice_leaves_one_point(self, clean: None) -> None:
        """The whole of the idempotence claim, decided by the server rather than by us."""
        items = [_item("MYC-1", "Login times out on mobile", WHEN)]

        first = await indexer.index_items(items)
        second = await indexer.index_items(items)

        assert first.embedded == 1
        assert second.embedded == 0, "nothing moved, so nothing should have been embedded"

        collection = collections.work_items(get_settings().embedding_model)
        count = await client.client().count(collection.name)
        assert count.count == 1, "the same key must overwrite, not accumulate"

    async def test_an_edited_item_overwrites_its_point(self, clean: None) -> None:
        await indexer.index_items([_item("MYC-1", "Login times out", WHEN)])
        await indexer.index_items(
            [_item("MYC-1", "Session expires early on mobile", WHEN + timedelta(minutes=1))]
        )

        collection = collections.work_items(get_settings().embedding_model)
        assert (await client.client().count(collection.name)).count == 1

        hits = await search.search("session expiry", projects=["MYC"], limit=5)
        assert [h.title for h in hits] == ["Session expires early on mobile"]

    async def test_the_vector_is_the_declared_size(self, clean: None) -> None:
        """A dimension mismatch is refused by Qdrant."""
        await indexer.index_items([_item("MYC-1", "anything", WHEN)])

        collection = collections.work_items(get_settings().embedding_model)
        info = await client.client().get_collection(collection.name)
        assert info.config.params.vectors.size == collection.dimensions


class TestSearch:
    async def test_meaning_beats_keywords(self, clean: None) -> None:
        """The reason this tool exists at all."""
        await indexer.index_items(
            [
                _item("MYC-1", "Session expires early on mobile", WHEN),
                _item("MYC-2", "Invoice PDF renders with the wrong font", WHEN),
            ]
        )

        hits = await search.search("users keep getting logged out", projects=["MYC"], limit=1)

        assert [h.issue_key for h in hits] == ["MYC-1"]

    async def test_the_filter_runs_inside_the_search(self, clean: None) -> None:
        """THE test of this file."""
        await indexer.index_items(
            [
                _item("OPS-1", "Login times out", WHEN, project="OPS"),
                _item("OPS-2", "Login is slow", WHEN, project="OPS"),
                _item("OPS-3", "Login fails intermittently", WHEN, project="OPS"),
                _item("MYC-1", "Session expires early", WHEN),
                _item("MYC-2", "Auth redirect loops", WHEN),
                _item("MYC-3", "Token refresh is unreliable", WHEN),
            ]
        )

        hits = await search.search("login problems", projects=["MYC"], limit=3)

        assert len(hits) == 3, "post-filtering would have returned fewer"
        assert {h.project for h in hits} == {"MYC"}

    async def test_a_forbidden_project_returns_nothing(self, clean: None) -> None:
        await indexer.index_items([_item("OPS-1", "Login times out", WHEN, project="OPS")])

        assert await search.search("login", projects=["MYC"], limit=5) == []

    async def test_a_status_narrows_the_result(self, clean: None) -> None:
        done = _item("MYC-2", "Login times out on mobile", WHEN)
        done = WorkItemRow(**{**done.__dict__, "status": "Done", "status_category": "done"})
        await indexer.index_items([_item("MYC-1", "Login times out on desktop", WHEN), done])

        hits = await search.search("login", projects=["MYC"], limit=5, status_category="done")

        assert [h.issue_key for h in hits] == ["MYC-2"]
