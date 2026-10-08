"""Agent that turns a follow-up into one question a search can run on its own.

Used for the Knowledge search only; the orchestrator still reads the user's own words.
"""

from mycel.agents.core.base import BaseAgent
from mycel.agents.prompts import load


class Rewriter(BaseAgent[str]):
    """Resolves what a follow-up points at. No tools, plain text out."""

    name = "rewriter"
    instructions = load("rewriter")
    output_type = str
