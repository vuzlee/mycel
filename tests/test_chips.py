"""No chip, no tool: what the model is shown is decided in code, per turn."""

from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from mycel.agents.agent.analyst import Analyst
from mycel.agents.agent.orchestrator import Orchestrator
from mycel.agents.agent.researcher import Researcher
from mycel.agents.core.chips import Chip, parse, tools_for
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.llm.budget import JobBudget

pytestmark = pytest.mark.anyio


async def offered(agent_cls: type, chips: frozenset[Chip] | None) -> set[str]:
    """The tool names the model would see for one turn."""
    seen: list[set[str]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append({t.name for t in info.function_tools})
        return ModelResponse(parts=[TextPart("ok")])

    agent = agent_cls.build(AgentSettings(model_spec="cloud:x"))
    deps = MycelDeps("j", JobBudget("j", Decimal("1")), chips=chips)
    with agent.override(model=FunctionModel(respond)):
        try:
            await agent.run("hi", deps=deps)
        except Exception:  # a structured agent rejects "ok"; the tools were already shown
            pass
    return seen[0]


class TestWhatTheModelIsShown:
    async def test_no_chip_means_no_tool(self) -> None:
        assert await offered(Orchestrator, frozenset()) == set()

    async def test_no_decision_keeps_every_tool(self) -> None:
        """Scripts, tests and scheduled work pick no chips and must keep working."""
        assert {"researcher", "analyst"} <= await offered(Orchestrator, None)

    async def test_the_jira_chip_opens_the_analyst_not_the_researcher(self) -> None:
        tools = await offered(Orchestrator, frozenset({Chip.JIRA}))
        assert "analyst" in tools
        assert "researcher" not in tools

    async def test_a_chip_reaches_into_the_specialist(self) -> None:
        """The web chip opens the researcher, and inside it only web search."""
        tools = await offered(Researcher, frozenset({Chip.WEB}))
        assert "web_search" in tools
        assert "read_mail" not in tools

    async def test_the_analyst_sees_nothing_with_only_the_web_chip(self) -> None:
        assert await offered(Analyst, frozenset({Chip.WEB})) == set()


class TestParsing:
    def test_unknown_names_are_dropped(self) -> None:
        assert parse(["jira", "root", "web"]) == frozenset({Chip.JIRA, Chip.WEB})

    def test_absent_means_undecided(self) -> None:
        assert parse(None) is None

    def test_knowledge_opens_no_orchestrator_tool(self) -> None:
        assert tools_for(frozenset({Chip.KNOWLEDGE})) == frozenset()
