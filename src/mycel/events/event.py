"""The envelope every streamed event travels in."""

from typing import Any

from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    """One thing that happened during a run.

    `parent_tool_call_id` is set when the agent was called from another agent's tool, which
    is what lets a client nest the two rather than interleave them.
    """

    agent: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_tool_call_id: str | None = None


class SequencedEvent(AgentEvent):
    """An event with its place in the job's sequence.

    Gaps are meaningful: a client that jumps from 7 to 9 lost one, and knows it.
    """

    seq: int
