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
from contextlib import contextmanager
from typing import TYPE_CHECKING, TypeVar

from pydantic_ai import Agent
from pydantic_ai.models import Model

from mycel.agents.core.emit import RUN_FINISHED, RUN_STARTED, RunEmitter
from mycel.agents.core.exceptions import translate_agent_errors
from mycel.agents.core.model_builder import build_model, note_failure
from mycel.core.logging import get_logger
from mycel.llm.budget import BudgetExceeded
from mycel.observability.metrics import tokens_spent_total

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic_ai import RunContext
    from pydantic_ai.agent import AgentRun
    from pydantic_ai.usage import RunUsage

    from mycel.agents.core.config import AgentSettings
    from mycel.agents.core.deps import MycelDeps

OutputT = TypeVar("OutputT")

log = get_logger(__name__)


@contextmanager
def _benching_the_key(model: Model) -> "Iterator[None]":
    """Let the key ring hear about a credential failure, then re-raise unchanged.

    Inside `translate_agent_errors` so it still sees the provider's own exception: the
    status code and the body are what say whether a 429 was a burst or the day's quota, and
    translation replaces both with a sentence. It changes nothing about the error — a key
    being benched is bookkeeping, not a different failure.
    """
    try:
        yield
    except Exception as exc:
        note_failure(model, exc)
        raise


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

    with translate_agent_errors(cfg.model_spec), _benching_the_key(model):
        async with agent.iter(prompt, deps=deps, model=model, usage_limits=limits) as agent_run:
            try:
                await emitter.emit(RUN_STARTED, prompt=prompt)
                await _drive(agent_run, emitter)
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


async def _drive(agent_run: "AgentRun[MycelDeps, OutputT]", emitter: RunEmitter) -> None:
    """Walk one agent loop, emitting as it goes.

    One node per step: prompt, model request, tool calls, back to the model. A model request
    is opened as a stream so its prose goes out while it is written; everything else is
    emitted from the finished node. A model that cannot stream raises on `stream()` before
    doing any work, and the ordinary iteration runs the node instead — the answer then
    arrives as one `TEXT` event, which reads the same.
    """
    async for node in agent_run:
        if Agent.is_model_request_node(node) and _can_stream(agent_run.ctx.deps.model):
            async with node.stream(agent_run.ctx) as chunks:
                await emitter.stream(chunks)
        await emitter.node(node)


def _can_stream(model: "Model") -> bool:
    """Whether opening this model as a stream is safe to try.

    Asking has to happen before the attempt, not after: `stream()` marks the node as
    streamed on its way to failing, and the node cannot then be run the ordinary way.
    `FunctionModel`, which the tests use, declares `request_stream` and then asserts on a
    `stream_function` it was not given — hence the second question.
    """
    if type(model).request_stream is Model.request_stream:
        return False
    return getattr(model, "stream_function", False) is not None


def _name_of(agent: "Agent[MycelDeps, OutputT]") -> str:
    """The agent's registry name, which is what a client groups events by."""
    return agent.name or "agent"


def _charge(deps: "MycelDeps", cfg: "AgentSettings", usage: "RunUsage") -> BudgetExceeded | None:
    """Record one run's spend, returning the overdraft rather than raising it."""
    # The same place and for the same reason as the budget: `usage` here already carries
    # every delegated token, so counting at the delegation site too would double it. The
    # label is the spec, not the job — a job id would mint a series per job forever.
    tokens_spent_total.labels(model=cfg.model_spec, direction="input").inc(usage.input_tokens)
    tokens_spent_total.labels(model=cfg.model_spec, direction="output").inc(usage.output_tokens)

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

    with translate_agent_errors(cfg.model_spec), _benching_the_key(model):
        async with agent.iter(prompt, deps=deps, model=model, usage=ctx.usage) as agent_run:
            await emitter.emit(RUN_STARTED, prompt=prompt)
            await _drive(agent_run, emitter)
            await emitter.emit(RUN_FINISHED)

        result = agent_run.result
        if result is None:  # pragma: no cover - iter() always sets it on success
            raise RuntimeError("agent run produced no result")
    return result.output
