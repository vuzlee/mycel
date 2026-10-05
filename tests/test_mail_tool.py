"""`read_mail`, and the connector under it, against a fake Gmail API.

Three claims are worth proving here and none is about the model's judgement.

**Whose inbox is the asker's.** It used to be one mailbox from `.env`, so every user read
the maintainer's mail. The token handed to Gmail must be the asker's own, and a run with
nobody behind it — or nobody connected — reads nothing.

**Headers only.** `format=metadata` with three named headers is what keeps a body out; the
fake records what was asked of it.

**The window comes from the question.** "This week" and "today" are different questions,
so the hours asked for must reach the search and the cap must hold.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from typing import Any

import pytest
from pydantic_ai import ModelRetry

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.tools import mail as mail_tool
from mycel.agents.tools.mail import CONNECT, MAX_HOURS, MAX_MESSAGES, build_toolset
from mycel.llm.budget import JobBudget
from mycel.services.auth import Principal
from mycel.services.google_oauth import NotConnected
from mycel.sources import gmail

pytestmark = pytest.mark.anyio

ASKER = Principal(id=7, email="dev@example.com")


def now() -> datetime:
    return datetime.now(UTC)


class FakeGmail:
    """Answers the two calls the connector makes, and records them."""

    def __init__(self, messages: list[tuple[str, str, datetime]], status: int = 200) -> None:
        self.messages = {f"m{i}": m for i, m in enumerate(messages)}
        self.status = status
        self.calls: list[tuple[str, Any]] = []
        self.tokens: list[str] = []

    def client(self, headers: dict[str, str], **_: Any) -> "FakeGmail._Client":
        self.tokens.append(headers["authorization"])
        return FakeGmail._Client(self)

    class _Client:
        def __init__(self, outer: "FakeGmail") -> None:
            self.outer = outer

        async def __aenter__(self) -> "FakeGmail._Client":
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def get(self, url: str, params: Any) -> "FakeGmail._Response":
            self.outer.calls.append((url, params))
            if url.endswith("/messages"):
                after = int(dict(params)["q"].split(":")[1])
                ids = [
                    i for i, (_, _, at) in self.outer.messages.items() if at.timestamp() >= after
                ]
                return FakeGmail._Response(
                    self.outer.status,
                    {"messages": [{"id": i} for i in ids], "resultSizeEstimate": len(ids)},
                )
            sender, subject, at = self.outer.messages[url.rsplit("/", 1)[1]]
            headers = [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": format_datetime(at)},
            ]
            return FakeGmail._Response(self.outer.status, {"payload": {"headers": headers}})

    class _Response:
        def __init__(self, status: int, body: dict[str, Any]) -> None:
            self.status_code = status
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self.body


@pytest.fixture
def inbox() -> list[tuple[str, str, datetime]]:
    t = now()
    return [
        ("Nam <nam@example.com>", "Deploy is green", t - timedelta(hours=2)),
        ("Lan <lan@example.com>", "Invoice overdue", t - timedelta(hours=30)),
        ("Old <old@example.com>", "Last month", t - timedelta(days=40)),
    ]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, inbox: list[tuple[str, str, datetime]]) -> FakeGmail:
    fake = FakeGmail(inbox)
    monkeypatch.setattr(gmail.httpx2, "AsyncClient", fake.client)
    return fake


@pytest.fixture
def connected(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The asker has a Google grant; their token is `token-<id>`."""
    asked: list[int] = []

    async def token_for(user_id: int) -> str:
        asked.append(user_id)
        return f"token-{user_id}"

    monkeypatch.setattr(mail_tool, "token_for", token_for)
    return asked


def _ctx(principal: Principal | None) -> Any:
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
    return _ctx(ASKER)


@pytest.fixture
def read_mail() -> Any:
    return build_toolset().tools["read_mail"].function


class TestWhoseInbox:
    async def test_the_asker_s_own_token_reaches_gmail(
        self, read_mail: Any, ctx: Any, api: FakeGmail, connected: list[int]
    ) -> None:
        await read_mail(ctx, hours=24)

        assert connected == [ASKER.id]
        assert set(api.tokens) == {f"Bearer token-{ASKER.id}"}

    async def test_a_run_with_nobody_behind_it_reads_nothing(
        self, read_mail: Any, api: FakeGmail, connected: list[int]
    ) -> None:
        assert await read_mail(_ctx(None), hours=24) == CONNECT
        assert api.calls == [] and connected == []

    async def test_nobody_connected_is_told_how_not_given_another_inbox(
        self, read_mail: Any, ctx: Any, api: FakeGmail, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def not_connected(user_id: int) -> str:
            raise NotConnected("no Google account is connected")

        monkeypatch.setattr(mail_tool, "token_for", not_connected)

        assert await read_mail(ctx, hours=24) == CONNECT
        assert api.calls == []


class TestHeadersOnly:
    async def test_messages_are_asked_for_as_metadata_with_three_headers(
        self, api: FakeGmail
    ) -> None:
        await gmail.read_recent("t", hours=24, limit=MAX_MESSAGES)

        fetches = [
            dict(p) | {"h": [v for k, v in p if k == "metadataHeaders"]}
            for u, p in api.calls
            if not u.endswith("/messages")
        ]
        assert fetches
        assert all(f["format"] == "metadata" for f in fetches)
        assert all(f["h"] == ["From", "Subject", "Date"] for f in fetches)


class TestTheWindowComesFromTheQuestion:
    async def test_a_message_older_than_the_window_is_dropped(
        self, read_mail: Any, ctx: Any, api: FakeGmail, connected: list[int]
    ) -> None:
        text = await read_mail(ctx, hours=24)

        assert "Deploy is green" in text
        assert "Invoice overdue" not in text

    async def test_a_week_reaches_further_than_a_day(
        self, read_mail: Any, ctx: Any, api: FakeGmail, connected: list[int]
    ) -> None:
        text = await read_mail(ctx, hours=168)

        assert "Invoice overdue" in text
        assert "Last month" not in text

    async def test_asking_for_more_than_the_cap_says_so(
        self, read_mail: Any, ctx: Any, api: FakeGmail, connected: list[int]
    ) -> None:
        text = await read_mail(ctx, hours=MAX_HOURS * 2)

        assert f"{MAX_HOURS} is the most" in text

    async def test_a_window_of_nothing_is_refused(self, read_mail: Any, ctx: Any) -> None:
        with pytest.raises(ModelRetry):
            await read_mail(ctx, hours=0)


class TestWhatTheModelReads:
    async def test_every_line_carries_a_link(
        self, read_mail: Any, ctx: Any, api: FakeGmail, connected: list[int]
    ) -> None:
        text = await read_mail(ctx, hours=168)

        rows = [line for line in text.splitlines() if "@example.com" in line]
        assert rows and all("https://mail.google.com/" in r for r in rows)

    async def test_an_empty_mailbox_says_so(
        self, read_mail: Any, ctx: Any, monkeypatch: pytest.MonkeyPatch, connected: list[int]
    ) -> None:
        monkeypatch.setattr(gmail.httpx2, "AsyncClient", FakeGmail([]).client)

        assert "(no messages)" in await read_mail(ctx, hours=24)


class TestWhenTheMailboxCannotBeRead:
    async def test_a_grant_without_gmail_says_to_reconnect(
        self, read_mail: Any, ctx: Any, monkeypatch: pytest.MonkeyPatch, connected: list[int]
    ) -> None:
        """A grant made before mail was asked for answers 403; the fix is reconnecting."""
        monkeypatch.setattr(gmail.httpx2, "AsyncClient", FakeGmail([], status=403).client)

        with pytest.raises(ToolFailed, match="connect Google again"):
            await read_mail(ctx, hours=24)
