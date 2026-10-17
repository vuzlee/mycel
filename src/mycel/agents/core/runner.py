"""Start agent runs and count their cost.

`run` starts a job's first agent and records its spend on the budget. `delegate` runs an
agent from inside a tool with `usage=ctx.usage`, so its tokens merge into the caller's and
are recorded once, by the caller. `iter()` rather than `run()` so a run stopped part-way
still reports what it spent.
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, TypeVar

from pydantic_ai import Agent
from pydantic_ai.models import Model

from mycel.agents.core.emit import RunEmitter
from mycel.agents.core.exceptions import translate_agent_errors
from mycel.agents.core.model_builder import build_model, build_own_model
from mycel.core import redact
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.events.event import RUN_FINISHED, RUN_STARTED
from mycel.infra.redis import key_rotation
from mycel.llm.budget import BudgetExceeded, own_price, price_usd
from mycel.llm.quota import cooldown_seconds
from mycel.llm.router import resolve
from mycel.observability.metrics import tokens_spent_total

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from pydantic_ai import RunContext
    from pydantic_ai.agent import AgentRun
    from pydantic_ai.usage import RunUsage, UsageLimits

    from mycel.agents.core.config import AgentSettings
    from mycel.agents.core.deps import MycelDeps

OutputT = TypeVar("OutputT")

log = get_logger(__name__)


async def run(
    agent: "Agent[MycelDeps, OutputT]",
    prompt: str,
    deps: "MycelDeps",
    settings: "AgentSettings | None" = None,
) -> OutputT:
    """Run an agent to completion and charge the job budget once."""
    cfg = settings or deps.settings
    deps.budget.check()
    overdrawn: BudgetExceeded | None = None

    def charge(usage: "RunUsage") -> None:
        nonlocal overdrawn
        overdrawn = _record_usage(deps, cfg, usage)

    output = await _iterate(agent, prompt, deps, cfg, deps.budget.limits(cfg), None, None, charge)
    # Raised after the run, so a bookkeeping error never hides what stopped it.
    if overdrawn is not None:
        raise overdrawn
    return output


async def _iterate_nodes(agent_run: "AgentRun[MycelDeps, OutputT]", emitter: RunEmitter) -> None:
    """Walk one agent loop, streaming model requests where the model supports it."""
    async for node in agent_run:
        if Agent.is_model_request_node(node) and _can_stream(agent_run.ctx.deps.model):
            async with node.stream(agent_run.ctx) as chunks:
                await emitter.stream(chunks)
        await emitter.node(node)


def _can_stream(model: "Model") -> bool:
    """Whether `stream()` is safe to try; a failed attempt leaves the node unrunnable."""
    if type(model).request_stream is Model.request_stream:
        return False
    return getattr(model, "stream_function", False) is not None


def _name_of(agent: "Agent[MycelDeps, OutputT]") -> str:
    return agent.name or "agent"


def _record_usage(
    deps: "MycelDeps", cfg: "AgentSettings", usage: "RunUsage"
) -> BudgetExceeded | None:
    """Record one run's spend, returning the overdraft rather than raising it."""
    # `usage` already includes delegated tokens, so count only here.
    name = model_name(deps, cfg)
    tokens_spent_total.labels(model=name, direction="input").inc(usage.input_tokens)
    tokens_spent_total.labels(model=name, direction="output").inc(usage.output_tokens)

    if deps.own is not None:
        price = own_price(deps.own.endpoint_model, deps.own.api_base, usage)
    else:
        price = price_usd(get_settings().model_prices_usd, resolve(cfg.model_spec).name, usage)
    try:
        deps.budget.record(usage, price)
        overdrawn = None
    except BudgetExceeded as exc:
        overdrawn = exc

    log.debug(
        "run finished",
        extra={
            "job_id": deps.job_id,
            "model_spec": name,
            "spent_usd": str(deps.budget.spent_usd),
        },
    )
    return overdrawn


def model_name(deps: "MycelDeps", cfg: "AgentSettings") -> str:
    """What answers this run: the own model when the asker picked one, else the gateway's."""
    return f"own:{deps.own.endpoint_model}" if deps.own is not None else cfg.model_spec


async def delegate(
    agent: "Agent[MycelDeps, OutputT]",
    prompt: str,
    ctx: "RunContext[MycelDeps]",
    settings: "AgentSettings | None" = None,
) -> OutputT:
    """Run another agent from a tool, on the caller's usage and limits; records nothing."""
    cfg = settings or ctx.deps.settings
    limits = ctx.deps.budget.limits(cfg, spent=ctx.usage)
    return await _iterate(agent, prompt, ctx.deps, cfg, limits, ctx.usage, ctx.tool_call_id)


async def _iterate(
    agent: "Agent[MycelDeps, OutputT]",
    prompt: str,
    deps: "MycelDeps",
    cfg: "AgentSettings",
    limits: "UsageLimits",
    usage: "RunUsage | None",
    parent_tool_call_id: str | None,
    on_usage: "Callable[[RunUsage], None] | None" = None,
) -> OutputT:
    emitter = RunEmitter(deps, _name_of(agent), parent_tool_call_id)
    async with _model_for(deps, cfg) as (model, name):
        with translate_agent_errors(name):
            async with agent.iter(
                prompt, deps=deps, model=model, usage=usage, usage_limits=limits
            ) as agent_run:
                try:
                    await emitter.emit(RUN_STARTED, prompt=prompt)
                    await _iterate_nodes(agent_run, emitter)
                    await emitter.emit(RUN_FINISHED)
                finally:
                    if on_usage is not None:
                        on_usage(agent_run.usage)
            result = agent_run.result
            if result is None:  # pragma: no cover - iter() always sets it on success
                raise RuntimeError("agent run produced no result")
    return result.output


@asynccontextmanager
async def _model_for(deps: "MycelDeps", cfg: "AgentSettings") -> "AsyncIterator[tuple[Model, str]]":
    """The gateway model, or the run's own model with its per-run clients closed after."""
    if deps.own is None:
        yield build_model(cfg.model_spec, cfg), cfg.model_spec
        return
    own = deps.own

    async def set_aside(position: int, status: int, error: str) -> None:
        log.warning(
            "own model key set aside",
            extra={
                "job_id": deps.job_id,
                "own_model": own.model_id,
                "key": position,
                "status": status,
            },
        )
        await key_rotation.cool(own.model_id, position, cooldown_seconds(status, error))

    model, clients = build_own_model(own, cfg, set_aside)
    try:
        with redact.holding(*(key.get_secret_value() for _, key in own.keys)):
            yield model, own.label
    finally:
        for client in clients:
            await client.close()
