"""Agent that turns one chat's progress updates into a summary a person can read.

The opposite shape to the orchestrator, and that is why it is a separate agent rather than
a second prompt for one. The orchestrator is built to *not* have data — its instructions
say to call a specialist rather than answer from memory, and its tools search the web.
Handing it a pre-loaded table and asking it not to delegate means fighting its own prompt.

This one has no tools at all. Everything it knows arrives in the prompt, assembled by
`services/gather.py`, so the only failure mode left is the model mis-summarising what it
was given — not inventing what it was not.

Turning a `ProgressWindow` into the text of that prompt is `services/analyze.py`'s job,
not this module's: an agent that imported a service would reverse the direction every
other agent points in, and the shape of the data is the caller's concern anyway.
"""

from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.deps import MycelDeps
from mycel.agents.prompts import load
from mycel.agents.schemas import ProgressSummary


class Summariser(BaseAgent[ProgressSummary]):
    """Reads a window of progress updates and says what happened in it."""

    name = "summariser"
    instructions = load("summariser")
    output_type = ProgressSummary

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        """None. The data is in the prompt — see the module docstring."""
        return []
