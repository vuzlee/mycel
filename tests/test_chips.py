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


class TestKnowledgeGoesThroughTheOrchestrator:
    """A Knowledge turn is a chat job like any other, carrying the previous question."""

    async def test_a_knowledge_turn_is_queued_as_chat(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from contextlib import asynccontextmanager
        from types import SimpleNamespace

        from mycel.domains import chat

        queued: list[tuple[object, object]] = []

        async def plain(*args: object, **kwargs: object) -> str:
            queued.append((kwargs.get("chips"), kwargs.get("previous")))
            return "job-c"

        class Repo:
            def __init__(self, session: object) -> None: ...

            async def create_conversation(self, *a: object, **k: object) -> object:
                return SimpleNamespace(id=1)

            async def turns_for_conversation(self, thread_id: int) -> list[object]:
                return []

            async def upsert_turn(self, *a: object, **k: object) -> None: ...

        @asynccontextmanager
        async def scope():  # type: ignore[no-untyped-def]
            yield None

        monkeypatch.setattr(chat, "AppRepository", Repo)
        monkeypatch.setattr(chat, "session_scope", scope)
        monkeypatch.setattr(chat, "enqueue_chat", plain)

        await chat.request_chat(7, "What is BERT?", chips=["knowledge"])
        await chat.request_chat(7, "Late tickets?", chips=["jira"])

        assert queued == [(["knowledge"], ""), (["jira"], "")]


async def instructions_seen(chips: frozenset[Chip] | None) -> str:
    """The orchestrator's instructions for one turn."""
    seen: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info.instructions or "")
        return ModelResponse(parts=[TextPart("ok")])

    agent = Orchestrator.build(AgentSettings(model_spec="cloud:x"))
    deps = MycelDeps("j", JobBudget("j", Decimal("1")), chips=chips)
    with agent.override(model=FunctionModel(respond)):
        await agent.run("hi", deps=deps)
    return seen[0]


class TestASourceThatIsOff:
    """Off means the model says so in a sentence, not a heading over nothing."""

    async def test_the_orchestrator_is_told_which_sources_are_off(self) -> None:
        text = await instructions_seen(frozenset({Chip.WEB}))
        assert "Switched off for this turn: your team's Jira, your mail, your calendar." in text
        assert "Settings → Accounts" in text

    async def test_nothing_is_added_when_every_source_is_on(self) -> None:
        on = frozenset({Chip.JIRA, Chip.MAIL, Chip.CALENDAR, Chip.WEB})
        assert "Switched off" not in await instructions_seen(on)

    async def test_nothing_is_added_when_nobody_chose(self) -> None:
        assert "Switched off" not in await instructions_seen(None)
