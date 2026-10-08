"""Tool-less agent that summarizes one chat's progress updates."""

from mycel.agents.core.base import BaseAgent
from mycel.agents.prompts import load
from mycel.agents.schemas import ProgressSummary


class Summariser(BaseAgent[ProgressSummary]):
    """Reads a window of progress updates and says what happened in it."""

    name = "summariser"
    instructions = load("summariser")
    output_type = ProgressSummary
