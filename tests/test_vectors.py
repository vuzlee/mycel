"""Search over gold: the id, the skip, the filter, and the tool around them."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai import ModelRetry

import mycel.infra.vectors.collections as collections
import mycel.infra.vectors.indexer as indexer
import mycel.infra.vectors.search as search
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.tools.rag_search import MAX_RESULTS, build_toolset
from mycel.infra.postgres.repositories.gold import WorkItemRow
from mycel.llm.budget import JobBudget

pytestmark = pytest.mark.anyio


def _item(key: str, updated: datetime, title: str = "Login times out on mobile") -> WorkItemRow:
    return WorkItemRow(
        source="jira",
        project="MYC",
        issue_id="1",
        issue_key=key,
        kind="Task",
        parent_key=None,
        title=title,
        status="In Progress",
        status_category="doing",
        priority="High",
        sprint_id=1,
        sprint_name="Sprint 0",
        sprint_state="active",
        assignee_account_id="a1",
        assignee_name="Vu",
        original_estimate_seconds=None,
        time_spent_seconds=None,
        due_at=None,
        created_at=updated,
        resolved_at=None,
        labels=["auth"],
        updated_at=updated,
    )


class FakeQdrant:
    """Enough of the async client to answer, and to record what it was asked."""

    def __init__(self, points: dict[str, dict[str, Any]] | None = None) -> None:
        self.points = points or {}
        self.upserted: list[Any] = []
        self.filters: list[Any] = []
        self.created: list[str] = []

    async def collection_exists(self, name: str) -> bool:
        return name in self.created or bool(self.points)

    async def create_collection(self, name: str, vectors_config: Any) -> None:
        self.created.append(name)

    async def retrieve(
        self, collection: str, ids: list[str], with_payload: bool, with_vectors: bool
    ) -> list[Any]:
        class _Point:
            def __init__(self, pid: str, payload: dict[str, Any]) -> None:
                self.id = pid
                self.payload = payload

        return [_Point(pid, self.points[pid]) for pid in ids if pid in self.points]

    async def upsert(self, collection: str, points: list[Any]) -> None:
        self.upserted.extend(points)

    async def query_points(
        self, collection: str, query: Any, query_filter: Any, limit: int, with_payload: bool
    ) -> Any:
        self.filters.append(query_filter)

        class _Scored:
            def __init__(self, payload: dict[str, Any], score: float) -> None:
                self.payload = payload
                self.score = score

        class _Result:
            def __init__(self, points: list[Any]) -> None:
                self.points = points

        return _Result([_Scored(p, 0.9) for p in list(self.points.values())[:limit]])


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeQdrant:
    """A client in place of the real one, and embeddings that cost nothing."""
    client = FakeQdrant()
    monkeypatch.setattr(indexer, "client", lambda: client)
    monkeypatch.setattr(search, "client", lambda: client)
    monkeypatch.setattr(indexer, "embed", lambda texts: [[0.1] * 384 for _ in texts])
    monkeypatch.setattr(search, "embed", lambda texts: [[0.1] * 384 for _ in texts])
    return client


class TestTheId:
    def test_the_same_item_always_gets_the_same_id(self) -> None:
        """What makes a re-run an overwrite rather than a second copy."""
        first = indexer.point_id("jira", "MYC-1")
        assert first == indexer.point_id("jira", "MYC-1")

    def test_different_items_get_different_ids(self) -> None:
        assert indexer.point_id("jira", "MYC-1") != indexer.point_id("jira", "MYC-2")

    def test_the_source_is_part_of_the_key(self) -> None:
        """Two sources could number their issues the same way; gold's natural key is both."""
        assert indexer.point_id("jira", "MYC-1") != indexer.point_id("github", "MYC-1")


class TestOnlyWhatMoved:
    async def test_an_unchanged_item_is_not_embedded_again(self, fake: FakeQdrant) -> None:
        when = datetime(2026, 10, 1, tzinfo=UTC)
        item = _item("MYC-1", when)
        fake.points[indexer.point_id("jira", "MYC-1")] = {"updated_at": when.timestamp()}

        result = await indexer.index_items([item])

        assert result.embedded == 0
        assert result.skipped == 1
        assert fake.upserted == []

    async def test_a_changed_item_is_embedded(self, fake: FakeQdrant) -> None:
        when = datetime(2026, 10, 1, tzinfo=UTC)
        fake.points[indexer.point_id("jira", "MYC-1")] = {"updated_at": when.timestamp()}

        result = await indexer.index_items([_item("MYC-1", when + timedelta(minutes=1))])

        assert result.embedded == 1
        assert len(fake.upserted) == 1

    async def test_an_unknown_item_is_embedded(self, fake: FakeQdrant) -> None:
        result = await indexer.index_items([_item("MYC-9", datetime(2026, 10, 1, tzinfo=UTC))])
        assert result.embedded == 1

    async def test_nothing_in_means_nothing_done(self, fake: FakeQdrant) -> None:
        """A quiet tick must not create a collection or call the model."""
        result = await indexer.index_items([])
        assert (result.seen, result.embedded) == (0, 0)
        assert fake.created == []


class TestWhatGetsEmbedded:
    def test_the_title_leads(self) -> None:
        """Most of the meaning is in the title, and a model weights early tokens more."""
        text = indexer.document(_item("MYC-1", datetime(2026, 10, 1, tzinfo=UTC)))
        assert text.startswith("Login times out on mobile")

    def test_fields_are_labelled(self) -> None:
        """So "Done" as a status does not collide with "done" in a title."""
        text = indexer.document(_item("MYC-1", datetime(2026, 10, 1, tzinfo=UTC)))
        assert "status: In Progress (doing)" in text
        assert "labels: auth" in text

    def test_seconds_are_not_in_it(self) -> None:
        """A number embeds as noise. Nobody searches for "28800 seconds"; run_sql does."""
        item = _item("MYC-1", datetime(2026, 10, 1, tzinfo=UTC))
        text = indexer.document(item)
        assert "28800" not in text
        assert "seconds" not in text

    def test_the_payload_carries_the_timestamp_as_a_number(self) -> None:
        """So the next pass compares without parsing a string."""
        when = datetime(2026, 10, 1, tzinfo=UTC)
        assert indexer.payload(_item("MYC-1", when))["updated_at"] == when.timestamp()


class TestTheFilterReachesQdrant:
    async def test_the_projects_are_a_filter_not_a_post_step(self, fake: FakeQdrant) -> None:
        """Asserted on what the client was handed."""
        fake.points["x"] = {"issue_key": "MYC-1", "title": "t", "project": "MYC"}

        await search.search("flaky login", projects=["MYC", "OPS"], limit=5)

        sent = fake.filters[0]
        assert any(
            getattr(c, "key", None) == "project" and set(c.match.any) == {"MYC", "OPS"}
            for c in sent.must
        )

    async def test_no_projects_searches_nothing(self, fake: FakeQdrant) -> None:
        """Written as an early return, not as an empty filter."""
        fake.points["x"] = {"issue_key": "MYC-1", "title": "t", "project": "MYC"}

        assert await search.search("anything", projects=[], limit=5) == []
        assert fake.filters == []

    async def test_a_status_narrows_further(self, fake: FakeQdrant) -> None:
        fake.points["x"] = {"issue_key": "MYC-1", "title": "t", "project": "MYC"}

        await search.search("q", projects=["MYC"], limit=5, status_category="done")

        assert any(getattr(c, "key", None) == "status_category" for c in fake.filters[0].must)

    async def test_an_unindexed_collection_is_empty_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deployment that has never run the indexer has no answers."""
        empty = FakeQdrant()
        monkeypatch.setattr(search, "client", lambda: empty)
        monkeypatch.setattr(search, "embed", lambda texts: [[0.1] * 384])

        assert await search.search("q", projects=["MYC"], limit=5) == []


class TestTheCollectionName:
    def test_the_name_carries_the_model(self) -> None:
        """The dimension belongs to the model."""
        small = collections.work_items("BAAI/bge-small-en-v1.5")
        base = collections.work_items("BAAI/bge-base-en-v1.5")
        assert small.name != base.name
        assert (small.dimensions, base.dimensions) == (384, 768)

    def test_an_unknown_model_is_refused_at_the_name(self) -> None:
        """Rather than at the first write, where the error is about a vector size."""
        with pytest.raises(ValueError, match="unknown embedding model"):
            collections.work_items("some/model")


def _deps() -> MycelDeps:
    return MycelDeps(
        job_id="j1",
        budget=JobBudget("j1", Decimal("1")),
        settings=AgentSettings(repeat_threshold=99),
    )


async def _call(tool_fn: Any, **kwargs: Any) -> str:
    from pydantic_ai import RunContext
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.usage import RunUsage

    ctx: RunContext[MycelDeps] = RunContext(
        deps=_deps(), model=TestModel(), usage=RunUsage(), prompt=""
    )
    return str(await tool_fn(ctx, **kwargs))


class TestTheTool:
    @pytest.fixture
    def tool(self) -> Any:
        return build_toolset().tools["rag_search"].function

    async def test_no_principal_searches_nothing(self, tool: Any, fake: FakeQdrant) -> None:
        """The same fail-closed direction run_sql takes."""
        out = await _call(tool, query="flaky login")
        assert "No projects are readable" in out
        assert fake.filters == []

    async def test_an_empty_query_asks_the_model_again(self, tool: Any) -> None:
        with pytest.raises(ModelRetry):
            await _call(tool, query="   ")

    async def test_a_zero_limit_asks_the_model_again(self, tool: Any) -> None:
        with pytest.raises(ModelRetry):
            await _call(tool, query="x", limit=0)

    async def test_the_two_empty_cases_read_differently(self) -> None:
        """ "You may see nothing" reported as "nothing exists" is the system claiming work is absent
        when the asker simply cannot see it.
        """
        from mycel.agents.tools.rag_search import _render

        forbidden = _render([], query="q", asked=5, capped=5, scoped=False)
        nothing = _render([], query="q", asked=5, capped=5, scoped=True)
        assert forbidden != nothing
        assert "readable" in forbidden
        assert "Nothing indexed" in nothing

    def test_a_large_limit_is_capped_and_said_so(self) -> None:
        from mycel.agents.tools.rag_search import _render

        hit = search.Hit(
            issue_key="MYC-1",
            title="t",
            status="Done",
            kind="Task",
            project="MYC",
            assignee_name=None,
            sprint_name=None,
            score=0.9,
        )
        out = _render([hit], query="q", asked=100, capped=MAX_RESULTS, scoped=True)
        assert f"{MAX_RESULTS} is the most" in out
