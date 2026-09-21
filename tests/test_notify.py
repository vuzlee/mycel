"""The two one-way outputs: a chat message, and a calendar entry.

Both exist to be ignorable. A deployment with neither configured runs unchanged, and a
failure in either must never take down the job whose result it was carrying — so most of
what is pinned here is what happens when they *do not* work.

No request leaves the machine: `httpx2.MockTransport` answers for both APIs, and the
Google credential is never constructed because nothing here has a key file.
"""

from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from mycel.agents.schemas import LoadLine, ProgressSummary, WorkLine
from mycel.core.config import Settings
from mycel.etl.normalise import JIRA
from mycel.infra.postgres.repositories.gold import SECONDS_PER_DAY, WorkItemRow
from mycel.notify import calendar, telegram

pytestmark = pytest.mark.anyio

#: Captured before any test patches the name, so the factory below builds a real client
#: rather than recursing into its own replacement.
_REAL_CLIENT = httpx2.AsyncClient


def _mock(handler: Any) -> Any:
    def _client(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=httpx2.MockTransport(handler), **kwargs)

    return _client


def _sent(sink: list[httpx2.Request], status: int = 200) -> Any:
    """Record every request and answer it, so a test can read what went out."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        sink.append(request)
        return httpx2.Response(status, json={"ok": status == 200})

    return _mock(handler)


def _summary(**kw: Any) -> ProgressSummary:
    fields: dict[str, Any] = {
        "period": "15-21 September 2026",
        "headline": "Schemas landed; the dashboard is five days late.",
        "health": "at_risk",
        "shipped": [WorkLine(key="MYC-8", title="Schemas", who="Dev One")],
        "in_flight": [WorkLine(key="MYC-7", title="Dashboard", who="Dev One")],
        "at_risk": [
            WorkLine(key="MYC-7", title="Dashboard", who="Dev One", note="five days past due")
        ],
        "load": [LoadLine(person="Dev One", items=2, done=1, estimated="2.0d", spent="3.0d")],
        "notes": [],
    }
    return ProgressSummary(**{**fields, **kw})


def _item(key: str = "MYC-7", **kw: Any) -> WorkItemRow:
    fields: dict[str, Any] = {
        "source": JIRA,
        "project": "MYC",
        "issue_id": key.split("-")[-1],
        "issue_key": key,
        "kind": "story",
        "parent_key": "MYC-6",
        "title": "dựng dashboard",
        "status": "In Progress",
        "status_category": "doing",
        "assignee_account_id": "acct-1",
        "assignee_name": "Dev One",
        "original_estimate_seconds": 2 * SECONDS_PER_DAY,
        "time_spent_seconds": SECONDS_PER_DAY,
        "due_at": datetime(2026, 9, 16, tzinfo=UTC),
        "created_at": datetime(2026, 9, 14, tzinfo=UTC),
        "resolved_at": None,
        "labels": [],
        "updated_at": datetime(2026, 9, 20, tzinfo=UTC),
    }
    return WorkItemRow(**{**fields, **kw})


class TestTheTelegramMessage:
    """What goes out, and what is deliberately left behind a link."""

    @pytest.fixture(autouse=True)
    def _configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def settings() -> Settings:
            return Settings(
                telegram_bot_token=SecretStr("bot-token"),
                telegram_notify_chat_id="-100",
                public_base_url="https://mycel.example.com",
            )

        monkeypatch.setattr(telegram, "get_settings", settings)

    async def test_it_posts_to_the_configured_chat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink))

        assert await telegram.notify_summary("job-1", "MYC", _summary()) is True
        assert "/botbot-token/sendMessage" in str(sink[0].url)

    async def test_the_message_carries_a_link_to_the_whole_report(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A report in a chat bubble is a report nobody scrolls, so the link is the point."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink))

        await telegram.notify_summary("job-1", "MYC", _summary())
        text = str(sink[0].read(), "utf-8")

        assert "https://mycel.example.com/app/reports?job=job-1" in text

    def test_the_headline_leads_with_what_is_late(self) -> None:
        """The one line somebody has to act on today, and not the fourth one down."""
        text = telegram.headline("MYC", _summary(), "https://x/app")

        assert "MYC — 15-21 September 2026" in text
        assert "MYC-7 Dashboard — five days past due" in text

    def test_a_quiet_window_still_says_the_counts(self) -> None:
        text = telegram.headline("MYC", _summary(at_risk=[]), "https://x/app")

        assert "1 shipped · 1 in flight · 0 at risk" in text

    def test_the_summarys_own_sentence_leads(self) -> None:
        """The headline is the one line written to be read alone, so it goes first."""
        text = telegram.headline("MYC", _summary(), "https://x/app")
        lines = text.splitlines()

        assert lines[1] == "Schemas landed; the dashboard is five days late."

    def test_the_verdict_is_a_colour_not_a_word(self) -> None:
        """Read at a glance among other notifications, where a word gets scrolled past."""
        assert telegram.headline("MYC", _summary(health="on_track"), "u").startswith("🟢")
        assert telegram.headline("MYC", _summary(health="at_risk"), "u").startswith("🟡")
        assert telegram.headline("MYC", _summary(health="off_track"), "u").startswith("🔴")

    def test_a_summary_with_no_headline_still_sends(self) -> None:
        """The field defaults to empty, and an empty line in a chat bubble is a bug."""
        text = telegram.headline("MYC", _summary(headline=""), "https://x/app")

        assert "\n\n" not in text

    def test_a_long_summary_is_cut_rather_than_refused(self) -> None:
        """Telegram rejects anything over 4096 characters outright, and a message that
        needs scrolling has already failed at being a notification."""
        long = [WorkLine(key="MYC-7", title="x" * 2000)]
        text = telegram.headline("MYC", _summary(at_risk=long), "https://x/app")

        assert len(text) <= telegram.MAX_CHARS
        assert text.endswith("…")

    async def test_an_unreachable_chat_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The job already produced and stored the report. Losing it over a failed
        receipt would be throwing away the work to report that the receipt went missing."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("no route to host")

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))

        assert await telegram.notify_summary("job-1", "MYC", _summary()) is False

    async def test_a_rejection_does_not_raise_either(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A wrong chat id is a 400, and it is still not this job's problem."""
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], status=400))

        assert await telegram.notify_summary("job-1", "MYC", _summary()) is False


class TestNotBeingConfigured:
    """A deployment that notifies nobody is a supported deployment, not a broken one."""

    async def test_no_token_means_nothing_is_sent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            telegram, "get_settings", lambda: Settings(telegram_notify_chat_id="-1")
        )

        assert await telegram.notify_summary("job-1", "MYC", _summary()) is False

    async def test_no_chat_id_means_nothing_is_sent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            telegram, "get_settings", lambda: Settings(telegram_bot_token=SecretStr("t"))
        )

        assert await telegram.notify_summary("job-1", "MYC", _summary()) is False

    async def test_no_calendar_means_no_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(calendar, "get_settings", lambda: Settings())

        assert await calendar.publish_due_dates([_item()]) == 0

    async def test_a_calendar_without_a_key_file_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Half-configured is the state a deployment actually reaches, and it is not a
        crash: the id was set and the key never mounted."""
        monkeypatch.setattr(
            calendar, "get_settings", lambda: Settings(google_calendar_id="work@group.calendar")
        )

        assert await calendar.publish_due_dates([_item()]) == 0


class TestTheCalendarEvents:
    @pytest.fixture(autouse=True)
    def _configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def settings() -> Settings:
            return Settings(
                google_calendar_id="work@group.calendar",
                google_service_account_json="/nowhere/key.json",
            )

        monkeypatch.setattr(calendar, "get_settings", settings)
        monkeypatch.setattr(calendar, "_token", lambda path: "access-token")

    def test_an_event_id_is_the_same_every_time(self) -> None:
        """The whole of idempotence: a re-sync updates the event already in someone's
        week rather than adding a second one beside it."""
        assert calendar.event_id("MYC-7") == calendar.event_id("MYC-7")
        assert calendar.event_id("MYC-7") != calendar.event_id("MYC-8")

    def test_an_event_id_is_legal_for_google(self) -> None:
        """Lowercase base32hex, 5 to 1024 characters — which `MYC-7` is not, so the key is
        encoded rather than tidied up."""
        made = calendar.event_id("MYC-7")

        assert 5 <= len(made) <= 1024
        assert set(made) <= set("0123456789abcdefghijklmnopqrstuv")

    async def test_a_due_date_is_written_as_an_all_day_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A date, not an hour: Jira's due date has no time of day, and inventing 9am puts
        a false precision on a phone's lock screen."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink))

        assert await calendar.publish_due_dates([_item()]) == 1
        body = str(sink[0].read(), "utf-8")

        assert sink[0].method == "PUT"
        assert '"date":"2026-09-16"' in body
        assert "MYC-7" in body and "dựng dashboard" in body

    async def test_the_id_is_in_the_url_so_a_second_run_updates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PUT with an id we chose: an insert and an update are the same call, and there
        is no window in which a duplicate can appear."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink))

        await calendar.publish_due_dates([_item(), _item()])

        assert str(sink[0].url) == str(sink[1].url)
        assert calendar.event_id("MYC-7") in str(sink[0].url)

    async def test_a_removed_due_date_removes_the_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deadline that no longer exists is worse on a calendar than one that never
        appeared, because somebody is still planning around it."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, status=204))

        assert await calendar.publish_due_dates([_item(due_at=None)]) == 1
        assert sink[0].method == "DELETE"

    async def test_deleting_something_already_gone_is_a_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """404 means the calendar is in the state we wanted it in."""
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], status=404))

        assert await calendar.publish_due_dates([_item(due_at=None)]) == 1

    async def test_one_refused_event_does_not_stop_the_rest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sync writes a week at a time, and one bad row must not cost the other six."""
        seen: list[str] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(str(request.url))
            return httpx2.Response(500 if len(seen) == 1 else 200, json={})

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))

        assert await calendar.publish_due_dates([_item("MYC-7"), _item("MYC-8")]) == 1
        assert len(seen) == 2
