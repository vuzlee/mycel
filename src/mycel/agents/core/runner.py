"""The one place a run is started, so the one place money is counted.

Replaces the `hooks.py` this file was planned as. pydantic-ai has no per-run hook, and
wanting one turned out to be a symptom rather than a need: what the hooks were for was
charging the budget, and that belongs at a single call site, not spread across callbacks.

**Two entry points, and the difference between them is the whole design.**

`run_agent` starts a top-level run. It builds the model, converts Mycel's limits into
`UsageLimits`, records what the run cost, and translates the framework's exceptions into
Mycel's.

`run_child` is how an agent delegates to another agent. It forwards `usage=ctx.usage`, and
that single argument is why it must not touch the budget: pydantic-ai merges the child's
tokens into the parent's `RunUsage` as they are spent, so the parent's single `record()`
at the end already includes every delegated token. A child that also recorded would count
the same tokens twice — and the deeper the delegation, the worse the overcharge.

**Why `agent.iter()` rather than `await agent.run()`.** A run killed part-way by
`UsageLimitExceeded` has already spent real money. `await agent.run()` raises and hands
back nothing, so that spend never reaches the budget and the job quietly overdraws. `iter()`
exposes the usage on the run object, which a `finally` can read whether the run finished,
failed, or was stopped.
"""

from typing import TYPE_CHECKING, TypeVar

from mycel.agents.core.exceptions import translate_agent_errors
from mycel.agents.core.model_builder import build_model
from mycel.core.logging import get_logger

if TYPE_CHECKING:
    from pydantic_ai import Agent, RunContext

    from mycel.agents.core.config import AgentSettings
    from mycel.agents.core.deps import MycelDeps

OutputT = TypeVar("OutputT")

log = get_logger(__name__)


async def run_agent(
    agent: "Agent[MycelDeps, OutputT]",
    prompt: str,
    deps: "MycelDeps",
    settings: "AgentSettings | None" = None,
) -> OutputT:
    """Run an agent to completion, charging the job budget exactly once.

    Raises `BudgetExceeded` before spending anything if the job has no headroom left, and
    `RunawayStopped` if the run hits its own limits part-way — with whatever it spent up to
    that point already recorded.
    """
    cfg = settings or deps.settings
    deps.budget.check()

    model = build_model(cfg.model_spec, cfg)
    limits = deps.budget.limits(cfg)

    with translate_agent_errors(cfg.model_spec):
        async with agent.iter(
            prompt, deps=deps, model=model, usage_limits=limits
        ) as run:
            try:
                async for _node in run:
                    pass
            finally:
                # Charge whatever was spent, including on the path where the run was
                # stopped mid-way. This is the reason for iter() over run().
                deps.budget.record(run.usage)
                log.debug(
                    "run finished",
                    extra={
                        "job_id": deps.job_id,
                        "model_spec": cfg.model_spec,
                        "spent_usd": str(deps.budget.spent_usd),
                    },
                )

        result = run.result
        if result is None:  # pragma: no cover - iter() always sets it on success
            raise RuntimeError("agent run produced no result")
        return result.output


async def run_child(
    agent: "Agent[MycelDeps, OutputT]",
    prompt: str,
    ctx: "RunContext[MycelDeps]",
    settings: "AgentSettings | None" = None,
) -> OutputT:
    """Delegate from inside a tool to another agent, on the parent's budget.

    Deliberately does **not** call `budget.record()`. Passing `usage=ctx.usage` merges this
    run's tokens into the parent's usage, which the parent records when it finishes;
    recording here as well would bill every delegated token twice.
    """
    deps = ctx.deps
    cfg = settings or deps.settings
    model = build_model(cfg.model_spec, cfg)

    with translate_agent_errors(cfg.model_spec):
        result = await agent.run(
            prompt,
            deps=deps,
            model=model,
            usage=ctx.usage,
        )
    return result.output

