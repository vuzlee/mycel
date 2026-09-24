"""The sync chain: the Jira connector, the normaliser, and the checks that guard gold.

No request leaves the machine and no database is touched — `httpx2.MockTransport` answers
for the REST API, and the layered tests in `test_postgres.py` cover the SQL. What is
pinned here is the part with no equivalent elsewhere: the ways Jira fails, the shape its
payloads actually have, and the rule that nothing malformed reaches the layer above.

`tests/fixtures/jira_payloads.json` is a recorded response from a real site with the
addresses and account ids replaced. Recorded rather than hand-written, because the bugs
worth catching live in the fields Jira fills in its own way — an offset with no colon, a
bare due date, an estimate that is only inside `timetracking`.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from mycel.core.config import Settings
from mycel.etl.checks.work import CheckFailed, check_item, check_items, check_worklog
from mycel.etl.normalise import JIRA, from_jira_issue, from_jira_worklog
from mycel.etl.promote import to_gold_item, to_gold_worklog
from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow
from mycel.services.check import check_work
from mycel.sources import SourceError, jira

pytestmark = pytest.mark.anyio

PROJECT = "MYC"

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "jira_payloads.json").read_text())


def _issue(key: str) -> dict[str, Any]:
    return next(i for i in RECORDED["issues"] if i["key"] == key)


def _settings(**kw: Any) -> Settings:
    kw.setdefault("jira_base_url", "https://example.atlassian.net")
    kw.setdefault("jira_email", "dev@example.com")
    kw.setdefault("jira_api_token", SecretStr("token"))
    return Settings(**kw)


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials by default; the tests that care about their absence override this."""
    monkeypatch.setattr(jira, "get_settings", _settings)


#: Captured before any test patches the name, so the factory below builds a real client
#: rather than recursing into its own replacement.
_REAL_CLIENT = httpx2.AsyncClient


def _mock(handler: Any) -> Any:
    def _client(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=httpx2.MockTransport(handler), **kwargs)

    return _client


def _responds(payload: Any, status: int = 200, **headers: str) -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=payload, headers=headers)

    return _mock(handler)


def _item(**kw: Any) -> WorkItemRow:
    fields: dict[str, Any] = {
        "source": JIRA,
        "project": PROJECT,
        "issue_id": "10007",
        "issue_key": "MYC-7",
        "kind": "story",
        "parent_key": "MYC-6",
        "title": "Postgres schemas and alembic migrations",
        "status": "Done",
        "status_category": "done",
        "priority": "Medium",
        "assignee_account_id": "acct-1",
        "assignee_name": "Dev One",
        "original_estimate_seconds": 57600,
        "time_spent_seconds": 18000,
        "due_at": datetime(2026, 9, 9, tzinfo=UTC),
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "resolved_at": None,
        "labels": ["backfill"],
        "updated_at": datetime(2026, 9, 2, tzinfo=UTC),
    }
    return WorkItemRow(**{**fields, **kw})


def _worklog(**kw: Any) -> WorklogRow:
    fields: dict[str, Any] = {
        "source": JIRA,
        "project": PROJECT,
        "worklog_id": "10100",
        "issue_key": "MYC-7",
        "author_account_id": "acct-1",
        "author_name": "Dev One",
        "time_spent_seconds": 18000,
        "started_at": datetime(2026, 9, 8, 9, tzinfo=UTC),
        "comment": None,
    }
    return WorklogRow(**{**fields, **kw})


class TestSearchingIssues:
    async def test_the_issues_come_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({"issues": RECORDED["issues"]}))
        found = await jira.search_issues("project = MYC")
        assert [i["key"] for i in found] == ["MYC-6", "MYC-7", "MYC-8"]

    async def test_the_jql_is_sent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.update(json.loads(request.content))
            return httpx2.Response(200, json={"issues": []})

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))
        await jira.search_issues("project = MYC AND updated >= '2026-09-01'")
        assert seen["jql"] == "project = MYC AND updated >= '2026-09-01'"
        assert "summary" in seen["fields"]

    async def test_paging_follows_the_token_not_an_offset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/search/jql` pages with an opaque token; sending `startAt` is a 400."""
        tokens: list[str | None] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content)
            tokens.append(body.get("nextPageToken"))
            first = body.get("nextPageToken") is None
            return httpx2.Response(
                200,
                json={
                    "issues": [_issue("MYC-6")] if first else [_issue("MYC-7")],
                    **({"nextPageToken": "page-2"} if first else {}),
                },
            )

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))
        found = await jira.search_issues("project = MYC")
        assert tokens == [None, "page-2"]
        assert [i["key"] for i in found] == ["MYC-6", "MYC-7"]

    async def test_an_empty_project_is_not_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({"issues": []}))
        assert await jira.search_issues("project = MYC") == []


class TestTheWorklogCall:
    async def test_the_entries_come_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({"worklogs": RECORDED["worklogs"]}))
        found = await jira.issue_worklogs("MYC-7")
        assert [w["timeSpentSeconds"] for w in found] == [18000, 21600]

    async def test_an_issue_with_no_effort_logged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({"worklogs": []}))
        assert await jira.issue_worklogs("MYC-6") == []


class TestWritingBack:
    """Off by default, and a transition is looked up rather than hardcoded."""

    def _armed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jira, "get_settings", lambda: _settings(jira_write_enabled=True))

    async def test_commenting_is_refused_until_it_is_armed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Commenting on fifty issues by mistake is not recoverable the way a bad read is."""
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({"id": "1"}))

        with pytest.raises(SourceError, match="writing is off"):
            await jira.add_comment("MYC-7", "two stories shipped")

    async def test_a_comment_goes_as_a_document_not_a_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The v3 API rejects plain text, and it rejects it as a 400 with no clue why."""
        self._armed(monkeypatch)
        seen: dict[str, Any] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.update(json.loads(request.content))
            return httpx2.Response(201, json={"id": "10200"})

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))
        created = await jira.add_comment("MYC-7", "two stories shipped")

        assert created["id"] == "10200"
        assert seen["body"]["type"] == "doc"
        text = seen["body"]["content"][0]["content"][0]["text"]
        assert text == "two stories shipped"

    async def test_a_transition_is_looked_up_by_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ids are per workflow: a hardcoded one is right until somebody edits the workflow,
        and then it silently moves issues somewhere else."""
        self._armed(monkeypatch)
        sent: list[dict[str, Any]] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            if request.method == "GET":
                return httpx2.Response(
                    200,
                    json={"transitions": [{"id": "31", "to": {"name": "Done"}}]},
                )
            sent.append(json.loads(request.content))
            return httpx2.Response(204)

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))
        await jira.transition("MYC-7", "done")

        assert sent == [{"transition": {"id": "31"}}]

    async def test_a_move_the_workflow_does_not_allow_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transition that did not happen looks exactly like one that did, from a 204."""
        self._armed(monkeypatch)
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            _responds({"transitions": [{"id": "31", "to": {"name": "In Progress"}}]}),
        )

        with pytest.raises(SourceError, match="cannot move"):
            await jira.transition("MYC-7", "Done")

    async def test_transitions_can_be_read_without_arming_writes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        moves = {"transitions": [{"id": "31", "to": {"name": "Done"}}]}
        monkeypatch.setattr(httpx2, "AsyncClient", _responds(moves))

        assert [t["id"] for t in await jira.transitions_for("MYC-7")] == ["31"]


class TestHowJiraFails:
    async def test_a_missing_base_url_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jira, "get_settings", lambda: Settings(jira_base_url=None))
        with pytest.raises(SourceError, match="JIRA_BASE_URL"):
            await jira.search_issues("project = MYC")

    async def test_missing_credentials_say_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jira, "get_settings", lambda: _settings(jira_api_token=None))
        with pytest.raises(SourceError, match="JIRA_EMAIL and JIRA_API_TOKEN"):
            await jira.search_issues("project = MYC")

    async def test_a_rejected_token_mentions_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After a year this is the expected failure, not a bug, and the message says why."""
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({}, status=401))
        with pytest.raises(SourceError, match="expire"):
            await jira.search_issues("project = MYC")

    async def test_a_forbidden_project_names_the_account(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({}, status=403))
        with pytest.raises(SourceError, match="dev@example.com"):
            await jira.search_issues("project = MYC")

    async def test_a_wrong_site_says_where_to_look(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({}, status=404))
        with pytest.raises(SourceError, match="JIRA_BASE_URL"):
            await jira.search_issues("project = MYC")

    async def test_a_bad_jql_reports_jiras_own_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            _responds({"errorMessages": ["Field 'sprintt' does not exist"]}, status=400),
        )
        with pytest.raises(SourceError, match="sprintt"):
            await jira.search_issues("project = MYC")

    async def test_rate_limiting_is_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """429 is normal on an adaptive limit; the sync waits rather than failing the run."""
        calls: list[int] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx2.Response(429, json={}, headers={"Retry-After": "0"})
            return httpx2.Response(200, json={"issues": [_issue("MYC-6")]})

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))
        assert len(await jira.search_issues("project = MYC")) == 1
        assert len(calls) == 2

    async def test_persistent_rate_limiting_gives_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({}, 429, **{"Retry-After": "0"}))
        with pytest.raises(SourceError, match="rate limited"):
            await jira.search_issues("project = MYC")

    async def test_a_timeout_names_the_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.TimeoutException("too slow")

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))
        with pytest.raises(SourceError, match="did not respond"):
            await jira.search_issues("project = MYC")


class TestNormalisingAnIssue:
    def test_an_epic_becomes_a_row(self) -> None:
        row = from_jira_issue(_issue("MYC-6"), PROJECT)
        assert row is not None
        assert (row.kind, row.issue_key, row.parent_key) == ("epic", "MYC-6", None)

    def test_a_story_keeps_its_parent_as_a_key(self) -> None:
        """A key, not a foreign key: a sync may bring a child in before its epic."""
        row = from_jira_issue(_issue("MYC-7"), PROJECT)
        assert row is not None
        assert (row.kind, row.parent_key) == ("story", "MYC-6")

    def test_the_estimate_is_kept_in_seconds(self) -> None:
        row = from_jira_issue(_issue("MYC-7"), PROJECT)
        assert row is not None
        assert row.original_estimate_seconds == 57600

    def test_a_bare_due_date_becomes_the_end_of_that_day(self) -> None:
        """Read as the end of the day, so something due today is not late at nine a.m."""
        row = from_jira_issue(_issue("MYC-7"), PROJECT)
        assert row is not None and row.due_at is not None
        assert (row.due_at.date().isoformat(), row.due_at.hour) == ("2026-09-09", 23)

    def test_an_offset_without_a_colon_is_still_parsed(self) -> None:
        """Jira writes `+0700`; `fromisoformat` wants `+07:00`, and one of them has to give."""
        row = from_jira_issue(_issue("MYC-6"), PROJECT)
        assert row is not None
        assert row.created_at.tzinfo is not None

    def test_the_status_category_is_the_readable_one(self) -> None:
        row = from_jira_issue(_issue("MYC-7"), PROJECT)
        assert row is not None
        assert row.status_category in {"todo", "doing", "done"}

    def test_the_assignee_is_kept_by_account_id(self) -> None:
        """`accountId` is the only supported identifier; the name is for display only."""
        row = from_jira_issue(_issue("MYC-7"), PROJECT)
        assert row is not None
        assert (row.assignee_account_id, row.assignee_name) == ("acct-1", "Dev One")

    def test_an_estimate_only_in_timetracking_is_still_found(self) -> None:
        """The top-level field is absent on a site that hides it from the screen."""
        payload = _issue("MYC-7")
        fields = {
            **payload["fields"],
            "timeoriginalestimate": None,
            "timetracking": {"originalEstimateSeconds": 3600},
        }
        row = from_jira_issue({**payload, "fields": fields}, PROJECT)
        assert row is not None
        assert row.original_estimate_seconds == 3600

    def test_the_priority_is_kept_as_the_sites_own_name(self) -> None:
        """A name, not a rank: one site's "Blocker" is another's "Highest"."""
        row = from_jira_issue(_issue("MYC-7"), PROJECT)
        assert row is not None
        assert row.priority == "High"

    def test_a_hidden_priority_field_is_none_not_a_guess(self) -> None:
        """An ordinary configuration. Inventing a Medium here would put work in a bar
        nobody put it in."""
        row = from_jira_issue(_issue("MYC-6"), PROJECT)
        assert row is not None
        assert row.priority is None

    def test_an_unknown_issue_type_becomes_a_task(self) -> None:
        payload = _issue("MYC-7")
        fields = {**payload["fields"], "issuetype": {"name": "Spike"}}
        row = from_jira_issue({**payload, "fields": fields}, PROJECT)
        assert row is not None and row.kind == "task"

    def test_a_payload_with_no_fields_is_refused(self) -> None:
        """Not a shape Jira produces, but a replay of half-written bronze can be."""
        assert from_jira_issue({"key": "MYC-7"}, PROJECT) is None


class TestNormalisingAWorklog:
    def test_an_entry_becomes_a_row(self) -> None:
        row = from_jira_worklog(RECORDED["worklogs"][0], PROJECT)
        assert row is not None
        assert (row.issue_key, row.time_spent_seconds) == ("MYC-7", 18000)

    def test_the_backdated_start_is_kept(self) -> None:
        """The whole reason worklogs are the time series: `started` is whatever it is told."""
        row = from_jira_worklog(RECORDED["worklogs"][0], PROJECT)
        assert row is not None
        assert row.started_at.date().isoformat() == "2026-09-08"

    def test_the_issue_key_comes_from_the_carrier_not_the_payload(self) -> None:
        """Jira serves worklogs per issue and does not repeat the key inside the entry."""
        payload = {k: v for k, v in RECORDED["worklogs"][0].items() if k != "issue_key"}
        assert from_jira_worklog(payload, PROJECT) is None

    def test_a_comment_document_is_flattened_to_prose(self) -> None:
        payload = {
            **RECORDED["worklogs"][0],
            "comment": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "wrote the DDL"}]}
                ],
            },
        }
        row = from_jira_worklog(payload, PROJECT)
        assert row is not None and row.comment == "wrote the DDL"


class TestPromotingToGold:
    """A copy today. The test is here so it fails loudly when it stops being one."""

    def test_an_item_crosses_unchanged(self) -> None:
        assert to_gold_item(_item()) == _item()

    def test_a_worklog_crosses_unchanged(self) -> None:
        assert to_gold_worklog(_worklog()) == _worklog()


class TestTheChecks:
    def test_a_good_item_passes(self) -> None:
        assert check_item(_item()) is None

    def test_an_unknown_category_is_caught(self) -> None:
        assert check_item(_item(status_category="cooking")) is not None

    def test_an_empty_title_is_caught(self) -> None:
        assert check_item(_item(title="   ")) is not None

    def test_an_item_that_is_its_own_parent_is_caught(self) -> None:
        assert check_item(_item(parent_key="MYC-7")) is not None

    def test_a_naive_timestamp_is_caught(self) -> None:
        """A timestamp with no zone compares wrongly against every window query."""
        assert check_item(_item(created_at=datetime(2026, 9, 1))) is not None

    def test_a_creation_in_the_future_is_caught(self) -> None:
        assert check_item(_item(created_at=datetime.now(UTC) + timedelta(days=1))) is not None

    def test_small_clock_skew_is_tolerated(self) -> None:
        """A site's clock being a minute off is normal and not a parsing bug."""
        assert check_item(_item(created_at=datetime.now(UTC) + timedelta(minutes=1))) is None

    def test_a_due_date_in_the_future_is_fine(self) -> None:
        """Being ahead of now is the entire point of a due date."""
        assert check_item(_item(due_at=datetime.now(UTC) + timedelta(days=30))) is None

    def test_resolved_before_created_is_caught(self) -> None:
        assert check_item(_item(resolved_at=datetime(2026, 8, 1, tzinfo=UTC))) is not None

    def test_a_backdated_worklog_is_allowed(self) -> None:
        """It is the one honest time series in a project filled in after the fact."""
        assert check_worklog(_worklog(started_at=datetime(2024, 1, 1, tzinfo=UTC))) is None

    def test_a_worklog_from_the_future_is_caught(self) -> None:
        ahead = datetime.now(UTC) + timedelta(days=1)
        assert check_worklog(_worklog(started_at=ahead)) is not None

    def test_effort_of_zero_is_caught(self) -> None:
        assert check_worklog(_worklog(time_spent_seconds=0)) is not None

    def test_every_reason_is_reported_not_just_the_first(self) -> None:
        """One bad row usually means a class of them; finding them one run at a time is slow."""
        assert len(check_items([_item(status_category="x"), _item(title="")])) == 2

    def test_the_service_raises_rather_than_dropping_rows(self) -> None:
        """A silently shorter batch is how a dashboard ends up quietly wrong."""
        with pytest.raises(CheckFailed):
            check_work([_item(), _item(title="")], [])

    def test_the_service_passes_a_clean_batch(self) -> None:
        check_work([_item(), _item(kind="epic")], [_worklog()])
