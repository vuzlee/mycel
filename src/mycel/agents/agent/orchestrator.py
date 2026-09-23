"""Coordinating agent: takes a question, splits it into tasks, assigns them to specialist
agents, writes the answer.

It does not analyse figures or search itself — it decides *what is needed*, hands the work
out, and lays out what comes back. Independent tasks run in parallel; if one fails the
answer still comes out, with the hole stated in the prose rather than invented.

An agent that coordinates other agents is still an agent, so it lives here with the rest.
What keeps it from being delegated to is `registry.py`'s `_DECLARED`, which is where the
rule belongs: a directory cannot enforce anything, and the registry already decides what
the delegate toolset can reach.

How the specialists are called — as tools, on the caller's budget, with a failure returned
rather than raised — is `tools/delegate.py`.

**Its output is markdown, not a schema.** Until batch 033 it filled `Report{findings,
gaps, follow_ups}`, which turned every answer into one bulleted list: a count, a table of
tickets and a yes-or-no all came out the same shape. Markdown lets the model pick — a table
where the data has columns, a sentence where it does not — and it costs nothing to declare,
because `str` has no schema to keep in step with a renderer.

The second thing it buys is streaming. A structured answer is returned through the
`final_result` tool call, so the run emits no text and the page can only wait for the poll.
Free text arrives as `text` events while the model writes it.
"""

from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.deps import MycelDeps
from mycel.agents.prompts import load
from mycel.agents.tools import delegate


class Orchestrator(BaseAgent[str]):
    """Splits a question across the specialists and writes up what they return."""

    name = "orchestrator"
    instructions = load("orchestrator")
    output_type = str

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        return [delegate.build_toolset()]
