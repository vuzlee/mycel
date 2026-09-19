"""What every agent is, so that each one only writes what makes it different.

An agent in Mycel is four declarations — a name, an output schema, instructions, and the
toolsets it may call — plus the wiring that turns them into a pydantic-ai `Agent`. The
wiring is identical for every agent and easy to get subtly wrong: forget `deps_type` and
tools lose the budget, forget `retries` and a configured value is silently ignored.
`BaseAgent` owns it once; a subclass is the four declarations and nothing else.

**The name lives in exactly one place.** It is the registry key, the value pydantic-ai
tags spans with, and the stem of `config/agents/<name>.yaml`. Spelling it three times is
how an agent ends up reading another one's configuration, so subclasses declare it once
and everything else reads it off the class.

**No model is built here.** `runner.run` resolves the spec and passes the model per run,
so constructing an agent needs no credentials: the registry can be imported, listed and
unit-tested on a machine with no API key, and a missing key fails when a run is actually
attempted rather than at import time.

**Classes, not instances, in the registry.** A module-level agent is a shared mutable
object — whichever test or task overrides its model last wins, across everything else in
the process. `build()` is a classmethod returning a fresh agent each call.
"""

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from pydantic_ai import Agent

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.mcp.clients import build_toolsets

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.toolsets import AbstractToolset

OutputT = TypeVar("OutputT")


class BaseAgent(ABC, Generic[OutputT]):
    """One specialist. Subclasses declare what they are; this class builds them.

    Never instantiated — everything is a classmethod, because an agent definition is a
    description rather than an object with state of its own. `ABC` alone does not enforce
    that here: with no abstract method to leave unimplemented, Python would happily hand
    out a useless empty instance.
    """

    def __init__(self) -> None:
        raise TypeError(f"{type(self).__name__} is a declaration, not an object; call build()")

    #: Registry key, span name, and the stem of `config/agents/<name>.yaml`.
    name: ClassVar[str]

    #: The system prompt. Kept as a class attribute so a prompt diff is a one-file diff.
    instructions: ClassVar[str]

    #: The schema the model must fill. A wrong shape is retried, not passed downstream.
    output_type: type[OutputT]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Refuse a half-declared agent at import time.

        The alternative is an `AttributeError` from inside `build()`, raised in a worker
        halfway through a job rather than when the module is first loaded.
        """
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
        """The toolsets written in this agent's own code.

        Empty for an agent that only reasons over its prompt. MCP servers are *not*
        declared here — they come from `settings.mcp_servers`, so that which outside
        server an agent may call is a line in `config/` rather than a line in a module.
        """
        return []

    @classmethod
    def validate_output(cls, ctx: "RunContext[MycelDeps]", output: OutputT) -> OutputT:
        """Last check before the output leaves the agent.

        Raise `ModelRetry` to send the model back with a reason; the default accepts
        whatever matched the schema. This is where a rule that the schema cannot express —
        "every figure carries a source" — is enforced rather than merely requested.
        """
        return output

    @classmethod
    def settings(cls, settings: AgentSettings | None = None) -> AgentSettings:
        """This agent's configuration, unless the caller supplied its own."""
        return settings or AgentSettings.from_config(cls.name)

    @classmethod
    def build(cls, settings: AgentSettings | None = None) -> Agent[MycelDeps, OutputT]:
        """A fresh agent, wired the same way as every other one."""
        cfg = cls.settings(settings)
        agent: Agent[MycelDeps, OutputT] = Agent(
            deps_type=MycelDeps,
            output_type=cls.output_type,
            instructions=cls.instructions,
            retries=cfg.tool_retries,
            name=cls.name,
            toolsets=[*cls.toolsets(), *build_toolsets(list(cfg.mcp_servers))],
        )
        agent.output_validator(cls.validate_output)
        return agent
