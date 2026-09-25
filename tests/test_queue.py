"""The job layer, against fakes rather than a running broker.

No RabbitMQ and no Redis: `docker compose up` is not a precondition for `pytest`, or the
suite stops being something anyone runs before pushing. What is worth pinning down here is
the failure behaviour, because every one of these fails *silently* in production — a job
acked too early is simply gone, and a job requeued at the head of the queue looks like a
busy worker rather than a spinning one.

`test_queue_live.py` is the other half: it runs against a real broker, where these fakes
cannot tell the truth about routing, and skips when there is none.

The agent is faked at `domains/chat.runner.run` rather than at the consumer, because
batch 013 moved what a job *means* into the domain: the consumer now receives, dispatches
and acks, and that is all it is tested for here.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from mycel.agents.core.exceptions import AgentError
from mycel.domains import chat as chat_domain
from mycel.infra.redis import budgets, results
from mycel.llm.budget import BudgetExceeded, JobBudget
from mycel.queue import consumer, retry, topology
from mycel.queue.job import Job, JobKind
from mycel.services.auth import Principal

pytestmark = pytest.mark.anyio


class FakeExchange:
    """Records what would have been published, and where."""

    def __init__(self) -> None:
        self.published: list[tuple[Any, str]] = []

    async def publish(self, message: Any, routing_key: str = "") -> None:
        self.published.append((message, routing_key))


class FakeMessage:
    """An incoming message, with just the surface the consumer touches."""

    def __init__(self, body: bytes, headers: dict[str, Any] | None = None) -> None:
        self.body = body
        self.headers: dict[str, Any] = headers or {}
        self.content_type = "application/json"
        self.message_id = "job-1"
        self.correlation_id = "chat:abc"
        self.acked = False
        self.nacked = False

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, requeue: bool = True) -> None:
        self.nacked = True


def _message(question: str = "how many?", **headers: Any) -> FakeMessage:
    job = Job(kind=JobKind.CHAT, payload={"question": question, "user_id": 1}, job_id="job-1")
    return FakeMessage(job.model_dump_json().encode(), dict(headers))


@pytest.fixture(autouse=True)
def asker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Who the job belongs to, without the `app.user` lookup behind it.

    The lookup is real work in production — a job whose account was deleted must not run —
    but it is a round trip to Postgres, and every test in this file is about the queue.
    """

    async def _who(job: Job) -> Principal:
        user_id = job.payload.get("user_id")
        if not isinstance(user_id, int):
            raise ValueError("chat job has no user_id")
        return Principal(id=user_id, email="someone@example.com")

    monkeypatch.setattr(chat_domain, "_who_asked", _who)


@pytest.fixture
def spent(monkeypatch: pytest.MonkeyPatch) -> dict[str, Decimal]:
    """A budget store that keeps the running total in a dict instead of in Redis.

    It merges the same way the Lua script does — larger wins — so a test can show an
    attempt inheriting what the one before it spent.
    """
    totals: dict[str, Decimal] = {}

    async def load(job_id: str, ceiling_usd: Decimal | str) -> JobBudget:
        return JobBudget(job_id, Decimal(ceiling_usd), spent_usd=totals.get(job_id, Decimal(0)))

    async def save(budget: JobBudget) -> None:
        totals[budget.job_id] = max(totals.get(budget.job_id, Decimal(0)), budget.spent_usd)

    monkeypatch.setattr(budgets, "load", load)
    monkeypatch.setattr(budgets, "save", save)
    return totals


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, spent: dict[str, Decimal]) -> dict[str, Any]:
    """Capture what the worker would have written, instead of writing to Redis.

    Depends on `spent` so no test in this file can reach a real Redis by forgetting it.
    """
    written: dict[str, Any] = {}

    async def mark_running(job_id: str) -> None:
        written[job_id] = {"status": "running"}

    async def store_result(job_id: str, answer: Any, spent_usd: str) -> None:
        written[job_id] = {"status": "done", "spent_usd": spent_usd}

    async def store_failure(job_id: str, error: str) -> None:
        written[job_id] = {"status": "failed", "error": error}

    monkeypatch.setattr(results, "mark_running", mark_running)
    monkeypatch.setattr(results, "store", store_result)
    monkeypatch.setattr(results, "store_failure", store_failure)
    return written


def _runs(monkeypatch: pytest.MonkeyPatch, outcome: str | Exception) -> None:
    """Make the orchestrator return or raise, with no model anywhere in sight."""

    async def fake_run(agent: object, prompt: str, deps: Any) -> str:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(chat_domain.runner, "run", fake_run)


_ANSWER = "42, and here is why."


@asynccontextmanager
async def _no_session() -> AsyncIterator[None]:
    """Stands in for `session_scope`, so no test here opens a database connection."""
    yield None


class _GoneThread:
    """An `AppRepository` whose conversation has been deleted underneath it."""

    def __init__(self, session: Any) -> None:
        pass

    async def upsert_turn(self, *args: Any, **kwargs: Any) -> None:
        raise IntegrityError("INSERT INTO app.turn", {}, Exception("foreign key"))


class TestIdempotencyKey:
    """The one thing at-least-once delivery makes mandatory."""

    def test_the_same_work_gets_the_same_key(self) -> None:
        a = Job(kind=JobKind.CHAT, payload={"question": "revenue?"})
        b = Job(kind=JobKind.CHAT, payload={"question": "revenue?"})
        assert a.idempotency_key == b.idempotency_key
        # ...while still being two distinct attempts, so both callers can poll.
        assert a.job_id != b.job_id

    def test_key_order_does_not_change_the_key(self) -> None:
        """Two dicts equal in Python must not hash differently, or the key is useless."""
        a = Job(kind=JobKind.CHAT, payload={"a": 1, "b": 2})
        b = Job(kind=JobKind.CHAT, payload={"b": 2, "a": 1})
        assert a.idempotency_key == b.idempotency_key

    def test_different_work_gets_a_different_key(self) -> None:
        a = Job(kind=JobKind.CHAT, payload={"question": "revenue?"})
        b = Job(kind=JobKind.CHAT, payload={"question": "headcount?"})
        assert a.idempotency_key != b.idempotency_key

    def test_a_caller_may_supply_its_own(self) -> None:
        job = Job(kind=JobKind.CHAT, payload={"q": 1}, idempotency_key="nightly-2026-09-18")
        assert job.idempotency_key == "nightly-2026-09-18"


class TestSuccess:
    async def test_the_job_is_acked_only_after_the_work_is_done(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        """Ack order is the whole reason a dying worker does not lose a job."""
        seen: list[str] = []

        async def fake_run(agent: object, prompt: str, deps: Any) -> str:
            seen.append("ran")
            return _ANSWER

        monkeypatch.setattr(chat_domain.runner, "run", fake_run)

        message = _message()
        original_ack = message.ack

        async def recording_ack() -> None:
            seen.append("acked")
            await original_ack()

        message.ack = recording_ack  # type: ignore[method-assign]

        await consumer.handle(message, FakeExchange())  # type: ignore[arg-type]
        assert seen == ["ran", "acked"]

    async def test_the_answer_is_stored_for_the_caller(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        """The API has only a job id; without this the work happened for nobody."""
        _runs(monkeypatch, _ANSWER)
        await consumer.handle(_message(), FakeExchange())  # type: ignore[arg-type]
        assert store["job-1"]["status"] == "done"


class TestFailures:
    """Split by whether another attempt could possibly help."""

    async def test_a_transient_failure_goes_to_the_retry_queue(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        _runs(monkeypatch, AgentError("provider returned 503"))
        dlx = FakeExchange()
        message = _message()

        await consumer.handle(message, dlx)  # type: ignore[arg-type]

        assert [key for _, key in dlx.published] == [topology.RETRY_QUEUE]
        # Acked, not nacked: the copy carries the job onward, so the original must go.
        assert message.acked and not message.nacked

    async def test_a_transient_failure_is_not_yet_reported_as_failed(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        """A caller polling between attempts must not be told the job is dead."""
        _runs(monkeypatch, AgentError("provider returned 503"))
        await consumer.handle(_message(), FakeExchange())  # type: ignore[arg-type]
        assert store["job-1"]["status"] == "running"

    async def test_the_last_attempt_lands_in_the_dead_letter_queue(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        _runs(monkeypatch, AgentError("still down"))
        dlx = FakeExchange()
        message = _message(**{retry.ATTEMPT_HEADER: topology.MAX_ATTEMPTS - 1})

        await consumer.handle(message, dlx)  # type: ignore[arg-type]

        assert [key for _, key in dlx.published] == [topology.DEAD_QUEUE]
        assert store["job-1"]["status"] == "failed"

    async def test_running_out_of_money_skips_the_retries(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        """Retrying spends money the job does not have, however long we wait."""
        _runs(monkeypatch, BudgetExceeded("job-1", Decimal("0.51"), Decimal("0.50")))
        dlx = FakeExchange()

        await consumer.handle(_message(), dlx)  # type: ignore[arg-type]

        assert [key for _, key in dlx.published] == [topology.DEAD_QUEUE]
        assert store["job-1"]["status"] == "failed"

    async def test_an_unreadable_body_skips_the_retries(self) -> None:
        """It will be just as unreadable in a minute."""
        dlx = FakeExchange()
        message = FakeMessage(b"{not json")

        await consumer.handle(message, dlx)  # type: ignore[arg-type]

        assert [key for _, key in dlx.published] == [topology.DEAD_QUEUE]
        assert message.acked

    async def test_a_bug_in_the_job_does_not_kill_the_consumer(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        """One bad job must not take the worker down with it."""
        _runs(monkeypatch, ZeroDivisionError("oops"))
        dlx = FakeExchange()

        await consumer.handle(_message(), dlx)  # type: ignore[arg-type]

        assert [key for _, key in dlx.published] == [topology.DEAD_QUEUE]

    async def test_a_thread_deleted_mid_run_does_not_strand_the_job(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        """The row the run would be written to went with the thread it hung off.

        Both the success path and the failure path write that same row, so an exception
        here escapes `_handle` entirely: the message is never acked and the broker
        redelivers it at `consumer_timeout` to fail the same way. Recorded as a warning
        instead, and the job is acked and done with.
        """
        _runs(monkeypatch, _ANSWER)
        monkeypatch.setattr(chat_domain, "session_scope", _no_session)
        monkeypatch.setattr(chat_domain, "AppRepository", _GoneThread)

        job = Job(
            kind=JobKind.CHAT,
            payload={"question": "how many?", "conversation_id": 22, "user_id": 1},
            job_id="job-1",
        )
        message = FakeMessage(job.model_dump_json().encode())

        await consumer.handle(message, FakeExchange())  # type: ignore[arg-type]

        assert message.acked
        assert store["job-1"]["status"] == "done"

    async def test_a_chat_job_with_no_question_is_not_retried_forever(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]
    ) -> None:
        dlx = FakeExchange()
        job = Job(kind=JobKind.CHAT, payload={}, job_id="job-1")
        message = FakeMessage(job.model_dump_json().encode())

        await consumer.handle(message, dlx)  # type: ignore[arg-type]

        assert [key for _, key in dlx.published] == [topology.DEAD_QUEUE]


class TestAKindThisWorkerDoesNotKnow:
    async def test_a_kind_this_worker_does_not_know_is_an_unreadable_body(
        self, store: dict[str, Any]
    ) -> None:
        """A worker older than the producer that queued the job. `JobKind` rejects it while
        parsing, before any handler is chosen, and it goes straight to the dead letters —
        another attempt on the same worker would fail the same way."""
        dlx = FakeExchange()
        body = b'{"kind":"librarian","payload":{},"job_id":"job-1","idempotency_key":"k"}'

        await consumer.handle(FakeMessage(body), dlx)  # type: ignore[arg-type]

        assert [key for _, key in dlx.published] == [topology.DEAD_QUEUE]


class TestAttemptCounting:
    def test_a_message_with_no_header_is_a_first_attempt(self) -> None:
        """Published by an older deployment, or by hand through the management UI."""
        assert retry.attempt_of(FakeMessage(b"{}")) == 0  # type: ignore[arg-type]

    def test_a_malformed_counter_is_not_a_crash(self) -> None:
        message = FakeMessage(b"{}", {retry.ATTEMPT_HEADER: "not a number"})
        assert retry.attempt_of(message) == 0  # type: ignore[arg-type]

    def test_the_counter_travels_with_the_job(self) -> None:
        message = FakeMessage(b"{}", {retry.ATTEMPT_HEADER: 2})
        assert retry.attempt_of(message) == 2  # type: ignore[arg-type]
        assert retry.exhausted(message) is (3 >= topology.MAX_ATTEMPTS)

    async def test_republishing_increments_it(self) -> None:
        dlx = FakeExchange()
        message = FakeMessage(b"{}", {retry.ATTEMPT_HEADER: 0})

        await retry.reject(message, dlx, reason="nope")  # type: ignore[arg-type]

        published, _ = dlx.published[0]
        assert published.headers[retry.ATTEMPT_HEADER] == 1

    async def test_giving_up_marks_the_counter_spent(self) -> None:
        """So a message inspected in the DLQ says why it stopped, not just that it did."""
        dlx = FakeExchange()
        message = FakeMessage(b"{}", {retry.ATTEMPT_HEADER: 0})

        await retry.reject(message, dlx, reason="no point", give_up=True)

        published, key = dlx.published[0]
        assert key == topology.DEAD_QUEUE
        assert published.headers[retry.ATTEMPT_HEADER] == topology.MAX_ATTEMPTS


class TestWhatTravelsWithAFailedJob:
    async def test_the_body_is_carried_through_unchanged(self) -> None:
        """A job in the DLQ has to be re-runnable, which means it must still be a job."""
        dlx = FakeExchange()
        message = _message("how many tickets?")

        await retry.reject(message, dlx, reason="down")  # type: ignore[arg-type]

        published, _ = dlx.published[0]
        payload = Job.model_validate_json(published.body).payload
        assert payload == {"question": "how many tickets?", "user_id": 1}

    async def test_the_reason_is_attached(self) -> None:
        dlx = FakeExchange()
        await retry.reject(FakeMessage(b"{}"), dlx, reason="provider 503")  # type: ignore[arg-type]
        published, _ = dlx.published[0]
        assert "provider 503" in published.headers["mycel-error"]


class TestTheBudgetSurvivesARetry:
    """The ceiling is per job, and a job is up to `MAX_ATTEMPTS` attempts.

    Every case here used to pass while costing three times what it was allowed to, because
    each attempt built a fresh `JobBudget` starting at zero.
    """

    async def test_an_attempt_starts_from_what_the_job_has_already_spent(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any], spent: dict[str, Decimal]
    ) -> None:
        spent["job-1"] = Decimal("0.30")
        seen: list[Decimal] = []

        async def fake_run(agent: object, prompt: str, deps: Any) -> str:
            seen.append(deps.budget.spent_usd)
            return _ANSWER

        monkeypatch.setattr(chat_domain.runner, "run", fake_run)
        await consumer.handle(_message(), FakeExchange())  # type: ignore[arg-type]

        assert seen == [Decimal("0.30")]

    async def test_what_an_attempt_spends_is_published(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any], spent: dict[str, Decimal]
    ) -> None:
        async def fake_run(agent: object, prompt: str, deps: Any) -> str:
            deps.budget.spent_usd = Decimal("0.20")
            return _ANSWER

        monkeypatch.setattr(chat_domain.runner, "run", fake_run)
        await consumer.handle(_message(), FakeExchange())  # type: ignore[arg-type]

        assert spent["job-1"] == Decimal("0.20")

    async def test_a_failed_attempt_still_publishes_what_it_spent(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any], spent: dict[str, Decimal]
    ) -> None:
        """The expensive case: a run that dies half-way has already paid for its tokens."""

        async def fake_run(agent: object, prompt: str, deps: Any) -> str:
            deps.budget.spent_usd = Decimal("0.40")
            raise AgentError("provider returned 503")

        monkeypatch.setattr(chat_domain.runner, "run", fake_run)
        await consumer.handle(_message(), FakeExchange())  # type: ignore[arg-type]

        assert spent["job-1"] == Decimal("0.40")

    async def test_a_job_out_of_money_is_refused_before_the_model_is_called(
        self, monkeypatch: pytest.MonkeyPatch, store: dict[str, Any], spent: dict[str, Decimal]
    ) -> None:
        """Seeded over the ceiling, `runner.run`'s own `budget.check()` stops the attempt.

        `runner.run` is real here — faking it would fake away the thing being tested.
        """
        spent["job-1"] = Decimal("0.99")
        dlx = FakeExchange()
        message = _message()

        await consumer.handle(message, dlx)  # type: ignore[arg-type]

        # Straight to the dead-letter queue: another attempt spends money the job has not
        # got, so this is not a transient failure.
        assert [key for _, key in dlx.published] == [topology.DEAD_QUEUE]
        assert store["job-1"]["status"] == "failed"
