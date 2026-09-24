"""Event envelope, emitter and the SSE frames, against fakes rather than a live Redis."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai import Agent, RunContext, messages
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.emit import RunEmitter
from mycel.api.routes import events
from mycel.events.channel import NullChannel, RecordingChannel
from mycel.events.event import TOOL_CALLED, TOOL_RETURNED, AgentEvent, SequencedEvent
from mycel.llm.budget import JobBudget

pytestmark = pytest.mark.anyio


class Collector:
    """Keeps everything published, so a test can read what a run said."""

    def __init__(self) -> None:
        self.published: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> None:
        self.published.append(event)


@pytest.fixture
def channel() -> Collector:
    return Collector()


@pytest.fixture
def deps(channel: Collector) -> MycelDeps:
    return MycelDeps(job_id="job-1", budget=JobBudget("job-1", Decimal("1.00")), events=channel)


def _response(*parts: Any) -> ModelResponse:
    return ModelResponse(parts=list(parts))


async def _events(*events: Any) -> Any:
    for event in events:
        yield event

def _chunks(*pieces: str) -> Any:
    """A model stream: the part starts with the first piece and grows by deltas."""
    first, rest = pieces[0], pieces[1:]
    return _events(
        messages.PartStartEvent(index=0, part=messages.TextPart(content=first)),
        *(
            messages.PartDeltaEvent(index=0, delta=messages.TextPartDelta(content_delta=p))
            for p in rest
        ),
    )

class Node:
    """A node of the agent loop, with only the attribute the emitter reads."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class TestEmitter:
    async def test_text_becomes_an_event(self, deps: MycelDeps, channel: Collector) -> None:
        emitter = RunEmitter(deps, "analyst", None)
        await emitter.node(Node(model_response=_response(messages.TextPart(content="hello"))))

        assert [(e.agent, e.type, e.payload["text"]) for e in channel.published] == [
            ("analyst", "text", "hello")
        ]

    async def test_thinking_becomes_an_event(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        """Reasoning is the agent's own prose, so it streams like text does."""
        emitter = RunEmitter(deps, "analyst", None)
        await emitter.node(
            Node(
                model_response=_response(
                    messages.ThinkingPart(content="1.41 / 1.2", signature="opaque")
                )
            )
        )

        event = channel.published[0]
        assert (event.type, event.payload) == ("thinking", {"text": "1.41 / 1.2"})

    async def test_a_tool_call_carries_its_id(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        """The id is what a nested run points back at."""
        emitter = RunEmitter(deps, "orchestrator", None)
        await emitter.node(
            Node(
                model_response=_response(
                    messages.ToolCallPart(tool_name="analyst", args="{}", tool_call_id="c1")
                )
            )
        )

        assert channel.published[0].payload["tool_call_id"] == "c1"

    async def test_a_delegated_run_is_tagged_with_its_parent_call(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        """Without this a client cannot tell nesting from interleaving."""
        emitter = RunEmitter(deps, "analyst", "c1")
        await emitter.node(Node(model_response=_response(messages.TextPart(content="42"))))

        assert channel.published[0].parent_tool_call_id == "c1"

    async def test_an_unknown_node_is_skipped(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        """A new node kind must not crash a run, only go unshown."""
        await RunEmitter(deps, "analyst", None).node(Node(something_else=1))
        assert channel.published == []

    async def test_a_long_tool_result_is_truncated(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        """Raw tool output can be a whole document; this goes to a browser."""
        emitter = RunEmitter(deps, "researcher", None)
        await emitter.node(
            Node(
                request=messages.ModelRequest(
                    parts=[
                        messages.ToolReturnPart(
                            tool_name="web_search", content="x" * 5000, tool_call_id="c1"
                        )
                    ]
                )
            )
        )

        assert len(channel.published[0].payload["result"]) == 500


class TestProseArrivesAsItIsWritten:
    """Deltas are the point of the streamed path: a long answer must not land in one block.

    The rule that keeps it honest is that the same words go out once. A model that streams
    sends deltas and the finished part is then silent; a model that cannot sends the part
    whole, and a reader cannot tell which happened.
    """

    async def test_each_piece_is_its_own_event(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        emitter = RunEmitter(deps, "orchestrator", None)
        await emitter.stream(_chunks("Hello", " there"))

        assert [(e.type, e.payload["text"]) for e in channel.published] == [
            ("text_delta", "Hello"),
            ("text_delta", " there"),
        ]

    async def test_what_was_streamed_is_not_sent_again_whole(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        emitter = RunEmitter(deps, "orchestrator", None)
        await emitter.stream(_chunks("Hello", " there"))
        await emitter.node(Node(model_response=_response(messages.TextPart(content="Hello there"))))

        assert [e.type for e in channel.published] == ["text_delta", "text_delta"]

    async def test_a_model_that_cannot_stream_still_sends_its_answer(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        emitter = RunEmitter(deps, "orchestrator", None)
        await emitter.node(Node(model_response=_response(messages.TextPart(content="Hello there"))))

        assert [(e.type, e.payload["text"]) for e in channel.published] == [
            ("text", "Hello there")
        ]

    async def test_the_next_turn_starts_over(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        """The flag is per turn: a streamed turn must not silence the one after it."""
        emitter = RunEmitter(deps, "orchestrator", None)
        await emitter.stream(_chunks("first"))
        await emitter.node(Node(model_response=_response(messages.TextPart(content="first"))))
        await emitter.node(Node(model_response=_response(messages.TextPart(content="second"))))

        assert [(e.type, e.payload["text"]) for e in channel.published] == [
            ("text_delta", "first"),
            ("text", "second"),
        ]

    async def test_a_tool_call_on_the_stream_adds_no_prose(
        self, deps: MycelDeps, channel: Collector
    ) -> None:
        """A streamed run still emits tool calls from the finished node, once."""
        emitter = RunEmitter(deps, "orchestrator", None)
        await emitter.stream(
            _events(
                messages.PartStartEvent(
                    index=0, part=messages.ToolCallPart("analyst", {"question": "q"})
                )
            )
        )

        assert channel.published == []

class TestNullChannelIsTheDefault:
    async def test_a_run_without_a_listener_publishes_nowhere(self) -> None:
        """A script or a test must not need Redis to run an agent."""
        deps = MycelDeps(job_id="j", budget=JobBudget("j", Decimal("1.00")))
        await RunEmitter(deps, "analyst", None).emit("text", text="hi")


class TestSequenceGaps:
    def test_a_client_can_tell_a_gap_from_silence(self) -> None:
        """The whole reason `seq` exists: 7 then 9 means one was dropped."""
        received = [SequencedEvent(seq=n, agent="a", type="text") for n in (7, 9)]
        assert received[1].seq - received[0].seq > 1


class TestNestingThroughARealRun:
    """The envelope's whole purpose, exercised end to end with a fake model."""

    async def test_a_delegated_run_nests_under_the_call_that_made_it(
        self, channel: Collector
    ) -> None:
        settings = AgentSettings(model_spec="local:qwen3-4b")
        deps = MycelDeps(
            job_id="job-1",
            budget=JobBudget("job-1", Decimal("1.00")),
            settings=settings,
            events=channel,
        )
        child = Agent(name="analyst", deps_type=MycelDeps, output_type=str)
        parent = Agent(name="orchestrator", deps_type=MycelDeps, output_type=str)

        def child_says(msgs: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[messages.TextPart("42")])

        @parent.tool
        async def analyst(ctx: RunContext[MycelDeps]) -> str:
            """Delegate to the analyst."""
            with child.override(model=FunctionModel(child_says)):
                return await runner.delegate(child, "sub-question", ctx)

        step = [0]

        def parent_says(msgs: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            step[0] += 1
            if step[0] == 1:
                return ModelResponse(parts=[messages.ToolCallPart("analyst", {})])
            return ModelResponse(parts=[messages.TextPart("done")])

        with parent.override(model=FunctionModel(parent_says)):
            await runner.run(parent, "go", deps)

        by_agent = {e.agent for e in channel.published}
        assert by_agent == {"orchestrator", "analyst"}

        nested = [e for e in channel.published if e.agent == "analyst"]
        call_id = next(
            e.payload["tool_call_id"]
            for e in channel.published
            if e.type == "tool_called" and e.agent == "orchestrator"
        )
        # Every analyst event points at the call that started it — never at nothing.
        assert {e.parent_tool_call_id for e in nested} == {call_id}

    async def test_the_top_level_run_has_no_parent(self, channel: Collector) -> None:
        """A client uses this to know which events sit at the root."""
        deps = MycelDeps(
            job_id="job-1",
            budget=JobBudget("job-1", Decimal("1.00")),
            settings=AgentSettings(model_spec="local:qwen3-4b"),
            events=channel,
        )
        agent = Agent(name="orchestrator", deps_type=MycelDeps, output_type=str)

        def says(msgs: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[messages.TextPart("done")])

        with agent.override(model=FunctionModel(says)):
            await runner.run(agent, "go", deps)

        assert {e.parent_tool_call_id for e in channel.published} == {None}


    async def test_a_streaming_model_reaches_the_client_in_pieces(
        self, channel: Collector
    ) -> None:
        """The whole point, through `runner.run`: one answer, several events.

        `FunctionModel` streams only when given a `stream_function`, which is also how the
        runner decides whether to open the node as a stream at all.
        """
        deps = MycelDeps(
            job_id="job-1",
            budget=JobBudget("job-1", Decimal("1.00")),
            settings=AgentSettings(model_spec="local:qwen3-4b"),
            events=channel,
        )
        agent = Agent(name="orchestrator", deps_type=MycelDeps, output_type=str)

        async def writes(msgs: list[ModelMessage], info: AgentInfo) -> Any:
            for piece in ("The ", "answer ", "is 42."):
                yield piece

        with agent.override(model=FunctionModel(stream_function=writes)):
            answer = await runner.run(agent, "go", deps)

        assert answer == "The answer is 42."
        prose = [(e.type, e.payload["text"]) for e in channel.published if "text" in e.payload]
        assert prose == [
            ("text_delta", "The "),
            ("text_delta", "answer "),
            ("text_delta", "is 42."),
        ], "the answer must arrive in pieces, and not a fourth time whole"

class FakeRequest:
    """A request that is connected until a test says otherwise."""

    def __init__(self, disconnect_after: int | None = None) -> None:
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._disconnect_after is not None and self._checks > self._disconnect_after


async def _collect(
    items: list[Any],
    request: Any,
    monkeypatch: pytest.MonkeyPatch,
    kept: Any = None,
    stream: bool = True,
) -> list[str]:
    """Drive `_frames` over a canned stream instead of Redis.

    `kept` is what `app.turn` holds for the job and `stream` whether Redis still has the
    key. The default pair — no record, stream present — is a run still in flight, which is
    what most tests here are about.
    """

    async def fake_read(job_id: str, after: str = "0") -> Any:
        for item in items:
            yield item

    async def fake_exists(job_id: str) -> bool:
        return stream

    async def fake_find_turn(job_id: str) -> Any:
        return kept

    monkeypatch.setattr(events.streams, "read", fake_read)
    monkeypatch.setattr(events.streams, "exists", fake_exists)
    monkeypatch.setattr(events, "find_turn", fake_find_turn)
    return [frame async for frame in events._frames(request, "job-1", "0")]


class TestSseFrames:
    async def test_an_event_becomes_a_frame_with_its_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The id is what the browser sends back as Last-Event-ID."""
        event = SequencedEvent(seq=1, agent="analyst", type="text", payload={"text": "hi"})
        frames = await _collect([("1700-0", event)], FakeRequest(), monkeypatch)

        assert frames[0].startswith("id: 1700-0\ndata: {")
        assert frames[0].endswith("\n\n")

    async def test_the_type_travels_in_the_json_not_an_event_line(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An `event:` line would make a client drop every type it was not built for."""
        event = SequencedEvent(seq=1, agent="analyst", type="text")
        frames = await _collect([("1700-0", event)], FakeRequest(), monkeypatch)

        assert "event:" not in frames[0]
        assert '"type":"text"' in frames[0]

    async def test_a_quiet_job_sends_a_keepalive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Otherwise a proxy closes a connection that is merely waiting."""
        frames = await _collect([None, None], FakeRequest(), monkeypatch)
        assert frames == [events.KEEPALIVE, events.KEEPALIVE]

    async def test_a_disconnected_client_stops_the_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without this the generator keeps reading Redis for nobody."""
        event = SequencedEvent(seq=1, agent="analyst", type="text")
        frames = await _collect(
            [("1-0", event), ("2-0", event)], FakeRequest(disconnect_after=1), monkeypatch
        )

        assert len(frames) == 1


class TestAFinishedRunDoesNotBlock:
    """A run whose stream is gone but whose answer is kept (MYC-61).

    Redis holds the stream under a TTL and loses it outright on restart; `app.turn` holds
    the answer. Without the short circuit the client subscribes to a key nothing will ever
    write to, `xread` blocks until it times out, and the composer stays disabled on a
    question that was answered days ago.
    """

    async def test_a_kept_turn_with_no_stream_closes_at_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One run_finished and nothing else — there is nothing left to wait for."""
        frames = await _collect([], FakeRequest(), monkeypatch, kept=object(), stream=False)

        assert len(frames) == 1
        assert '"type":"run_finished"' in frames[0]

    async def test_it_does_not_read_the_stream_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The blocking read is what hangs, so the fix has to be not reaching it."""
        frames = await _collect(
            [("1-0", SequencedEvent(seq=1, agent="a", type="text"))],
            FakeRequest(),
            monkeypatch,
            kept=object(),
            stream=False,
        )

        assert len(frames) == 1
        assert '"type":"run_finished"' in frames[0]

    async def test_a_run_that_just_finished_still_replays_its_tool_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The record alone is not enough to close on (MYC-63).

        A finished run has a turn row within milliseconds, and its stream is still there. A
        reader opening the page a moment later has to see the calls the run made — closing
        on the row would leave every answer with an empty middle.
        """
        called = SequencedEvent(seq=1, agent="analyst", type=TOOL_CALLED, payload={"tool": "sql"})
        frames = await _collect(
            [("1-0", called)], FakeRequest(), monkeypatch, kept=object(), stream=True
        )

        assert len(frames) == 1
        assert '"type":"tool_called"' in frames[0]


class TestATurnKeepsItsToolCalls:
    """What `app.turn.steps` gets, so a reopened thread is not an empty middle (MYC-41)."""

    async def test_everything_still_reaches_the_stream(self) -> None:
        """The recorder wraps, it does not replace: a page watching live loses nothing."""
        inner = Collector()
        recorder = RecordingChannel(inner)

        await recorder.publish(AgentEvent(agent="a", type="thinking", payload={"text": "hm"}))
        await recorder.publish(AgentEvent(agent="a", type=TOOL_CALLED, payload={"tool": "sql"}))

        assert [event.type for event in inner.published] == ["thinking", TOOL_CALLED]

    async def test_only_tool_calls_are_kept(self) -> None:
        """Reasoning is worth watching and not worth storing; a call is what makes an
        answer checkable."""
        recorder = RecordingChannel(NullChannel())

        for type_ in ("run_started", "thinking", TOOL_CALLED, TOOL_RETURNED, "text"):
            await recorder.publish(AgentEvent(agent="a", type=type_))

        assert [step["type"] for step in recorder.steps] == [TOOL_CALLED, TOOL_RETURNED]

    async def test_steps_are_numbered_from_one(self) -> None:
        """Their own sequence, not the stream's: the stream counts every event, so a kept
        list carrying its numbers would replay as one long gap."""
        recorder = RecordingChannel(NullChannel())

        for _ in range(3):
            await recorder.publish(AgentEvent(agent="a", type=TOOL_CALLED))

        assert [step["seq"] for step in recorder.steps] == [1, 2, 3]

    async def test_a_turn_that_called_nothing_keeps_nothing(self) -> None:
        recorder = RecordingChannel(NullChannel())
        await recorder.publish(AgentEvent(agent="a", type="text", payload={"text": "hello"}))

        assert recorder.steps == []

    async def test_the_head_survives_the_ceiling_and_the_rest_is_counted(self) -> None:
        """A looping run writes the same call forever. The first calls are the ones that
        chose the direction, so they are what is kept — and the loss is reported rather
        than silent."""
        recorder = RecordingChannel(NullChannel())

        for n in range(RecordingChannel.MAX_STEPS + 5):
            await recorder.publish(AgentEvent(agent="a", type=TOOL_CALLED, payload={"n": n}))

        assert len(recorder.steps) == RecordingChannel.MAX_STEPS
        assert recorder.steps[0]["payload"] == {"n": 0}
        assert recorder.dropped == 5
