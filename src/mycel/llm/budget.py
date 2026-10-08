"""Per-job cost ceiling, accumulated across every run in the job.

`check()` refuses to start a run with no headroom; `limits()` turns what is left into a
per-run `cost_limit`. One in-flight request may overshoot.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from mycel.core.exceptions import MycelError

if TYPE_CHECKING:
    from pydantic_ai.usage import RunUsage, UsageLimits

DEFAULT_CEILING_USD = Decimal("1.00")


class RunLimits(Protocol):
    """Per-run ceilings `limits()` needs; `AgentSettings` fits, without importing `agents/`."""

    @property
    def request_limit(self) -> int: ...
    @property
    def tool_calls_limit(self) -> int: ...
    @property
    def total_tokens_limit(self) -> int | None: ...


class BudgetExceeded(MycelError):
    """A job hit its cost ceiling. Raised instead of making another model call."""

    def __init__(self, job_id: str, spent: Decimal, ceiling: Decimal) -> None:
        super().__init__(
            f"job {job_id} has spent ${spent} of its ${ceiling} ceiling; "
            "no further model calls will be made"
        )
        self.job_id = job_id
        self.spent = spent
        self.ceiling = ceiling


@dataclass
class JobBudget:
    """What one job may spend and has spent, across all of its runs."""

    job_id: str
    ceiling_usd: Decimal = DEFAULT_CEILING_USD
    spent_usd: Decimal = Decimal(0)
    tokens: int = 0
    requests: int = 0

    def remaining_usd(self) -> Decimal:
        """Never negative — an overshot budget has zero headroom, not a debt."""
        return max(Decimal(0), self.ceiling_usd - self.spent_usd)

    def check(self) -> None:
        """Raise before starting a run with no room left. No model call is made."""
        if self.remaining_usd() <= 0:
            raise BudgetExceeded(self.job_id, self.spent_usd, self.ceiling_usd)

    def limits(self, cfg: RunLimits, spent: "RunUsage | None" = None) -> "UsageLimits":
        """The agent's limits, capped by the job's remaining money.

        `spent` is a delegated run's inherited counters; limits are added on top of them.
        """
        from pydantic_ai.usage import UsageLimits

        def after(limit: int | None, already: int) -> int | None:
            return None if limit is None else limit + already

        return UsageLimits(
            request_limit=after(cfg.request_limit, spent.requests if spent else 0),
            tool_calls_limit=after(cfg.tool_calls_limit, spent.tool_calls if spent else 0),
            total_tokens_limit=after(cfg.total_tokens_limit, spent.total_tokens if spent else 0),
            cost_limit=self.remaining_usd(),
        )

    def record(self, usage: "RunUsage", fallback_cost: Decimal | None = None) -> None:
        """Charge one top-level run (sub-agent usage is already merged in); raise if over."""
        self.tokens += usage.total_tokens
        self.requests += usage.requests
        # pydantic-ai cannot price gateway models; the caller's price table fills in.
        cost = usage.cost if usage.cost is not None else fallback_cost
        if cost is not None:
            self.spent_usd += Decimal(cost)

        if self.spent_usd >= self.ceiling_usd:
            raise BudgetExceeded(self.job_id, self.spent_usd, self.ceiling_usd)


def price_usd(
    prices: "dict[str, tuple[Decimal, Decimal]]", model: str, usage: "RunUsage"
) -> Decimal | None:
    """Cost of a run from a per-million-token table, or `None` for a model not in it."""
    found = prices.get(model)
    if found is None:
        return None
    per_input, per_output = found
    million = Decimal(1_000_000)
    return (usage.input_tokens * per_input + usage.output_tokens * per_output) / million
