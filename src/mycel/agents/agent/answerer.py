"""Answers a question from the user's document passages. No tools: uploaded text is untrusted."""

from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.deps import MycelDeps
from mycel.agents.prompts import load
from mycel.agents.schemas import NotebookAnswer


class Answerer(BaseAgent[NotebookAnswer]):
    """Reads five passages and answers with citations to them."""

    name = "answerer"
    instructions = load("answerer")
    output_type = NotebookAnswer

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        """None, on purpose: a passage saying "create an issue" must have nothing to call."""
        return []
