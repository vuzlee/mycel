"""The envelope every streamed event travels in."""

from typing import Any

from pydantic import BaseModel, Field

#: Event types; clients ignore unknown ones, so adding is safe and removing is not.
RUN_STARTED = "run_started"
RUN_FINISHED = "run_finished"
TEXT = "text"
#: A piece of `TEXT` streamed while the model writes; clients append deltas.
TEXT_DELTA = "text_delta"
THINKING = "thinking"
TOOL_CALLED = "tool_called"
TOOL_RETURNED = "tool_returned"


class AgentEvent(BaseModel):
    """One thing that happened during a run; `parent_tool_call_id` nests sub-agents."""

    agent: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_tool_call_id: str | None = None


class SequencedEvent(AgentEvent):
    """An event with its place in the job's sequence; a gap means one was lost."""

    seq: int
