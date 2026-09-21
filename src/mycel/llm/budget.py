"""Per-job cost ceiling.

Accumulate spend by job_id and raise instead of calling again once the ceiling is hit —
one agent stuck in a loop must not burn the monthly budget.

**Not "count tokens before sending".** That was the original design, and it is not
implementable once pydantic-ai owns the request: there is no seam between "prompt built"
and "prompt sent". The honest equivalent, and what this does:

  check()   refuse to *start* a run that has no headroom left — no call is made at all
  limits()  convert the job's remaining money into a per-run `cost_limit`, so pydantic-ai
            kills the run mid-flight rather than letting it run to completion

A single in-flight request can still overshoot slightly, because the ceiling is checked
between requests and not mid-token. That is accepted: the alternative is reimplementing
the provider's own accounting, and the overshoot is bounded by one request.

Different from `agents/core/guards.py`: this counts money across a whole job, guards count
behaviour within one run.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from mycel.core.exceptions import MycelError

if TYPE_CHECKING:
    from pydantic_ai.usage import RunUsage, UsageLimits

DEFAULT_CEILING_USD = Decimal("1.00")


class RunLimits(Protocol):
    """The per-run ceilings `limits()` needs, without importing `agents/`.

    `AgentSettings` satisfies this structurally. Stating it as a Protocol keeps the
    dependency pointing one way: `agents/` imports `llm/`, never the reverse.
    """

    @property
    def request_limit(self) -> int: ...
    @property
    def tool_calls_limit(self) -> int: ...
    @property
    def total_tokens_limit(self) -> int | None: ...


class BudgetExceeded(MycelError):
    """A job hit its cost ceiling. Raised instead of making another model call.

    Lives here rather than in `agents/`, because `llm/` sits below `agents/` and may not
    import upwards. Agents re-raise it unchanged.
    """

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
    """What one job is allowed to spend, and what it has spent so far.

    A job is many runs — the orchestrator's, each specialist's. `UsageLimits` dies at the
    end of each run, so accumulating across them is Mycel's own job.
    """

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

    def limits(self, cfg: RunLimits) -> "UsageLimits":
        """Per-run ceilings: the agent's own limits, capped by the job's remaining money."""
        from pydantic_ai.usage import UsageLimits

        return UsageLimits(
            request_limit=cfg.request_limit,
            tool_calls_limit=cfg.tool_calls_limit,
            total_tokens_limit=cfg.total_tokens_limit,
            cost_limit=self.remaining_usd(),
        )

    def record(self, usage: "RunUsage") -> None:
        """Charge one completed top-level run.

        Called from `runner.run` and nowhere else. Sub-agent tokens are already merged into
        the parent's `RunUsage` by `usage=ctx.usage` at the delegation site, so charging
        per-run would count every delegated token twice.

        Raises if this run took the job over — the run already happened and is paid for,
        but the next one must not start.
        """
        self.tokens += usage.total_tokens
        self.requests += usage.requests
        # `cost` is None when the provider's price is unknown. Tokens are still recorded,
        # so the run is visible in logs even when it cannot be priced.
        if usage.cost is not None:
            self.spent_usd += usage.cost

        if self.spent_usd >= self.ceiling_usd:
            raise BudgetExceeded(self.job_id, self.spent_usd, self.ceiling_usd)


# There is no `BudgetStore` abstraction here. There was one — a `Protocol` with `get`/`put`
# and an in-memory implementation — and it was never wired into anything, because by the
# time a job really did outlive a process the answer it needed was async, keyed by
# `job_id`, and had to merge rather than overwrite. See `infra/redis/budgets.py`, which
# seeds a `JobBudget` at the start of an attempt and writes the larger total back at the
# end. An interface with one implementation and no second caller is a guess about the
# future; this file keeps the arithmetic and lets the store live next to Redis.
