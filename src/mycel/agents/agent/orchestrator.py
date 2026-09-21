"""Coordinating agent: takes a report request, splits it into tasks, assigns them to
specialist agents, merges the results.

It does not analyse figures or write prose itself — it decides *what is needed* and hands
the work out. Independent tasks run in parallel; if one fails the report still comes out,
with the gap stated explicitly rather than invented.

An agent that coordinates other agents is still an agent, so it lives here with the rest.
What keeps it from being delegated to is `registry.py`'s `_DECLARED`, which is where the
rule belongs: a directory cannot enforce anything, and the registry already decides what
`ask_*` can reach.

How the specialists are called — as tools, on the caller's budget, with a failure returned
rather than raised — is `tools/delegate.py`. The output schema is `agents/schemas.py`,
because the API layer names it too.
"""

from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.deps import MycelDeps
from mycel.agents.prompts import load
from mycel.agents.schemas import Report
from mycel.agents.tools import delegate


class Orchestrator(BaseAgent[Report]):
    """Splits a request across the specialists and merges what they return."""

    name = "orchestrator"
    instructions = load("orchestrator")
    output_type = Report

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        return [delegate.build_toolset()]
