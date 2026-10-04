"""Per-job cost accumulation: the ceiling that stops a stuck agent burning the month.

Arithmetic only — `runner.run` wiring is covered in test_runner.py.
"""

from decimal import Decimal

import pytest
from pydantic_ai.usage import RunUsage

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.llm.budget import BudgetExceeded, JobBudget


def _usage(cost: str | None = "0.10", tokens: int = 100) -> RunUsage:
    return RunUsage(
        input_tokens=tokens,
        output_tokens=0,
        requests=1,
        cost=Decimal(cost) if cost is not None else None,
    )


class TestRemaining:
    def test_starts_at_the_ceiling(self) -> None:
        assert JobBudget("j", Decimal("1.00")).remaining_usd() == Decimal("1.00")

    def test_never_negative(self) -> None:
        """An overshot budget has zero headroom, not a debt to pay back."""
        b = JobBudget("j", Decimal("1.00"), spent_usd=Decimal("1.50"))
        assert b.remaining_usd() == Decimal(0)


class TestCheck:
    def test_passes_with_headroom(self) -> None:
        JobBudget("j", Decimal("1.00")).check()

    def test_raises_when_exhausted(self) -> None:
        """No model call is made at all — this is the cheap stop."""
        b = JobBudget("j", Decimal("1.00"), spent_usd=Decimal("1.00"))
        with pytest.raises(BudgetExceeded, match="j"):
            b.check()


class TestRecord:
    def test_accumulates_cost_and_tokens(self) -> None:
        b = JobBudget("j", Decimal("1.00"))
        b.record(_usage("0.10", tokens=100))
        b.record(_usage("0.15", tokens=50))
        assert b.spent_usd == Decimal("0.25")
        assert b.tokens == 150
        assert b.requests == 2

    def test_unpriced_run_still_counts_tokens(self) -> None:
        """A model with no known price must not vanish from the logs."""
        b = JobBudget("j", Decimal("1.00"))
        b.record(_usage(None, tokens=100))
        assert b.spent_usd == Decimal(0)
        assert b.tokens == 100

    def test_crossing_the_ceiling_raises(self) -> None:
        """The run already happened and is paid for; the next one must not start."""
        b = JobBudget("j", Decimal("0.20"))
        b.record(_usage("0.15"))
        with pytest.raises(BudgetExceeded):
            b.record(_usage("0.10"))
        assert b.spent_usd == Decimal("0.25")  # recorded, then raised


class TestLimits:
    def test_carries_the_agent_ceilings(self) -> None:
        cfg = AgentSettings(request_limit=5, tool_calls_limit=7)
        limits = JobBudget("j", Decimal("1.00")).limits(cfg)
        assert limits.request_limit == 5
        assert limits.tool_calls_limit == 7

    def test_cost_limit_is_what_is_left(self) -> None:
        """The run is capped mid-flight, not just checked before it starts."""
        b = JobBudget("j", Decimal("1.00"), spent_usd=Decimal("0.60"))
        assert b.limits(AgentSettings()).cost_limit == Decimal("0.40")


class TestDeps:
    def test_child_shares_the_budget_object(self) -> None:
        """The whole point: a delegated call spends the same pot as its parent."""
        parent = MycelDeps(job_id="j", budget=JobBudget("j", Decimal("1.00")))
        child = parent.child()
        assert child.budget is parent.budget
        assert child.job_id == parent.job_id

    def test_child_is_a_separate_object(self) -> None:
        parent = MycelDeps(job_id="j", budget=JobBudget("j", Decimal("1.00")))
        assert parent.child() is not parent


class TestPricingFromTheTable:
    """MYC-102: pydantic-ai cannot price a model named by the gateway, so the job budget
    falls back to the per-million-token table in config."""

    def test_a_listed_model_is_priced_per_million_tokens(self) -> None:
        from pydantic_ai.usage import RunUsage

        from mycel.llm.budget import price_usd

        prices = {"claude-sonnet-5": (Decimal("2"), Decimal("10"))}
        usage = RunUsage(input_tokens=4_000, output_tokens=200)
        assert price_usd(prices, "claude-sonnet-5", usage) == Decimal("0.010")

    def test_an_unlisted_model_has_no_price(self) -> None:
        from pydantic_ai.usage import RunUsage

        from mycel.llm.budget import price_usd

        assert price_usd({}, "gemini-3.6-flash", RunUsage(input_tokens=10)) is None

    def test_the_table_fills_in_when_pydantic_ai_cannot(self) -> None:
        b = JobBudget("j", Decimal("1.00"))
        b.record(_usage(None, tokens=100), fallback_cost=Decimal("0.25"))
        assert b.spent_usd == Decimal("0.25")

    def test_pydantic_ais_own_price_wins(self) -> None:
        b = JobBudget("j", Decimal("1.00"))
        b.record(_usage("0.10", tokens=100), fallback_cost=Decimal("0.25"))
        assert b.spent_usd == Decimal("0.10")

    def test_the_ceiling_still_stops_a_gateway_model(self) -> None:
        b = JobBudget("j", Decimal("0.50"))
        with pytest.raises(BudgetExceeded):
            b.record(_usage(None, tokens=100), fallback_cost=Decimal("0.60"))
