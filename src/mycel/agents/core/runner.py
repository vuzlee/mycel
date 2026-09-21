"""The one place a run is started, so the one place money is counted.

**Two entry points, and the difference between them is the whole design.**

`run` starts a job's first agent. It builds the model, converts Mycel's limits into
`UsageLimits`, records what the run cost, and translates the framework's exceptions into
Mycel's. `run_sync` is the same thing for callers that have no event loop.

`delegate` is how an agent calls another agent, from inside one of its tools. It forwards
`usage=ctx.usage`, and that single argument is why it must not touch the budget:
pydantic-ai merges the delegate's tokens into the caller's `RunUsage` as they are spent, so
the caller's single `record()` at the end already includes every delegated token. A
delegate that also recorded would count the same tokens twice — and the deeper the
delegation, the worse the overcharge.

This is delegation, not handoff: the caller keeps control and receives the output as a tool
result, rather than stepping aside for the agent it called.

**Why `agent.iter()` rather than `await agent.run()`.** A run killed part-way by
`UsageLimitExceeded` has already spent real money. `await agent.run()` raises and hands
back nothing, so that spend never reaches the budget and the job quietly overdraws. `iter()`
exposes the usage on the run object, which a `finally` can read whether the run finished,
failed, or was stopped.
"""

import asyncio
from typing import TYPE_CHECKING, TypeVar

from mycel.agents.core.emit import RUN_FINISHED, RUN_STARTED, RunEmitter
from mycel.agents.core.exceptions import translate_agent_errors
from mycel.agents.core.model_builder import build_model
from mycel.core.logging import get_logger
from mycel.llm.budget import BudgetExceeded

if TYPE_CHECKING:
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.usage import RunUsage

    from mycel.agents.core.config import AgentSettings
    from mycel.agents.core.deps import MycelDeps

OutputT = TypeVar("OutputT")

log = get_logger(__name__)


async def run(
    agent: "Agent[MycelDeps, OutputT]",
    prompt: str,
    deps: "MycelDeps",
    settings: "AgentSettings | None" = None,
    parent_tool_call_id: str | None = None,
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
    emitter = RunEmitter(deps, _name_of(agent), parent_tool_call_id)

    overdrawn: BudgetExceeded | None = None

    with translate_agent_errors(cfg.model_spec):
        async with agent.iter(prompt, deps=deps, model=model, usage_limits=limits) as agent_run:
            try:
                await emitter.emit(RUN_STARTED, prompt=prompt)
                # One node per step of the agent loop: prompt, model request, tool calls,
                # back to the model.
                async for node in agent_run:
                    await emitter.node(node)
                await emitter.emit(RUN_FINISHED)
            finally:
                # `agent_run` exists before the loop runs and outlives it failing, so its
                # usage is readable even when the run was stopped part-way. That is the
                # whole reason for iter() over run(), whose usage dies with the result.
                overdrawn = _charge(deps, cfg, agent_run.usage)

        result = agent_run.result
        if result is None:  # pragma: no cover - iter() always sets it on success
            raise RuntimeError("agent run produced no result")

    # Raised out here, never from the `finally` above: an exception there would replace
    # whatever stopped the run, hiding the real cause behind a bookkeeping error.
    if overdrawn is not None:
        raise overdrawn
    return result.output


def run_sync(
    agent: "Agent[MycelDeps, OutputT]",
    prompt: str,
    deps: "MycelDeps",
    settings: "AgentSettings | None" = None,
) -> OutputT:
    """`run` for callers with no event loop: scripts, sync tests, a CLI.

    Raises if a loop is already running — `asyncio.run` cannot nest, and the caller in that
    position wants `await run(...)` anyway.
    """
    return asyncio.run(run(agent, prompt, deps, settings))


def _name_of(agent: "Agent[MycelDeps, OutputT]") -> str:
    """The agent's registry name, which is what a client groups events by."""
    return agent.name or "agent"


def _charge(deps: "MycelDeps", cfg: "AgentSettings", usage: "RunUsage") -> BudgetExceeded | None:
    """Record one run's spend, returning the overdraft rather than raising it."""
    try:
        deps.budget.record(usage)
        overdrawn = None
    except BudgetExceeded as exc:
        overdrawn = exc

    log.debug(
        "run finished",
        extra={
            "job_id": deps.job_id,
            "model_spec": cfg.model_spec,
            "spent_usd": str(deps.budget.spent_usd),
        },
    )
    return overdrawn


async def delegate(
    agent: "Agent[MycelDeps, OutputT]",
    prompt: str,
    ctx: "RunContext[MycelDeps]",
    settings: "AgentSettings | None" = None,
) -> OutputT:
    """Call another agent from inside a tool, on the caller's budget.

    Deliberately does **not** call `budget.record()`. Passing `usage=ctx.usage` merges this
    run's tokens into the caller's usage, which the caller records when it finishes;
    recording here as well would bill every delegated token twice.

    Async only: it exists to be awaited inside a tool, which is already in a running loop.
    """
    deps = ctx.deps
    cfg = settings or deps.settings
    model = build_model(cfg.model_spec, cfg)
    emitter = RunEmitter(deps, _name_of(agent), ctx.tool_call_id)

    with translate_agent_errors(cfg.model_spec):
        async with agent.iter(prompt, deps=deps, model=model, usage=ctx.usage) as agent_run:
            await emitter.emit(RUN_STARTED, prompt=prompt)
            async for node in agent_run:
                await emitter.node(node)
            await emitter.emit(RUN_FINISHED)

        result = agent_run.result
        if result is None:  # pragma: no cover - iter() always sets it on success
            raise RuntimeError("agent run produced no result")
    return result.output
