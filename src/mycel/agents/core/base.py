"""`BaseAgent`: what an agent declares, and the shared wiring into a pydantic-ai `Agent`.

No model is built here; `runner.run` passes it per run, so building needs no credentials.
"""

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from pydantic_ai import Agent

from mycel.agents.core.chips import allowed
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.mcp.clients import build_toolsets

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.toolsets import AbstractToolset

OutputT = TypeVar("OutputT")


class BaseAgent(ABC, Generic[OutputT]):
    """An agent declaration; never instantiated, every method is a classmethod."""

    def __init__(self) -> None:
        raise TypeError(f"{type(self).__name__} is a declaration, not an object; call build()")

    #: Registry key, span name, and the stem of `config/agents/<name>.yaml`.
    name: ClassVar[str]

    #: The system prompt.
    instructions: ClassVar[str]

    #: The schema the model must fill; a wrong shape is retried.
    output_type: type[OutputT]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Refuse a half-declared agent at import time."""
        super().__init_subclass__(**kwargs)
        if ABC in cls.__bases__:  # an intermediate base, not a concrete agent
            return
        missing = [
            field
            for field in ("name", "instructions", "output_type")
            if getattr(cls, field, None) is None
        ]
        if missing:
            raise TypeError(f"{cls.__name__} does not declare: {', '.join(missing)}")

    @classmethod
    def toolsets(cls) -> "list[AbstractToolset[MycelDeps]]":
        """In-code toolsets; MCP servers come from `settings.mcp_servers` instead."""
        return []

    @classmethod
    def validate_output(cls, ctx: "RunContext[MycelDeps]", output: OutputT) -> OutputT:
        """Final output check; raise `ModelRetry` to send the model back with a reason."""
        return output

    @classmethod
    def settings(cls, settings: AgentSettings | None = None) -> AgentSettings:
        return settings or AgentSettings.from_config(cls.name)

    @classmethod
    def build(cls, settings: AgentSettings | None = None) -> Agent[MycelDeps, OutputT]:
        cfg = cls.settings(settings)
        agent: Agent[MycelDeps, OutputT] = Agent(
            deps_type=MycelDeps,
            output_type=cls.output_type,
            instructions=cls.instructions,
            retries=cfg.tool_retries,
            name=cls.name,
            # A tool outside the turn's chips is never sent to the model.
            toolsets=[
                ts.filtered(allowed)
                for ts in [*cls.toolsets(), *build_toolsets(list(cfg.mcp_servers))]
            ],
        )
        agent.output_validator(cls.validate_output)
        return agent
