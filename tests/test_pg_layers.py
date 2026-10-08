"""Postgres: layers."""

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.etl.checks.work import CheckFailed
from mycel.infra.postgres.repositories.bronze import BronzeRepository
from mycel.infra.postgres.repositories.gold import WORKDAY_SECONDS
from mycel.infra.postgres.repositories.silver import SilverRepository
from mycel.services.transform import TransformResult, transform
from tests.fakes import needs_postgres
from tests.pg import (
    PROJECT,
    GoldRepository,
    _at,
    _epic,
    _item,
    _payload,
    _worklog,
    _worklog_payload,
)

pytestmark = pytest.mark.anyio


@needs_postgres
class TestBronzeRepository:
    async def test_the_payload_comes_back_untouched(self, session: AsyncSession) -> None:
        """Bronze is for replay: what went in is what a later transform will read."""
        payload = _payload()
        await BronzeRepository(session).save_issues([payload])
        stored = await session.scalar(
            text("SELECT payload FROM bronze.jira_issue WHERE issue_key = 'MYC-7'")
        )
        assert stored == payload

    async def test_the_same_issue_twice_overwrites(self, session: AsyncSession) -> None:
        """Unlike an event, which arriving twice does not make truer, an issue is a record and a
        second fetch is a later, better version of it.
        """
        repo = BronzeRepository(session)
        await repo.save_issues([_payload()])
        await repo.save_issues([_payload(summary="renamed")])

        payloads = await repo.issue_payloads()
        assert len(payloads) == 1
        assert payloads[0]["fields"]["summary"] == "renamed"

    async def test_an_issue_with_no_key_is_dropped(self, session: AsyncSession) -> None:
        assert await BronzeRepository(session).save_issues([{"id": "1"}]) == 0

    async def test_writing_nothing_is_allowed(self, session: AsyncSession) -> None:
        assert await BronzeRepository(session).save_issues([]) == 0

    async def test_a_worklog_carries_the_issue_key_back_out(self, session: AsyncSession) -> None:
        """Jira's worklog payload has no key in it."""
        repo = BronzeRepository(session)
        await repo.save_worklogs("MYC-7", [_worklog_payload()])

        payloads = await repo.worklog_payloads()
        assert [p["issue_key"] for p in payloads] == ["MYC-7"]

    async def test_a_replay_can_be_limited_to_one_syncs_keys(self, session: AsyncSession) -> None:
        repo = BronzeRepository(session)
        await repo.save_issues([_payload("MYC-7"), _payload("MYC-8")])

        assert len(await repo.issue_payloads(["MYC-8"])) == 1


@needs_postgres
class TestSilverRepository:
    """The layer between. It holds what the source said, and gold is promoted from it."""

    async def test_what_goes_in_comes_back(self, session: AsyncSession) -> None:
        repo = SilverRepository(session)
        await repo.upsert_items([_item()])

        assert await repo.items() == [_item()]

    async def test_a_second_sync_replaces_the_row(self, session: AsyncSession) -> None:
        """Keyed on `(source, issue_key)`, so a re-fetched issue updates instead of doubling."""
        repo = SilverRepository(session)
        await repo.upsert_items([_item()])
        await repo.upsert_items([_item(status="Done", status_category="done")])

        rows = await repo.items()
        assert [r.status_category for r in rows] == ["done"]

    async def test_worklogs_round_trip_too(self, session: AsyncSession) -> None:
        repo = SilverRepository(session)
        await repo.upsert_worklogs([_worklog()])

        assert await repo.worklogs() == [_worklog()]

    async def test_keys_narrow_the_read(self, session: AsyncSession) -> None:
        """What a scheduled run promotes: the issues its own fetch brought in."""
        repo = SilverRepository(session)
        await repo.upsert_items([_item("MYC-7"), _item("MYC-8")])

        assert [r.issue_key for r in await repo.items(keys=["MYC-8"])] == ["MYC-8"]

    async def test_writing_nothing_is_allowed(self, session: AsyncSession) -> None:
        assert await SilverRepository(session).upsert_items([]) == 0


@needs_postgres
class TestGoldRepository:
    async def test_what_goes_in_comes_back(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items([_item()])
        rows = await GoldRepository(session).items_between(PROJECT, _at(1))
        assert [r.issue_key for r in rows] == ["MYC-7"]

    async def test_a_second_sync_replaces_the_row(self, session: AsyncSession) -> None:
        """An issue moving from doing to done is the same row, later."""
        repo = GoldRepository(session)
        await repo.upsert_items([_item()])
        await repo.upsert_items([_item(status="Done", status_category="done")])

        rows = await repo.items_between(PROJECT, _at(1))
        assert len(rows) == 1 and rows[0].status_category == "done"

    async def test_writing_nothing_is_allowed(self, session: AsyncSession) -> None:
        """A quiet day must not have to be guarded by the caller."""
        repo = GoldRepository(session)
        assert (await repo.upsert_items([]), await repo.upsert_worklogs([])) == (0, 0)

    async def test_the_window_is_on_when_it_moved_not_when_it_opened(
        self, session: AsyncSession
    ) -> None:
        """A story opened last month and finished this week belongs to this week."""
        repo = GoldRepository(session)
        await repo.upsert_items([_item(created_at=_at(1), updated_at=_at(18))])

        assert len(await repo.items_between(PROJECT, _at(15), _at(21))) == 1

    async def test_a_window_excludes_what_falls_outside_it(self, session: AsyncSession) -> None:
        repo = GoldRepository(session)
        await repo.upsert_items([_item("MYC-7", updated_at=_at(8)), _item("MYC-8")])

        rows = await repo.items_between(PROJECT, _at(15), _at(21))
        assert [r.issue_key for r in rows] == ["MYC-8"]

    async def test_another_project_is_not_mixed_in(self, session: AsyncSession) -> None:
        repo = GoldRepository(session)
        await repo.upsert_items([_item(), _item("OTH-1", project="OTH")])

        assert len(await repo.items_between(PROJECT, _at(1))) == 1

    async def test_an_epic_outside_the_window_is_still_reachable(
        self, session: AsyncSession
    ) -> None:
        """An epic rarely moves while its children do."""
        repo = GoldRepository(session)
        await repo.upsert_items([_epic(updated_at=_at(2)), _item()])

        parents = await repo.parents_of(PROJECT, ["MYC-6"])
        assert [p.title for p in parents] == ["Pipeline and storage"]

    async def test_every_category_is_counted_zeroes_included(self, session: AsyncSession) -> None:
        """So a caller renders a fixed set of bars without guessing which exist."""
        repo = GoldRepository(session)
        await repo.upsert_items([_item("MYC-7"), _item("MYC-8", status_category="done")])

        assert await repo.count_by_category(PROJECT, _at(1)) == {
            "todo": 0,
            "doing": 1,
            "done": 1,
        }

    async def test_load_is_grouped_per_person(self, session: AsyncSession) -> None:
        repo = GoldRepository(session)
        await repo.upsert_items([_item("MYC-7"), _item("MYC-8", status_category="done")])

        load = await repo.load_by_assignee(PROJECT, _at(1))
        assert len(load) == 1
        assert (load[0].items, load[0].done) == (2, 1)

    async def test_the_gap_is_spent_minus_estimated(self, session: AsyncSession) -> None:
        """The number nobody has today, and the reason the hashtag convention had to go."""
        repo = GoldRepository(session)
        await repo.upsert_items(
            [_item(original_estimate_seconds=WORKDAY_SECONDS, time_spent_seconds=3 * 28800)]
        )

        load = await repo.load_by_assignee(PROJECT, _at(1))
        assert load[0].gap_seconds == 2 * WORKDAY_SECONDS

    async def test_unassigned_work_is_a_row_of_its_own(self, session: AsyncSession) -> None:
        """Six unassigned tickets is exactly what a lead needs to see, not something to drop."""
        repo = GoldRepository(session)
        await repo.upsert_items([_item("MYC-9", assignee_account_id=None, assignee_name=None)])

        load = await repo.load_by_assignee(PROJECT, _at(1))
        assert [p.name for p in load] == ["Unassigned"]

    async def test_the_busiest_person_comes_first(self, session: AsyncSession) -> None:
        repo = GoldRepository(session)
        await repo.upsert_items(
            [
                _item("MYC-7"),
                _item("MYC-8"),
                _item("MYC-9", assignee_account_id="acct-2", assignee_name="Dev Two"),
            ]
        )

        load = await repo.load_by_assignee(PROJECT, _at(1))
        assert [p.name for p in load] == ["Dev One", "Dev Two"]

    async def test_overdue_is_past_due_and_not_done(self, session: AsyncSession) -> None:
        repo = GoldRepository(session)
        await repo.upsert_items(
            [
                _item("MYC-7", due_at=_at(10)),
                _item("MYC-8", due_at=_at(10), status_category="done"),
                _item("MYC-9", due_at=_at(30)),
            ]
        )

        assert [r.issue_key for r in await repo.overdue(PROJECT, _at(21))] == ["MYC-7"]

    async def test_the_most_late_is_at_the_top(self, session: AsyncSession) -> None:
        repo = GoldRepository(session)
        await repo.upsert_items([_item("MYC-7", due_at=_at(12)), _item("MYC-8", due_at=_at(2))])

        assert [r.issue_key for r in await repo.overdue(PROJECT, _at(21))] == ["MYC-8", "MYC-7"]

    async def test_effort_is_summed_per_day(self, session: AsyncSession) -> None:
        repo = GoldRepository(session)
        await repo.upsert_worklogs(
            [
                _worklog("1", started_at=_at(16)),
                _worklog("2", started_at=_at(16, 14)),
                _worklog("3", started_at=_at(17)),
            ]
        )

        effort = await repo.effort_by_day(PROJECT, _at(1))
        assert [(e.day, e.seconds) for e in effort] == [
            (date(2026, 9, 16), 10 * 3600),
            (date(2026, 9, 17), 5 * 3600),
        ]

    async def test_an_edited_worklog_is_not_counted_twice(self, session: AsyncSession) -> None:
        """Keyed by Jira's own worklog id, which is what an edit keeps."""
        repo = GoldRepository(session)
        await repo.upsert_worklogs([_worklog()])
        await repo.upsert_worklogs([_worklog(time_spent_seconds=3600)])

        effort = await repo.effort_by_day(PROJECT, _at(1))
        assert [e.seconds for e in effort] == [3600]

    async def test_the_picker_lists_every_project(self, session: AsyncSession) -> None:
        repo = GoldRepository(session)
        await repo.upsert_items([_item(), _item("OTH-1", project="OTH")])

        assert await repo.projects() == ["MYC", "OTH"]


@needs_postgres
class TestTheTransform:
    """Bronze to silver to gold, on one session."""

    async def test_a_payload_reaches_gold(self, session: AsyncSession) -> None:
        await BronzeRepository(session).save_issues([_payload()])

        assert await transform(session) == TransformResult(
            silver_items=1, silver_worklogs=0, items=1, worklogs=0
        )

    async def test_worklogs_come_through_with_it(self, session: AsyncSession) -> None:
        bronze = BronzeRepository(session)
        await bronze.save_issues([_payload()])
        await bronze.save_worklogs("MYC-7", [_worklog_payload()])

        assert await transform(session) == TransformResult(
            silver_items=1, silver_worklogs=1, items=1, worklogs=1
        )

    async def test_running_it_twice_changes_nothing(self, session: AsyncSession) -> None:
        """Idempotent, which is what makes a failed sync safe to simply run again."""
        await BronzeRepository(session).save_issues([_payload()])
        await transform(session)
        await transform(session)

        assert len(await GoldRepository(session).items_between(PROJECT, _at(1))) == 1

    async def test_keys_limit_the_replay(self, session: AsyncSession) -> None:
        """A scheduled run transforms what its fetch brought in, not the whole table."""
        await BronzeRepository(session).save_issues([_payload("MYC-7"), _payload("MYC-8")])

        assert (await transform(session, keys=["MYC-8"])).items == 1

    async def test_the_project_comes_from_the_key(self, session: AsyncSession) -> None:
        """`JIRA_PROJECT_KEY` may be empty, meaning every project this account can see."""
        await BronzeRepository(session).save_issues([_payload("OTH-1")])
        await transform(session)

        assert await GoldRepository(session).projects() == ["OTH"]

    async def test_both_layers_hold_the_same_rows(self, session: AsyncSession) -> None:
        """The property that makes the middle layer honest rather than decorative."""
        bronze = BronzeRepository(session)
        await bronze.save_issues([_payload("MYC-7"), _payload("MYC-8")])
        await bronze.save_worklogs("MYC-7", [_worklog_payload()])
        await transform(session)

        silver = SilverRepository(session)
        assert [r.issue_key for r in await silver.items()] == ["MYC-7", "MYC-8"]
        assert len(await silver.worklogs()) == 1
        assert len(await GoldRepository(session).items_between(PROJECT, _at(1))) == 2

    async def test_a_failed_check_leaves_both_layers_untouched(self, session: AsyncSession) -> None:
        """The check guards the layer above it, and silver is now that layer."""
        await BronzeRepository(session).save_issues([_payload(summary="   ")])

        with pytest.raises(CheckFailed):
            await transform(session)

        assert await SilverRepository(session).items() == []
        assert await GoldRepository(session).items_between(PROJECT, _at(1)) == []

    async def test_an_empty_bronze_is_not_an_error(self, session: AsyncSession) -> None:
        assert await transform(session) == TransformResult(
            silver_items=0, silver_worklogs=0, items=0, worklogs=0
        )
