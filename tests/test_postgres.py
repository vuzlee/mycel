"""The data layer, against a real Postgres — never SQLite.

A migration is only proven on the database it will run on: SQLite has no schemas, no
`ON CONFLICT ... ON CONSTRAINT` and no JSONB, so it would skip most of what can break.
Without `DATABASE_URL` pointing somewhere reachable, these skip.

The pure-function half of the chain — Jira's payloads into rows — is in `test_sync.py`
against recorded payloads. What is here is what only a database can answer: the upserts,
the windows, the grouping, and that `alembic upgrade head` builds what the models declare.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mycel.etl.checks.work import CheckFailed
from mycel.etl.normalise import JIRA
from mycel.infra.postgres.engine import async_dsn, dispose_engine
from mycel.infra.postgres.locks import try_lock
from mycel.infra.postgres.models import Base
from mycel.infra.postgres.repositories.app import AppRepository
from mycel.infra.postgres.repositories.bronze import BronzeRepository
from mycel.infra.postgres.repositories.gold import (
    SECONDS_PER_DAY,
    GoldRepository,
    WorkItemRow,
    WorklogRow,
)
from mycel.infra.postgres.repositories.silver import SilverRepository
from mycel.services.dashboard import build_dashboard
from mycel.services.gather import gather_progress
from mycel.services.transform import TransformResult, transform

pytestmark = pytest.mark.anyio

DSN = os.environ.get("DATABASE_URL", "")
needs_postgres = pytest.mark.skipif(not DSN, reason="no test database is reachable")

# Every fixture below drops its schemas on teardown. `conftest` hands us a database whose
# name ends in `_test`; this asserts it, so a stray DATABASE_URL can never wipe a real one.
assert not DSN or DSN.rsplit("/", 1)[-1].endswith("_test"), f"refusing to run against {DSN}"

PROJECT = "MYC"
SCHEMAS = ("bronze", "silver", "gold", "app")


async def _drop(conn: Any) -> None:
    for schema in SCHEMAS:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A schema built from the models, dropped again when the test ends.

    Built with `create_all` rather than `alembic upgrade`, so a bug in the migration
    cannot make these pass — `TestTheMigration` is what holds the two together.
    """
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield db
    finally:
        async with engine.begin() as conn:
            await _drop(conn)
        await engine.dispose()


@pytest.fixture
async def alembic() -> AsyncIterator[Config]:
    """Alembic against an empty database, whatever the last run left behind.

    Both the schemas and alembic's own version row are cleared first: a stale version row
    over a missing schema makes `upgrade` a no-op and every assertion below meaningless.
    """
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        await _drop(conn)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()

    yield Config("alembic.ini")

    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        await _drop(conn)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()


def _at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=UTC)


def _item(key: str = "MYC-7", **kw: Any) -> WorkItemRow:
    fields: dict[str, Any] = {
        "source": JIRA,
        "project": PROJECT,
        "issue_id": key.split("-")[-1],
        "issue_key": key,
        "kind": "story",
        "parent_key": "MYC-6",
        "title": "Postgres schemas and alembic migrations",
        "status": "In Progress",
        "status_category": "doing",
        "assignee_account_id": "acct-1",
        "assignee_name": "Dev One",
        "original_estimate_seconds": 2 * SECONDS_PER_DAY,
        "time_spent_seconds": SECONDS_PER_DAY,
        "due_at": None,
        "created_at": _at(14),
        "resolved_at": None,
        "labels": ["backfill"],
        "updated_at": _at(18),
    }
    return WorkItemRow(**{**fields, **kw})


def _epic(key: str = "MYC-6", **kw: Any) -> WorkItemRow:
    return _item(key, kind="epic", parent_key=None, title="Pipeline and storage", **kw)


def _worklog(worklog_id: str = "10100", **kw: Any) -> WorklogRow:
    fields: dict[str, Any] = {
        "source": JIRA,
        "project": PROJECT,
        "worklog_id": worklog_id,
        "issue_key": "MYC-7",
        "author_account_id": "acct-1",
        "author_name": "Dev One",
        "time_spent_seconds": 5 * 3600,
        "started_at": _at(16),
        "comment": None,
    }
    return WorklogRow(**{**fields, **kw})


def _payload(key: str = "MYC-7", **overrides: Any) -> dict[str, Any]:
    """A search result, trimmed to the fields the normaliser reads."""
    fields: dict[str, Any] = {
        "summary": "Postgres schemas and alembic migrations",
        "issuetype": {"name": "Story"},
        "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
        "parent": {"key": "MYC-6"},
        "assignee": {"accountId": "acct-1", "displayName": "Dev One"},
        "duedate": None,
        "created": "2026-09-14T09:00:00.000+0000",
        "resolutiondate": None,
        "updated": "2026-09-18T09:00:00.000+0000",
        "labels": ["backfill"],
        "timeoriginalestimate": 2 * SECONDS_PER_DAY,
        "timespent": SECONDS_PER_DAY,
    }
    return {"id": key.split("-")[-1], "key": key, "fields": {**fields, **overrides}}


def _worklog_payload(worklog_id: str = "10100", **overrides: Any) -> dict[str, Any]:
    return {
        "id": worklog_id,
        "author": {"accountId": "acct-1", "displayName": "Dev One"},
        "timeSpentSeconds": 5 * 3600,
        "started": "2026-09-16T09:00:00.000+0000",
        **overrides,
    }


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
        """The opposite of the Telegram connector, and for a reason: an update is an event
        and arriving twice does not make the second copy truer, but an issue is a record
        and a second fetch is a later, better version of it."""
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
        """Jira's worklog payload has no key in it — it is only in the URL it came from —
        so the key lives in its own column and is joined back on here."""
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
        """An epic rarely moves while its children do, and a hierarchy with a hole where
        the parent's name should be is worse than one extra query."""
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
            [_item(original_estimate_seconds=SECONDS_PER_DAY, time_spent_seconds=3 * 28800)]
        )

        load = await repo.load_by_assignee(PROJECT, _at(1))
        assert load[0].gap_seconds == 2 * SECONDS_PER_DAY

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


class TestTheAsyncDsn:
    def test_a_plain_dsn_gets_the_async_driver(self) -> None:
        assert async_dsn("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"

    def test_an_explicit_driver_is_left_alone(self) -> None:
        """A deployment that names its own driver means it."""
        assert async_dsn("postgresql+psycopg://h/db") == "postgresql+psycopg://h/db"


@needs_postgres
class TestTheMigration:
    """`create_all` and `alembic upgrade head` must build the same thing.

    The repository tests run on `create_all`, which is fast and always matches the models.
    Production runs on the migration. Without this test the two drift and nobody notices
    until a deploy.
    """

    @pytest.mark.parametrize(
        ("schema", "table"),
        [
            ("bronze", "jira_issue"),
            ("bronze", "jira_worklog"),
            ("silver", "work_item"),
            ("silver", "worklog"),
            ("gold", "work_item"),
            ("gold", "worklog"),
            ("app", "user"),
            ("app", "session"),
            ("app", "conversation"),
            ("app", "turn"),
        ],
    )
    async def test_upgrade_builds_what_the_models_declare(
        self, alembic: Config, schema: str, table: str
    ) -> None:
        await asyncio.to_thread(command.upgrade, alembic, "head")

        engine = create_async_engine(async_dsn(DSN))
        async with engine.connect() as conn:
            built = await conn.run_sync(
                lambda sync: {
                    c["name"]: c["type"].compile(postgresql.dialect())
                    for c in inspect(sync).get_columns(table, schema=schema)
                }
            )
        await engine.dispose()

        # Compiled for postgresql, not `str(type)`: a declared `DateTime` prints as
        # DATETIME generically and TIMESTAMP on this dialect, which is the same column.
        declared = {
            c.name: c.type.compile(postgresql.dialect())
            for c in Base.metadata.tables[f"{schema}.{table}"].columns
        }
        assert built == declared

    @pytest.mark.parametrize(
        ("schema", "table"),
        [
            ("bronze", "telegram_message"),
            ("gold", "progress_update"),
            ("silver", "message"),
        ],
    )
    async def test_the_hashtag_tables_are_gone(
        self, alembic: Config, schema: str, table: str
    ) -> None:
        """Dropped rather than deprecated — 0004 for the first two, 0005 for `silver.message`.
        A table nothing writes to is a standing question about which of the two is real."""
        await asyncio.to_thread(command.upgrade, alembic, "head")

        engine = create_async_engine(async_dsn(DSN))
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda sync: inspect(sync).get_table_names(schema=schema))
        await engine.dispose()
        assert table not in names

    async def test_downgrade_leaves_nothing_behind(self, alembic: Config) -> None:
        """Written while the tables are empty, because nobody writes one later."""
        await asyncio.to_thread(command.upgrade, alembic, "head")
        await asyncio.to_thread(command.downgrade, alembic, "base")

        engine = create_async_engine(async_dsn(DSN))
        async with engine.connect() as conn:
            remaining = await conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.schemata "
                    "WHERE schema_name IN ('bronze','silver','gold','app')"
                )
            )
        await engine.dispose()
        assert remaining == 0


@needs_postgres
class TestTheTransform:
    """Bronze to silver to gold, on one session.

    The two counts are asserted separately every time. With Jira as the only source they
    must agree, and a test that says so is what stops the middle layer quietly falling out
    of the data path again.
    """

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


@needs_postgres
class TestTheAdvisoryLock:
    """Two schedulers, one sync. The loser skips rather than queueing identical work."""

    @pytest.fixture(autouse=True)
    async def _own_engine(self) -> AsyncIterator[None]:
        """A fresh process-wide engine per test, because each test gets its own loop.

        `try_lock` uses the cached engine, as the scheduler does. A pooled connection
        opened under one loop and checked out under the next is dead, and the failure
        surfaces as `Event loop is closed` from somewhere unrelated.
        """
        await dispose_engine()
        yield
        await dispose_engine()

    async def test_a_lock_is_granted(self) -> None:
        async with try_lock("test:sync") as acquired:
            assert acquired

    async def test_a_second_holder_is_refused(self) -> None:
        async with try_lock("test:sync") as first, try_lock("test:sync") as second:
            assert first and not second

    async def test_releasing_lets_the_next_one_in(self) -> None:
        async with try_lock("test:sync") as first:
            assert first
        async with try_lock("test:sync") as again:
            assert again

    async def test_unrelated_names_do_not_contend(self) -> None:
        async with try_lock("test:sync") as first, try_lock("test:report") as other:
            assert first and other


@needs_postgres
class TestTheProgressWindow:
    """What the summariser is given, assembled from gold in one place."""

    async def test_it_carries_the_items_and_the_totals(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items(
            [_item("MYC-7"), _item("MYC-8", status_category="done")]
        )

        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert len(window.items) == 2
        assert window.totals == {"todo": 0, "doing": 1, "done": 1}

    async def test_work_is_grouped_under_its_epic(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items([_epic(), _item()])

        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert [c.issue_key for c in window.by_epic["MYC-6"]] == ["MYC-7"]
        assert window.epic_titles["MYC-6"] == "Pipeline and storage"

    async def test_work_with_no_epic_is_not_lost(self, session: AsyncSession) -> None:
        """A standalone task is ordinary work, not a data error."""
        await GoldRepository(session).upsert_items([_item("MYC-9", parent_key=None)])

        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert [o.issue_key for o in window.orphans] == ["MYC-9"]

    async def test_an_empty_window_is_not_an_error(self, session: AsyncSession) -> None:
        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert window.is_empty and window.dropped == 0

    async def test_too_many_items_drops_the_oldest_and_counts_them(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The newest survive: a summary of this sprint that omits yesterday keeps the
        wrong half. `dropped` is non-zero so `render` can say the window is partial."""
        monkeypatch.setattr("mycel.services.gather.MAX_ITEMS", 2)
        await GoldRepository(session).upsert_items(
            [_item(f"MYC-{n}", updated_at=_at(15) + timedelta(hours=n)) for n in (1, 2, 3)]
        )

        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert window.dropped == 1
        assert [i.issue_key for i in window.items] == ["MYC-2", "MYC-3"]


@needs_postgres
class TestTheDashboard:
    """The same window the summariser reads, shaped for a screen.

    It goes through `gather_progress` rather than querying gold itself, so the two pages
    cannot disagree about what happened this week.
    """

    async def test_it_counts_by_category(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items(
            [_item("MYC-7"), _item("MYC-8", status_category="done")]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.totals == {"todo": 0, "doing": 1, "done": 1}

    async def test_an_epic_carries_how_far_its_children_got(self, session: AsyncSession) -> None:
        await GoldRepository(session).upsert_items(
            [_epic(), _item("MYC-7"), _item("MYC-8", status_category="done")]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [(e.issue_key, e.items, e.done, e.percent) for e in board.epics] == [
            ("MYC-6", 2, 1, 50)
        ]

    async def test_an_epic_is_sized_by_all_its_children_not_the_window(
        self, session: AsyncSession
    ) -> None:
        """The bar is the epic; `moved` is the week.

        A child finished last month still counts towards how far the epic has got. Sizing
        the bar by the window would draw a quiet epic as nearly done, which is the one
        thing a progress bar must never do.
        """
        await GoldRepository(session).upsert_items(
            [
                _epic(),
                _item("MYC-7", status_category="done", updated_at=_at(2)),
                _item("MYC-8", status_category="done"),
                _item("MYC-9"),
                _item("MYC-10"),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        epic = board.epics[0]
        assert (epic.items, epic.done, epic.percent) == (4, 2, 50)
        assert (epic.moved, epic.moved_done) == (3, 1)

    async def test_an_epic_nobody_has_touched_is_still_a_row(
        self, session: AsyncSession
    ) -> None:
        """A plan that hides its untouched parts is a plan that looks shorter than it is."""
        await GoldRepository(session).upsert_items([_epic(), _item("MYC-7")])

        board = await build_dashboard(session, PROJECT, _at(20), _at(21))
        assert [(e.issue_key, e.moved, e.percent) for e in board.epics] == [("MYC-6", 0, 0)]

    async def test_progress_is_the_project_not_the_window(self, session: AsyncSession) -> None:
        """`percent` answers "how far are we", which a window cannot answer.

        One item moved this week and it was done. Reading the window would call the
        project finished; it is one of three.
        """
        await GoldRepository(session).upsert_items(
            [
                _item("MYC-7", status_category="done"),
                _item("MYC-8", updated_at=_at(2)),
                _item("MYC-9", updated_at=_at(2)),
            ]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.totals == {"todo": 0, "doing": 0, "done": 1}
        assert board.all_totals == {"todo": 0, "doing": 2, "done": 1}
        assert board.percent == 33

    async def test_a_late_ticket_is_on_the_board_not_behind_a_count(
        self, session: AsyncSession
    ) -> None:
        await GoldRepository(session).upsert_items([_item(due_at=_at(10))])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [r.issue_key for r in board.overdue] == ["MYC-7"]

    async def test_an_old_overdue_ticket_is_late_without_being_in_the_window(
        self, session: AsyncSession
    ) -> None:
        """The one asymmetry the dashboard's captions promise, pinned.

        `overdue` is whole-project; every other block is the window. A ticket last touched
        before `since` must still show as late — that is the ticket nobody is looking at —
        while contributing nothing to the counts that say "these seven days".
        """
        await GoldRepository(session).upsert_items([_item(due_at=_at(10), updated_at=_at(11))])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [r.issue_key for r in board.overdue] == ["MYC-7"]
        assert board.totals == {"todo": 0, "doing": 0, "done": 0}

    async def test_spent_is_the_ticket_lifetime_and_effort_is_the_window(
        self, session: AsyncSession
    ) -> None:
        """Two numbers on one screen that are allowed to disagree, pinned so they stay so.

        Per person sums what Jira holds on the tickets the window selected — lifetime
        totals. Effort logged sums the worklogs *dated* inside it. The docs promise the two
        differ; without this, a later "fix" that made them agree would look like a cleanup.
        """
        gold = GoldRepository(session)
        await gold.upsert_items([_item("MYC-7", time_spent_seconds=10 * 3600)])
        await gold.upsert_worklogs(
            [_worklog("1", started_at=_at(2)), _worklog("2", started_at=_at(18))]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert [a.spent_seconds for a in board.assignees] == [10 * 3600]
        assert [d.seconds for d in board.effort_by_day] == [5 * 3600]

    async def test_an_epic_counts_as_an_item_but_never_as_its_own_child(
        self, session: AsyncSession
    ) -> None:
        """An epic is a Jira issue like any other, and the captions now say so.

        It counts in `totals` and against its assignee, so those two never disagree. It is
        not in its own `items`, which counts children — an epic containing itself would
        make every epic look one bigger than it is.
        """
        await GoldRepository(session).upsert_items(
            [_epic("MYC-6"), _item("MYC-7", parent_key="MYC-6")]
        )

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.totals == {"todo": 0, "doing": 2, "done": 0}
        assert [a.items for a in board.assignees] == [2]
        assert [(e.issue_key, e.items) for e in board.epics] == [("MYC-6", 1)]

    async def test_it_agrees_with_the_summariser_about_the_same_week(
        self, session: AsyncSession
    ) -> None:
        """One code path, so there is nothing for them to disagree over."""
        await GoldRepository(session).upsert_items([_epic(), _item()])

        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        window = await gather_progress(session, PROJECT, _at(15), _at(21))
        assert board.totals == window.totals
        assert board.assignees == window.by_assignee

    async def test_an_empty_project_is_an_empty_board(self, session: AsyncSession) -> None:
        """A project set up but not yet worked renders a blank page, not a 500."""
        board = await build_dashboard(session, PROJECT, _at(15), _at(21))
        assert board.totals == {"todo": 0, "doing": 0, "done": 0}
        assert (board.assignees, board.epics, board.overdue) == ([], [], [])


@needs_postgres
class TestATurnKeepsItsToolCalls:
    """`app.turn.steps`, so a thread reopened after the stream expired is not an empty
    middle (MYC-41)."""

    async def test_the_steps_come_back_as_they_were_written(
        self, session: AsyncSession
    ) -> None:
        repo = AppRepository(session)
        user = await repo.create_user("steps@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "what happened?")
        steps = [{"seq": 1, "agent": "analyst", "type": "tool_called", "payload": {"t": "sql"}}]

        await repo.upsert_turn(thread.id, "job-1", "q", "done", answer="a", steps=steps)

        kept = await repo.turn_by_job_id("job-1")
        assert kept is not None and kept.steps == steps

    async def test_a_later_write_without_steps_does_not_erase_them(
        self, session: AsyncSession
    ) -> None:
        """A redelivery that ends in failure must not wipe what a successful attempt
        already recorded."""
        repo = AppRepository(session)
        user = await repo.create_user("redeliver@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "what happened?")
        steps = [{"seq": 1, "agent": "analyst", "type": "tool_called", "payload": {}}]

        await repo.upsert_turn(thread.id, "job-2", "q", "done", answer="a", steps=steps)
        await repo.upsert_turn(thread.id, "job-2", "q", "failed", error="boom")

        kept = await repo.turn_by_job_id("job-2")
        assert kept is not None and kept.status == "failed" and kept.steps == steps


@needs_postgres
class TestForgettingAThread:
    """Delete is the one write in `app` that has to be scoped by hand.

    Nothing else in the sidebar can reach across users, because everything else reads by
    `user_id`. A delete takes an id from the URL, so the owner goes in the WHERE.
    """

    async def test_the_runs_under_it_go_too(self, session: AsyncSession) -> None:
        """`ON DELETE CASCADE` on `turn.conversation_id`, proved rather than assumed."""
        repo = AppRepository(session)
        user = await repo.create_user("keep@example.com", "x")
        thread = await repo.create_conversation(user.id, "chat", "what happened?")
        await repo.upsert_turn(thread.id, "job-1", "q", "done")

        assert await repo.delete_conversation(thread.id, user.id) is True
        assert await repo.turn_by_job_id("job-1") is None

    async def test_someone_elses_thread_is_left_alone(self, session: AsyncSession) -> None:
        repo = AppRepository(session)
        mine = await repo.create_user("mine@example.com", "x")
        theirs = await repo.create_user("theirs@example.com", "x")
        thread = await repo.create_conversation(theirs.id, "chat", "not yours")

        assert await repo.delete_conversation(thread.id, mine.id) is False
        assert await repo.conversation_by_id(thread.id) is not None
