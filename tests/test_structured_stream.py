"""A structured answer streams its text field, so a Knowledge answer appears as it is written."""

import json
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from mycel.agents.agent.answerer import Answerer
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.emit import _partial_field
from mycel.events.event import AgentEvent
from mycel.llm.budget import JobBudget

pytestmark = pytest.mark.anyio

BODY = {
    "answer": "BERT masks 15% of tokens [c1].",
    "citations": [{"id": "c1", "quote": "masks 15%"}],
    "answered": True,
}


class Collect:
    def __init__(self) -> None:
        self.deltas: list[str] = []

    async def publish(self, event: AgentEvent) -> None:
        if event.type == "text_delta":
            self.deltas.append(str(event.payload["text"]))


def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, BODY)])


async def _stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[dict[int, DeltaToolCall]]:
    text = json.dumps(BODY)
    for i in range(0, len(text), 9):
        name = info.output_tools[0].name if i == 0 else None
        yield {0: DeltaToolCall(name=name, json_args=text[i : i + 9])}


async def _run(field: str | None) -> Collect:
    cfg = AgentSettings(model_spec="cloud:x")
    agent = Answerer.build(cfg)
    channel = Collect()
    deps = MycelDeps("j", JobBudget("j", Decimal("1")), settings=cfg, events=channel)
    with agent.override(model=FunctionModel(_respond, stream_function=_stream)):
        await runner.run(agent, "q", deps, cfg, streamed_field=field)
    return channel


class TestStreamingAField:
    async def test_the_answer_arrives_in_pieces_and_adds_up(self) -> None:
        channel = await _run("answer")
        assert len(channel.deltas) > 1
        assert "".join(channel.deltas) == BODY["answer"]

    async def test_without_a_field_nothing_streams(self) -> None:
        """Every other structured agent keeps emitting its output once, at the end."""
        assert (await _run(None)).deltas == []


class TestPartialJson:
    def test_a_half_written_string_is_read(self) -> None:
        assert _partial_field('{"answer": "BERT mas', "answer") == "BERT mas"

    def test_a_field_not_yet_reached_is_empty(self) -> None:
        assert _partial_field('{"citations": [', "answer") == ""

    def test_broken_json_is_empty(self) -> None:
        assert _partial_field("{{", "answer") == ""
