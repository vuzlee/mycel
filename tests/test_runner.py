"""`runner.run` and `runner.delegate`, which between them decide what a job is charged.

The tests that matter here are about arithmetic, not about models: that a run is charged
once, that a run stopped part-way is still charged, and that delegation does not bill the
same tokens twice.
"""

from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import RunawayStopped
from mycel.llm.budget import BudgetExceeded, JobBudget

pytestmark = pytest.mark.anyio

LOCAL = AgentSettings(model_spec="local:qwen3-4b")


def _deps(ceiling: str = "1.00", settings: AgentSettings = LOCAL) -> MycelDeps:
    return MycelDeps(job_id="job-1", budget=JobBudget("job-1", Decimal(ceiling)), settings=settings)


def _says(text: str, *, tokens: int = 10) -> Any:
    """A model that answers immediately, reporting a fixed token cost."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(text)],
            usage=RequestUsage(input_tokens=tokens, output_tokens=tokens),
        )

    return FunctionModel(respond)


class TestCharging:
    async def test_a_completed_run_is_charged_once(self) -> None:
        deps = _deps()
        agent = Agent(deps_type=MycelDeps, output_type=str)
        with agent.override(model=_says("done", tokens=10)):
            out = await runner.run(agent, "go", deps)

        assert out == "done"
        assert deps.budget.tokens == 20
        assert deps.budget.requests == 1

    async def test_a_second_run_accumulates(self) -> None:
        """The budget spans a job, not a run — two runs on one job add up."""
        deps = _deps()
        agent = Agent(deps_type=MycelDeps, output_type=str)
        with agent.override(model=_says("done", tokens=10)):
            await runner.run(agent, "go", deps)
            await runner.run(agent, "again", deps)

        assert deps.budget.tokens == 40
        assert deps.budget.requests == 2

    async def test_an_exhausted_budget_refuses_before_spending(self) -> None:
        """`check()` runs before the model is built, so no request is made at all."""
        deps = _deps("0.00")
        calls: list[int] = []

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            return ModelResponse(parts=[TextPart("done")])

        agent = Agent(deps_type=MycelDeps, output_type=str)
        with pytest.raises(BudgetExceeded):
            with agent.override(model=FunctionModel(respond)):
                await runner.run(agent, "go", deps)

        assert not calls, "no model call may be made once the budget is gone"


class TestStoppedRunsAreStillCharged:
    async def test_a_runaway_run_records_what_it_spent(self) -> None:
        """The reason runner.run uses iter() rather than run(): tokens spent before the
        limit tripped are real money, and must not vanish."""
        settings = AgentSettings(model_spec="local:qwen3-4b", request_limit=3)
        deps = _deps(settings=settings)

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[ToolCallPart("noop", {})],
                usage=RequestUsage(input_tokens=5, output_tokens=5),
            )

        agent = Agent(deps_type=MycelDeps, output_type=str)

        @agent.tool_plain
        def noop() -> str:
            """Do nothing, so the model can loop."""
            return "ok"

        with pytest.raises(RunawayStopped):
            with agent.override(model=FunctionModel(respond)):
                await runner.run(agent, "go", deps)

        assert deps.budget.requests == 3
        assert deps.budget.tokens == 30


class TestDelegation:
    async def test_a_child_does_not_double_charge(self) -> None:
        """The child's tokens reach the budget exactly once, via the parent's record()."""
        deps = _deps()
        child = Agent(deps_type=MycelDeps, output_type=str)
        parent = Agent(deps_type=MycelDeps, output_type=str)

        child_model = _says("child answer", tokens=7)

        @parent.tool
        async def ask_child(ctx: RunContext[MycelDeps]) -> str:
            """Delegate to the child agent."""
            with child.override(model=child_model):
                return await runner.delegate(child, "sub-question", ctx)

        step = [0]

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            step[0] += 1
            usage = RequestUsage(input_tokens=10, output_tokens=10)
            if step[0] == 1:
                return ModelResponse(parts=[ToolCallPart("ask_child", {})], usage=usage)
            return ModelResponse(parts=[TextPart("final")], usage=usage)

        with parent.override(model=FunctionModel(respond)):
            out = await runner.run(parent, "go", deps)

        assert out == "final"
        # parent: 2 requests x 20 tokens; child: 1 request x 14 tokens.
        assert deps.budget.tokens == 54
        assert deps.budget.requests == 3

    async def test_a_delegated_run_is_limited_by_its_own_config(self) -> None:
        """MYC-48. A delegated run given no `usage_limits` fell to pydantic-ai's defaults —
        50 requests and no tool-call limit at all — so every number in `config/agents/`
        bound the orchestrator and nothing it called. One question cost 41 `run_sql` calls
        before the default request limit stopped it."""
        deps = _deps(settings=AgentSettings(model_spec="local:qwen3-4b", tool_calls_limit=3))
        child = Agent(deps_type=MycelDeps, output_type=str)
        parent = Agent(deps_type=MycelDeps, output_type=str)
        queries: list[str] = []

        @child.tool
        async def run_sql(ctx: RunContext[MycelDeps], query: str) -> str:
            """Read something, so the child can loop."""
            queries.append(query)
            return "rows"

        @parent.tool
        async def analyst(ctx: RunContext[MycelDeps]) -> str:
            """Delegate to the child agent."""
            return await runner.delegate(child, "q", ctx)

        # Different arguments every call, so `guards.py` never fires: the limit is the
        # only thing that can stop this, which is the whole point of the test.
        asked = [0]

        def child_says(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            asked[0] += 1
            return ModelResponse(parts=[ToolCallPart("run_sql", {"query": f"select {asked[0]}"})])

        step = [0]

        def parent_says(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            step[0] += 1
            if step[0] == 1:
                return ModelResponse(parts=[ToolCallPart("analyst", {})])
            return ModelResponse(parts=[TextPart("final")])

        with parent.override(model=FunctionModel(parent_says)):
            with child.override(model=FunctionModel(child_says)):
                with pytest.raises(RunawayStopped):
                    await runner.run(parent, "go", deps)

        assert len(queries) == 3, f"the child's own tool_calls_limit must bind, got {len(queries)}"

    async def test_a_delegate_limit_is_not_spent_by_its_caller(self) -> None:
        """The counters are the caller's, so a limit read against them raw would already be
        part-spent before the delegated run starts — and a specialist called late in a long
        orchestration would get fewer calls than its own file grants it."""
        CHILD = AgentSettings(model_spec="local:qwen3-4b", tool_calls_limit=2)
        deps = _deps(settings=AgentSettings(model_spec="local:qwen3-4b", tool_calls_limit=20))
        child = Agent(deps_type=MycelDeps, output_type=str)
        parent = Agent(deps_type=MycelDeps, output_type=str)
        reads: list[str] = []

        @child.tool
        async def read(ctx: RunContext[MycelDeps], n: int) -> str:
            """Read something, so the child can use its allowance."""
            reads.append(str(n))
            return "rows"

        @parent.tool
        async def noop(ctx: RunContext[MycelDeps]) -> str:
            """Spend one of the parent's tool calls before the child is reached."""
            return "ok"

        @parent.tool
        async def specialist(ctx: RunContext[MycelDeps]) -> str:
            """Delegate, on the child's own settings rather than the caller's."""
            assert ctx.usage.tool_calls >= 1, "the parent must have spent one before delegating"
            return await runner.delegate(child, "q", ctx, CHILD)

        asked = [0]

        def child_says(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            asked[0] += 1
            if asked[0] > 2:
                return ModelResponse(parts=[TextPart("child answer")])
            return ModelResponse(parts=[ToolCallPart("read", {"n": asked[0]})])

        step = [0]

        def parent_says(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            step[0] += 1
            if step[0] == 1:
                return ModelResponse(parts=[ToolCallPart("noop", {})])
            if step[0] == 2:
                return ModelResponse(parts=[ToolCallPart("specialist", {})])
            return ModelResponse(parts=[TextPart("final")])

        with parent.override(model=FunctionModel(parent_says)):
            with child.override(model=FunctionModel(child_says)):
                assert await runner.run(parent, "go", deps) == "final"

        assert reads == ["1", "2"], f"the child gets its own two calls, got {reads}"

    async def test_child_tokens_count_against_the_same_ceiling(self) -> None:
        """A child spending the job's money is the point of sharing the budget object."""
        deps = _deps()
        child = Agent(deps_type=MycelDeps, output_type=str)
        parent = Agent(deps_type=MycelDeps, output_type=str)

        @parent.tool
        async def ask_child(ctx: RunContext[MycelDeps]) -> str:
            """Delegate to the child agent."""
            with child.override(model=_says("child answer", tokens=100)):
                return await runner.delegate(child, "sub-question", ctx)

        step = [0]

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            step[0] += 1
            if step[0] == 1:
                return ModelResponse(parts=[ToolCallPart("ask_child", {})])
            return ModelResponse(parts=[TextPart("final")])

        with parent.override(model=FunctionModel(respond)):
            await runner.run(parent, "go", deps)

        assert deps.budget.tokens >= 200, "the child's tokens must reach the job budget"


def _priced(text: str, *, cost: str, tokens: int = 10) -> Any:
    """A model that answers immediately at a known price."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(text)],
            usage=RequestUsage(input_tokens=tokens, output_tokens=tokens, cost=Decimal(cost)),
        )

    return FunctionModel(respond)


class TestCostAccounting:
    """The token counts above are incidental; money is what the ceiling is made of."""

    async def test_a_priced_run_is_charged_in_dollars(self) -> None:
        deps = _deps(ceiling="1.00")
        agent = Agent(deps_type=MycelDeps, output_type=str)
        with agent.override(model=_priced("done", cost="0.25")):
            await runner.run(agent, "go", deps)

        assert deps.budget.spent_usd == Decimal("0.25")
        assert deps.budget.remaining_usd() == Decimal("0.75")

    async def test_a_job_with_no_headroom_never_calls_the_model(self) -> None:
        deps = _deps(ceiling="0.10")
        agent = Agent(deps_type=MycelDeps, output_type=str)
        with agent.override(model=_priced("done", cost="0.10")):
            with pytest.raises(BudgetExceeded):
                await runner.run(agent, "go", deps)

            with pytest.raises(BudgetExceeded):
                await runner.run(agent, "again", deps)

        assert deps.budget.requests == 1, "the second run must not reach the model"


class TestBookkeepingNeverMasks:
    """The budget is recorded in a `finally`. An exception from there would replace
    whatever actually stopped the run, leaving the caller with a bookkeeping error in
    place of the diagnosis."""

    async def test_a_runaway_survives_a_failing_charge(self) -> None:
        """The caller must hear about the runaway, because that is the one a human can
        act on. `cost_limit` normally stops a run before it can overdraw, so the
        overdraft is forced here rather than waited for."""

        class Overdrawing(JobBudget):
            def record(self, usage: Any, fallback_cost: Decimal | None = None) -> None:
                super().record(usage, fallback_cost)
                raise BudgetExceeded(self.job_id, Decimal("9.99"), self.ceiling_usd)

        deps = MycelDeps(
            job_id="job-1",
            budget=Overdrawing("job-1", Decimal("1.00")),
            settings=AgentSettings(model_spec="local:x", request_limit=2),
        )
        agent = Agent(deps_type=MycelDeps, output_type=str)

        @agent.tool_plain
        def noop() -> str:
            return "x"

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[ToolCallPart("noop", {})],
                usage=RequestUsage(input_tokens=5, output_tokens=5),
            )

        with pytest.raises(RunawayStopped):
            with agent.override(model=FunctionModel(respond)):
                await runner.run(agent, "go", deps)

        assert deps.budget.requests == 2, "the spend still has to be recorded"
