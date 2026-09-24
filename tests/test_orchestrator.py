"""The orchestrator, run against fake models.

Two things are worth pinning down here, and neither is about the orchestrator's own
reasoning — that is the model's job, not the code's.

The first is **money**: a delegated run must be billed once, by the caller. `runner.delegate`
forwards `usage=ctx.usage` and deliberately skips `budget.record()`, so a regression there
double-charges silently and only shows up on an invoice.

The second is **what a failing specialist does to a run**. It must come back as text the
model can write around, not as an exception that kills the run — except for
`BudgetExceeded`, which is the one failure that must end the job.

Since batch 033 the output is a plain `str`, so a model's turn ends with a `TextPart`
rather than a `final_result` tool call. That is the point of the change and not an
incidental one: prose arrives on the stream as it is written, and a tool call does not.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from mycel.agents.agent.orchestrator import Orchestrator
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ModelTimeout
from mycel.agents.tools import delegate
from mycel.agents.tools.delegate import build_toolset
from mycel.llm.budget import BudgetExceeded, JobBudget

pytestmark = pytest.mark.anyio

LOCAL = AgentSettings(model_spec="local:qwen3-4b")


@asynccontextmanager
async def _null_session() -> AsyncIterator[None]:
    """A stand-in for `session_scope`: the summariser tool opens its own, and what it
    does with the session is `gather_progress`'s business, faked separately."""
    yield None


#: The specialists are delegated to on every step, which is the pattern guards.py stops.
#: These tests drive the delegation deliberately, so the guard is out of the way.
UNGUARDED = AgentSettings(model_spec="local:qwen3-4b", repeat_threshold=1_000_000)


@pytest.fixture
def deps() -> MycelDeps:
    return MycelDeps(job_id="job-1", budget=JobBudget("job-1", Decimal("1.00")), settings=UNGUARDED)


def _answer(text: str = "Done.") -> ModelResponse:
    """A model response that ends the run. Free text, which is the whole output now."""
    return ModelResponse(parts=[TextPart(text)])


def _asks_then_answers(tool: str, question: str) -> Any:
    """A model that calls one specialist, then writes up whatever came back."""
    step = [0]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step[0] += 1
        if step[0] == 1:
            return ModelResponse(parts=[ToolCallPart(tool, {"question": question})])
        return _answer()

    return respond


class TestWiring:
    async def test_every_delegated_agent_is_registered(self) -> None:
        """An agent missing from the toolset is a capability the orchestrator silently
        does not have.

        The names are the agents' own, not `ask_*`: one string reaches the tool, the class
        and its `config/agents/<name>.yaml`, and none of them implies a rank.
        """
        toolset = build_toolset()
        assert set(toolset.tools) == {"researcher", "analyst", "summariser"}

    async def test_a_delegated_answer_reaches_the_model_as_text(
        self, deps: MycelDeps, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The specialist's schema has to survive the tool-result boundary as JSON: that is
        what keeps a statement attached to its sources."""
        seen: list[str] = []

        class _Output:
            @staticmethod
            def model_dump_json() -> str:
                return '{"claims": [{"statement": "x", "sources": ["https://example.com/a"]}]}'

        async def _fake_delegate(agent: Any, prompt: str, ctx: Any, cfg: Any) -> Any:
            seen.append(prompt)
            return _Output()

        monkeypatch.setattr(runner, "delegate", _fake_delegate)

        agent = Orchestrator.build(LOCAL)
        with agent.override(model=FunctionModel(_asks_then_answers("researcher", "who?"))):
            result = await agent.run("Find out who.", deps=deps)

        assert seen == ["who?"], "the tool must forward the question unchanged"
        assert isinstance(result.output, str)


class TestMoney:
    async def test_a_delegated_run_is_billed_once(
        self, deps: MycelDeps, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`delegate` must not call `budget.record()`: the caller's own record already
        includes the delegated tokens, so a second one bills them twice."""
        recorded: list[Any] = []
        original = deps.budget.record

        def _record(usage: Any) -> Any:
            recorded.append(usage)
            return original(usage)

        monkeypatch.setattr(deps.budget, "record", _record)

        class _Output:
            @staticmethod
            def model_dump_json() -> str:
                return "{}"

        async def _fake_delegate(agent: Any, prompt: str, ctx: Any, cfg: Any) -> Any:
            return _Output()

        monkeypatch.setattr(runner, "delegate", _fake_delegate)

        agent = Orchestrator.build(LOCAL)
        with agent.override(model=FunctionModel(_asks_then_answers("analyst", "1 to 2?"))):
            await runner.run(agent, "Compute.", deps, LOCAL)

        assert len(recorded) == 1, "one run, one charge — the delegate must not record too"


class TestAFailingSpecialist:
    async def test_becomes_text_the_model_can_read(
        self, deps: MycelDeps, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One unavailable source must not cost the whole run."""

        async def _fails(agent: Any, prompt: str, ctx: Any, cfg: Any) -> Any:
            raise ModelTimeout("researcher timed out")

        monkeypatch.setattr(runner, "delegate", _fails)

        returned: list[str] = []
        step = [0]

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            step[0] += 1
            if step[0] == 1:
                return ModelResponse(parts=[ToolCallPart("researcher", {"question": "q"})])
            for message in messages:
                for part in getattr(message, "parts", []):
                    content = getattr(part, "content", None)
                    if isinstance(content, str) and "could not answer" in content:
                        returned.append(content)
            return _answer("The researcher was unavailable, so this is unanswered.")

        agent = Orchestrator.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            result = await agent.run("Find out who.", deps=deps)

        assert returned, "the failure must arrive as a tool result, not as an exception"
        assert "researcher" in returned[0]
        assert "unavailable" in result.output, "the model must be free to say so in the answer"

    async def test_running_out_of_money_still_ends_the_job(
        self, deps: MycelDeps, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`BudgetExceeded` is not an `AgentError` and must pass through: continuing would
        spend money the job does not have."""

        async def _overdrawn(agent: Any, prompt: str, ctx: Any, cfg: Any) -> Any:
            raise BudgetExceeded("job-1", Decimal("1.01"), Decimal("1.00"))

        monkeypatch.setattr(runner, "delegate", _overdrawn)

        agent = Orchestrator.build(LOCAL)
        with agent.override(model=FunctionModel(_asks_then_answers("researcher", "q"))):
            with pytest.raises(BudgetExceeded):
                await agent.run("Find out who.", deps=deps)


class TestTheSummariserTool:
    """The one delegated tool that does not forward a question.

    It takes `project` and `days` and builds the prompt itself, because the summariser's
    prompt is what batches 017 and 024 tuned. Letting the orchestrator write that prompt
    would throw both away and re-open the faults they closed.
    """

    async def test_it_builds_the_prompt_from_the_window_it_was_given(
        self, deps: MycelDeps, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        windows: list[tuple[str, int]] = []

        async def _fake_gather(session: Any, project: str, since: Any, until: Any) -> Any:
            windows.append((project, round((until - since).total_seconds() / 86400)))
            return object()

        monkeypatch.setattr(delegate, "gather_progress", _fake_gather)
        monkeypatch.setattr(delegate, "render", lambda window: "rendered progress")
        monkeypatch.setattr(delegate, "session_scope", _null_session)

        prompts: list[str] = []

        class _Output:
            @staticmethod
            def model_dump_json() -> str:
                return "{}"

        async def _fake_delegate(agent: Any, prompt: str, ctx: Any, cfg: Any) -> Any:
            prompts.append(prompt)
            return _Output()

        monkeypatch.setattr(runner, "delegate", _fake_delegate)

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(
                    parts=[ToolCallPart("summariser", {"project": "MYC", "days": 14})]
                )
            return _answer()

        agent = Orchestrator.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            await agent.run("How is MYC going?", deps=deps)

        assert windows == [("MYC", 14)], "the window must be the one the model asked for"
        assert prompts == ["rendered progress"], "the summariser gets the rendered window"
