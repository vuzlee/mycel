"""The envelope every streamed event travels in."""

from typing import Any

from pydantic import BaseModel, Field

#: The event types, here rather than in `agents/core/emit.py` because both the emitter and
#: the channels that filter events need them, and a channel must not import the emitter.
#: Kept small on purpose: a client ignores types it does not know, so adding one later is
#: safe; removing one is not.
RUN_STARTED = "run_started"
RUN_FINISHED = "run_finished"
TEXT = "text"
#: A piece of `TEXT`, emitted while the model is still writing. A client appends deltas to
#: the same bubble; a run whose model cannot stream sends `TEXT` alone, and both read the
#: same way.
TEXT_DELTA = "text_delta"
THINKING = "thinking"
TOOL_CALLED = "tool_called"
TOOL_RETURNED = "tool_returned"


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
