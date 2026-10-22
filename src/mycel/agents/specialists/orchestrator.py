"""Coordinating agent: delegates to specialists and writes a markdown answer."""

from pydantic_ai import Agent, RunContext
from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.chip_filter import missing_sources_note
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.settings import AgentSettings
from mycel.agents.prompts import load
from mycel.agents.tools import delegate


class Orchestrator(BaseAgent[str]):
    name = "orchestrator"
    instructions = load("orchestrator")
    output_type = str

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        return [delegate.build_toolset()]

    @classmethod
    def build(cls, settings: AgentSettings | None = None) -> Agent[MycelDeps, str]:
        agent = super().build(settings)

        @agent.instructions
        def sources(ctx: RunContext[MycelDeps]) -> str:
            return missing_sources_note(ctx.deps.chips)

        return agent
