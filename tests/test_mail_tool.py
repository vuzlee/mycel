"""`read_mail`, and the connector under it, against a fake IMAP server.

Two claims are worth proving here and neither is about the model's judgement.

The first is **that nothing is marked read**. `BODY.PEEK` and `readonly=True` are one
string and one keyword, both easy to drop in a refactor, and the cost of dropping them is
a mailbox silently marked read — a failure nobody notices until it is far too late to
undo. So the fake records exactly what was asked of it.

The second is **that the window comes from the question**. The whole reason this stopped
being a cron at 08:00 is that "this week" and "today" are different questions, so the
hours a caller asks for must reach IMAP and the cap must hold.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai import ModelRetry

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.tools.mail import MAX_HOURS, MAX_MESSAGES, build_toolset
from mycel.core.config import get_settings
from mycel.llm.budget import JobBudget
from mycel.sources import SourceError, gmail

pytestmark = pytest.mark.anyio


def _raw(sender: str, subject: str, sent: datetime) -> bytes:
    """A header block shaped the way Gmail returns one."""
    stamp = sent.strftime("%a, %d %b %Y %H:%M:%S %z")
    return f"From: {sender}\r\nSubject: {subject}\r\nDate: {stamp}\r\n\r\n".encode()


class FakeIMAP:
    """Enough of `imaplib.IMAP4_SSL` to answer, and to say what it was asked."""

    def __init__(self, messages: dict[bytes, bytes]) -> None:
        self.messages = messages
        self.calls: list[tuple[Any, ...]] = []
        self.selected: tuple[str, bool] | None = None

    def login(self, address: str, password: str) -> None:
        self.calls.append(("login", address, password))

    def select(self, mailbox: str, readonly: bool = False) -> None:
        self.selected = (mailbox, readonly)

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        self.calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(self.messages)]
        uid = args[0].encode()
        return "OK", [(b"header", self.messages[uid])]

    def __enter__(self) -> "FakeIMAP":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def now() -> datetime:
    """Real time, because the connector windows against it and a frozen clock here would
    make the window test pass or fail depending on the hour the suite runs."""
    return datetime.now(UTC)


@pytest.fixture
def inbox(now: datetime) -> dict[bytes, bytes]:
    return {
        b"1": _raw("old@example.com", "Last month", now - timedelta(days=40)),
        b"2": _raw("boss@example.com", "Re: Q4 deadline", now - timedelta(hours=30)),
        b"3": _raw("ci@example.com", "build failed on main", now - timedelta(hours=2)),
    }


@pytest.fixture
def imap(monkeypatch: pytest.MonkeyPatch, inbox: dict[bytes, bytes]) -> FakeIMAP:
    """The fake, with credentials present so the connector gets as far as using it."""
    fake = FakeIMAP(inbox)
    monkeypatch.setattr(gmail.imaplib, "IMAP4_SSL", lambda host, timeout: fake)
    get_settings.cache_clear()
    monkeypatch.setenv("GMAIL_ADDRESS", "mycel@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    yield fake
    get_settings.cache_clear()


@pytest.fixture
def ctx() -> Any:
    class _Ctx:
        deps = MycelDeps(
            job_id="job-1",
            budget=JobBudget("job-1", Decimal("1.00")),
            settings=AgentSettings(model_spec="local:qwen3-4b"),
        )
        messages: list[Any] = []

    return _Ctx()


@pytest.fixture
def read_mail() -> Any:
    return build_toolset().tools["read_mail"].function


class TestNothingIsMarkedRead:
    """The failure that is invisible until it is permanent."""

    def test_the_fetch_asks_for_headers_and_peeks(self, imap: FakeIMAP) -> None:
        """One string carries the whole discipline: `PEEK` leaves the message unseen and
        `HEADER.FIELDS` is why no body ever reaches a model provider."""
        gmail.read_recent(hours=24, limit=MAX_MESSAGES)
        fetches = [call for call in imap.calls if call[0] == "FETCH"]
        assert fetches, "nothing was fetched"
        for call in fetches:
            assert call[2] == "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"

    def test_the_inbox_is_selected_read_only(self, imap: FakeIMAP) -> None:
        """Belt to PEEK's braces — either alone would do, which is the point."""
        gmail.read_recent(hours=24, limit=MAX_MESSAGES)
        assert imap.selected == ("INBOX", True)


class TestTheWindowComesFromTheQuestion:
    async def test_the_hours_asked_for_reach_the_search(
        self, read_mail: Any, ctx: Any, imap: FakeIMAP
    ) -> None:
        """A week back must search from a week back. This is the whole reason the batch
        dropped its scheduler."""
        await read_mail(ctx, hours=168)
        search = next(call for call in imap.calls if call[0] == "SEARCH")
        asked = datetime.strptime(search[2], "%d-%b-%Y").replace(tzinfo=UTC)
        assert (datetime.now(UTC) - asked).days >= 7

    async def test_a_message_older_than_the_window_is_dropped(
        self, read_mail: Any, ctx: Any, imap: FakeIMAP
    ) -> None:
        """IMAP's SINCE has a day's resolution, so it over-selects and the connector has
        to trim against the real timestamp."""
        out = await read_mail(ctx, hours=24)
        assert "build failed on main" in out
        assert "Re: Q4 deadline" not in out, "30 hours ago is outside a 24-hour window"

    async def test_asking_for_more_than_the_cap_says_so(
        self, read_mail: Any, ctx: Any, imap: FakeIMAP
    ) -> None:
        """Cost, not permission — so it answers with what it can and names the limit."""
        out = await read_mail(ctx, hours=10_000)
        assert str(MAX_HOURS) in out and "10000 hours was asked for" in out

    async def test_a_window_of_nothing_is_refused(self, read_mail: Any, ctx: Any) -> None:
        with pytest.raises(ModelRetry):
            await read_mail(ctx, hours=0)


class TestWhatTheModelReads:
    async def test_every_line_carries_a_link(
        self, read_mail: Any, ctx: Any, imap: FakeIMAP
    ) -> None:
        """The link is the source, in exactly the sense `validate_output` already means."""
        out = await read_mail(ctx, hours=720)
        for line in out.splitlines():
            if "|" in line and "Columns:" not in line:
                assert "https://mail.google.com/" in line

    async def test_the_total_is_reported_not_only_the_shown(
        self, read_mail: Any, ctx: Any, imap: FakeIMAP
    ) -> None:
        """Three worth reading out of forty-seven is a different claim from three of three,
        and the model cannot count what it was not shown."""
        out = await read_mail(ctx, hours=1)
        assert out.startswith("3 messages in the last 1 hours")

    async def test_an_empty_mailbox_says_so(self, read_mail: Any, ctx: Any, imap: FakeIMAP) -> None:
        """Silence reads as a failed call, and a model retries what did not fail."""
        imap.messages.clear()
        out = await read_mail(ctx, hours=24)
        assert "(no messages)" in out


class TestWhenTheMailboxCannotBeRead:
    async def test_missing_credentials_fail_rather_than_re_prompt(
        self, read_mail: Any, ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not the model's to fix: re-prompting would loop until the run dies unread.

        The run still survives — `tools/delegate.py` turns this into a gap.
        """
        get_settings.cache_clear()
        monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
        with pytest.raises(ToolFailed):
            await read_mail(ctx, hours=24)
        get_settings.cache_clear()

    def test_imap_disabled_is_reported_in_gmails_own_words(
        self, imap: FakeIMAP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The trap: login succeeds and select fails, so the error surfaces a step away
        from the setting that is actually wrong. Gmail's own wording is the useful part.
        """

        def _refuse(mailbox: str, readonly: bool = False) -> None:
            raise gmail.imaplib.IMAP4.error("IMAP access is disabled for this account")

        monkeypatch.setattr(imap, "select", _refuse)
        with pytest.raises(SourceError) as caught:
            gmail.read_recent(hours=24, limit=MAX_MESSAGES)
        assert "disabled" in str(caught.value)
