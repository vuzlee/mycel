"""The Jira write tools, and the draft store under them.

One claim matters more than everything else here: **`draft_jira_write` writes nothing**.
That is the whole reason the write is split in two, and the stake is higher than it is for
the calendar — a wrong event is deleted in a second, while Jira records an author and
offers no way to correct one. So the fake transport is asked not what it was sent but
*whether it was called at all*.

Around that:

**A draft is resolved before it is read back, not after it is agreed to.** An account id
looked up at confirm time would mean the person agreed to "Nam" and the system wrote to
whichever Nam it found a minute later — exactly the mistake the read-back exists to catch.

**A draft belongs to one person and is spent once.** The id travels through a prompt, which
is the least trustworthy place in the system for one to travel.

**Not connected is a sentence, not an exception.** A person who never consented still asked
something, and raising would end the job over the half of it that is answerable.

**A refused write gives the draft back; a timed-out one does not.** Those two are one
line apart in the code and opposite in consequence — getting the second wrong posts the
same comment twice, which is the exact thing this whole batch exists to prevent.

**`create_project` is absent unless the deployment armed it**, and absent means absent: a
tool the model cannot see is a tool it cannot be talked into using.

No Redis and no network: the draft store gets an in-memory client, and Jira gets a
transport that records rather than answers.
"""

from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic_ai import ModelRetry

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.tools.jira import CONNECT, build_toolset, offered
from mycel.core.config import get_settings
from mycel.infra.redis import drafts
from mycel.llm.budget import JobBudget
from mycel.services.auth import Principal
from mycel.sources import jira

pytestmark = pytest.mark.anyio

_REAL_CLIENT = httpx2.AsyncClient


class FakeRedis:
    """Enough of the client for `drafts.py`: set with a TTL, and read-and-delete.

    The TTL is recorded rather than honoured — nothing here waits ten minutes, and what a
    test wants to know is that an expiry was asked for at all.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


class Calls:
    """Every request that reached Jira, with a canned answer per path.

    Keyed by a fragment of the path rather than by the whole url, because the url carries
    a cloud id and a test that asserts one is testing the wrong thing.
    """

    def __init__(self, answers: dict[str, Any] | None = None, status: int = 200) -> None:
        self.requests: list[httpx2.Request] = []
        self.answers = answers or {}
        self.status = status

    def client(self, **kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=httpx2.MockTransport(self._handle), **kwargs)

    @property
    def written(self) -> list[httpx2.Request]:
        """Only the calls that change something. A lookup is not a write."""
        return [r for r in self.requests if r.method in ("POST", "PUT")]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        for fragment, payload in self.answers.items():
            if fragment in str(request.url):
                return httpx2.Response(self.status, json=payload)
        return httpx2.Response(self.status, json={})


#: Whoever the run is for, unless a test says otherwise.
ASKER = Principal(id=7, email="dev@example.com")


@pytest.fixture(autouse=True)
def armed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Writing on, project creation off — the ordinary armed deployment."""
    monkeypatch.setenv("JIRA_WRITE_ENABLED", "true")
    monkeypatch.delenv("JIRA_ALLOW_CREATE_PROJECT", raising=False)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()

    async def _get_client() -> FakeRedis:
        return fake

    monkeypatch.setattr(drafts, "get_client", _get_client)
    return fake


@pytest.fixture(autouse=True)
def grant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everyone is connected unless a test says otherwise."""
    from mycel.agents.tools import jira as tool

    async def _token(user_id: int) -> tuple[str, str]:
        return "access-token", "cloud-1"

    monkeypatch.setattr(tool, "token_for", _token)


def _ctx(principal: Principal | None = ASKER) -> Any:
    class _Ctx:
        deps = MycelDeps(
            job_id="job-1",
            budget=JobBudget("job-1", Decimal("1.00")),
            settings=AgentSettings(model_spec="local:qwen3-4b"),
            principal=principal,
        )
        messages: list[Any] = []

    return _Ctx()


@pytest.fixture
def ctx() -> Any:
    return _ctx()


@pytest.fixture
def tools() -> dict[str, Any]:
    toolset = build_toolset()
    return {name: tool.function for name, tool in toolset.tools.items()}


class TestDraftingWritesNothing:
    """The reason the write is split in two, asserted the only way that means anything."""

    async def test_a_drafted_comment_never_reaches_jira(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = Calls()
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        out = await tools["draft_jira_write"](
            ctx, kind="comment", issue_key="MYC-12", text="shipped"
        )

        assert calls.written == [], "drafting must not write to Jira"
        assert "Nothing written yet" in out

    async def test_a_drafted_issue_never_reaches_jira(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = Calls()
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        await tools["draft_jira_write"](
            ctx, kind="issue", project="myc", summary="fix the login timeout"
        )

        assert calls.written == [], "drafting an issue must not create one"

    async def test_the_draft_is_kept_with_an_expiry(
        self, tools: dict[str, Any], ctx: Any, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An abandoned draft must disappear on its own — there is nothing to clean up."""
        monkeypatch.setattr(httpx2, "AsyncClient", Calls().client)

        await tools["draft_jira_write"](ctx, kind="comment", issue_key="MYC-12", text="done")

        assert list(redis.ttls.values()) == [drafts.DRAFT_TTL_S]


class TestWhatTheDraftReadsBack:
    async def test_an_assignee_is_spelled_by_name_not_by_id(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An id reads back as noise. A person catches the wrong Nam only from a name."""
        calls = Calls({"/user/search": [{"accountId": "acct-9", "displayName": "Nam Nguyen"}]})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        out = await tools["draft_jira_write"](
            ctx,
            kind="issue",
            project="MYC",
            summary="fix the login timeout",
            assignee_account_id="acct-9",
        )

        assert "Nam Nguyen" in out
        assert "acct-9" not in out

    async def test_a_move_the_workflow_forbids_is_refused_before_anyone_agrees(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Checked at draft time: refusing after a yes is refusing too late, and the list
        of allowed moves is what tells the model which word to use instead."""
        moves = {"transitions": [{"id": "31", "to": {"name": "In Progress"}}]}
        monkeypatch.setattr(httpx2, "AsyncClient", Calls({"/transitions": moves}).client)

        with pytest.raises(ModelRetry) as caught:
            await tools["draft_jira_write"](ctx, kind="move", issue_key="MYC-12", to_status="Done")

        assert "In Progress" in str(caught.value)

    async def test_a_missing_argument_is_named(self, tools: dict[str, Any], ctx: Any) -> None:
        with pytest.raises(ModelRetry, match="text"):
            await tools["draft_jira_write"](ctx, kind="comment", issue_key="MYC-12")

    async def test_an_unknown_kind_is_sent_back(self, tools: dict[str, Any], ctx: Any) -> None:
        with pytest.raises(ModelRetry, match="comment"):
            await tools["draft_jira_write"](ctx, kind="archive", issue_key="MYC-12")


class TestConfirming:
    async def test_a_confirmed_comment_is_written(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = Calls({"/comment": {"id": "10200"}})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        drafted = await tools["draft_jira_write"](
            ctx, kind="comment", issue_key="MYC-12", text="shipped"
        )
        out = await tools["confirm_jira_write"](ctx, draft_id=_id_in(drafted))

        assert [str(r.url).split("/rest/api/3")[1] for r in calls.written] == [
            "/issue/MYC-12/comment"
        ]
        assert "MYC-12" in out

    async def test_a_draft_is_spent_once(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An enthusiastic "yes, do it" twice over must leave one comment, not two."""
        calls = Calls({"/comment": {"id": "10200"}})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        drafted = await tools["draft_jira_write"](
            ctx, kind="comment", issue_key="MYC-12", text="shipped"
        )
        draft_id = _id_in(drafted)
        await tools["confirm_jira_write"](ctx, draft_id=draft_id)
        again = await tools["confirm_jira_write"](ctx, draft_id=draft_id)

        assert len(calls.written) == 1
        assert "Nothing was written" in again

    async def test_a_draft_cannot_be_spent_by_somebody_else(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The id travels through a prompt, so a leaked one must not write under a name
        that never agreed to anything."""
        calls = Calls({"/comment": {"id": "10200"}})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        drafted = await tools["draft_jira_write"](
            ctx, kind="comment", issue_key="MYC-12", text="shipped"
        )
        stranger = _ctx(Principal(id=99, email="else@example.com"))
        out = await tools["confirm_jira_write"](stranger, draft_id=_id_in(drafted))

        assert calls.written == []
        assert "Nothing was written" in out

    async def test_an_unknown_draft_writes_nothing_and_says_so(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = Calls()
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        out = await tools["confirm_jira_write"](ctx, draft_id="never-existed")

        assert calls.written == []
        assert "Nothing was written" in out

    async def test_a_refused_write_is_a_failure_not_a_sentence(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model that reads "could not" as "did not matter" reports the task as done."""
        monkeypatch.setattr(httpx2, "AsyncClient", Calls({"/comment": {}}).client)
        drafted = await tools["draft_jira_write"](
            ctx, kind="comment", issue_key="MYC-12", text="shipped"
        )

        monkeypatch.setattr(httpx2, "AsyncClient", Calls({}, status=403).client)
        with pytest.raises(ToolFailed):
            await tools["confirm_jira_write"](ctx, draft_id=_id_in(drafted))


class TestWhatAFailedWriteCostsThePerson:
    """A draft is spent before the write is attempted. What happens next depends on
    whether the write can possibly have landed — and those two cases must not be
    collapsed, in either direction."""

    async def _drafted(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> str:
        monkeypatch.setattr(httpx2, "AsyncClient", Calls({"/comment": {"id": "1"}}).client)
        out = await tools["draft_jira_write"](
            ctx, kind="comment", issue_key="MYC-12", text="shipped"
        )
        return _id_in(out)

    async def test_a_refused_write_gives_the_draft_back(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """They already read the change back and already agreed to it. A 403 should not
        make them do the whole round again."""
        draft_id = await self._drafted(tools, ctx, monkeypatch)

        monkeypatch.setattr(httpx2, "AsyncClient", Calls({}, status=403).client)
        with pytest.raises(ToolFailed) as caught:
            await tools["confirm_jira_write"](ctx, draft_id=draft_id)

        assert "Nothing was written" in str(caught.value)
        # The id has to be IN the sentence, or the model drafts afresh instead of retrying.
        assert draft_id in str(caught.value)

        # And it really is retryable: the same id, and this time Jira answers.
        calls = Calls({"/comment": {"id": "10200"}})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)
        out = await tools["confirm_jira_write"](ctx, draft_id=draft_id)

        assert len(calls.written) == 1
        assert "MYC-12" in out

    async def test_a_timeout_does_not_give_the_draft_back(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dangerous half. A timed-out request may well have landed, so offering a
        retry is offering to post the same comment twice."""
        draft_id = await self._drafted(tools, ctx, monkeypatch)

        def slow(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.TimeoutException("too slow")

        def client(**kwargs: Any) -> httpx2.AsyncClient:
            kwargs.pop("transport", None)
            return _REAL_CLIENT(transport=httpx2.MockTransport(slow), **kwargs)

        monkeypatch.setattr(httpx2, "AsyncClient", client)
        with pytest.raises(ToolFailed) as caught:
            await tools["confirm_jira_write"](ctx, draft_id=draft_id)

        assert "not known whether this was written" in str(caught.value)

        # The draft is gone, so a second yes writes nothing rather than writing twice.
        calls = Calls({"/comment": {"id": "10200"}})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)
        out = await tools["confirm_jira_write"](ctx, draft_id=draft_id)

        assert calls.written == []
        assert "Nothing was written" in out

    async def test_a_restored_draft_still_expires(
        self, tools: dict[str, Any], ctx: Any, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Coming back must not make it permanent — it is still a draft nobody confirmed."""
        draft_id = await self._drafted(tools, ctx, monkeypatch)

        monkeypatch.setattr(httpx2, "AsyncClient", Calls({}, status=403).client)
        with pytest.raises(ToolFailed):
            await tools["confirm_jira_write"](ctx, draft_id=draft_id)

        assert list(redis.ttls.values()) == [drafts.DRAFT_TTL_S]


class TestWhenNobodyIsConnected:
    async def test_a_run_with_no_principal_is_told_to_connect(
        self, tools: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A forgotten principal must never borrow somebody else's name."""
        calls = Calls()
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        out = await tools["draft_jira_write"](
            _ctx(None), kind="comment", issue_key="MYC-12", text="shipped"
        )

        assert out == CONNECT
        assert calls.requests == []

    async def test_an_unconnected_person_gets_a_sentence_not_an_exception(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mycel.agents.tools import jira as tool
        from mycel.services.jira_oauth import NotConnected

        async def _refuse(user_id: int) -> tuple[str, str]:
            raise NotConnected("nope")

        monkeypatch.setattr(tool, "token_for", _refuse)
        monkeypatch.setattr(httpx2, "AsyncClient", Calls().client)

        out = await tools["draft_jira_write"](
            ctx, kind="comment", issue_key="MYC-12", text="shipped"
        )

        assert out == CONNECT


class TestTheTwoSwitches:
    def test_writing_off_means_the_tools_are_not_offered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not refused — absent. A tool the model can see costs a turn to find out."""
        monkeypatch.setenv("JIRA_WRITE_ENABLED", "false")
        get_settings.cache_clear()

        assert offered() is False

    def test_creating_a_project_is_off_by_default(self) -> None:
        """Its own switch, because it is the one write with no way back."""
        assert get_settings().jira_allow_create_project is False

    async def test_creating_a_project_is_refused_while_its_switch_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = Calls()
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        with pytest.raises(Exception, match="JIRA_ALLOW_CREATE_PROJECT"):
            await jira.create_project(
                jira.Auth("access-token", "cloud-1"), "NEW", "New thing", "acct-1"
            )

        assert calls.written == []

    def test_the_admin_scope_is_asked_for_only_when_it_is_armed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asking for everything up front, in case, is how a consent screen comes to
        describe an app that does not exist."""
        from mycel.services.jira_oauth import PROJECT_SCOPE, scopes

        assert PROJECT_SCOPE not in scopes()

        monkeypatch.setenv("JIRA_ALLOW_CREATE_PROJECT", "true")
        get_settings.cache_clear()

        assert PROJECT_SCOPE in scopes()


def _id_in(drafted: str) -> str:
    """The draft id out of the sentence the tool returned, as the model would read it."""
    return drafted.split("draft_id=")[1].strip().rstrip(".")
