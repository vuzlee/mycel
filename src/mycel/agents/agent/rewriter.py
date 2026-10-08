"""Agent that rewrites a follow-up into a standalone search question."""

from mycel.agents.core.base import BaseAgent
from mycel.agents.prompts import load


class Rewriter(BaseAgent[str]):
    name = "rewriter"
    instructions = load("rewriter")
    output_type = str
