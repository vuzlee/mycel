"""Old search pages are cut before the next request; their urls and calls stay."""

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from mycel.agents.core.history import KEEP_ROUNDS, shrink_old_results
from mycel.agents.tools.web_search import Passage, SearchResult


def _round(i: int, content: object, tool: str = "web_search") -> list[ModelMessage]:
    return [
        ModelResponse(parts=[ToolCallPart(tool, {"query": f"q{i}"}, tool_call_id=f"c{i}")]),
        ModelRequest(parts=[ToolReturnPart(tool, content, tool_call_id=f"c{i}")]),
    ]


def _page(i: int) -> SearchResult:
    return SearchResult(
        query=f"q{i}", passages=[Passage(title="t", url=f"https://x/{i}", content="long " * 500)]
    )


def _content(messages: list[ModelMessage], i: int) -> object:
    request = messages[2 * i + 1]
    assert isinstance(request, ModelRequest)
    part = request.parts[0]
    assert isinstance(part, ToolReturnPart)
    return part.content


def test_old_pages_lose_their_text_but_keep_their_url() -> None:
    history = [m for i in range(5) for m in _round(i, _page(i))]
    out = shrink_old_results(history)
    first = _content(out, 0)
    assert isinstance(first, SearchResult)
    assert first.passages[0].content == ""
    assert first.passages[0].url == "https://x/0"


def test_the_latest_rounds_stay_whole() -> None:
    history = [m for i in range(5) for m in _round(i, _page(i))]
    out = shrink_old_results(history)
    for i in range(5 - KEEP_ROUNDS, 5):
        assert _content(out, i) == _page(i)


def test_a_batch_of_results_is_cut_item_by_item() -> None:
    history = [m for i in range(5) for m in _round(i, [_page(i), _page(i + 10)])]
    first = _content(shrink_old_results(history), 0)
    assert isinstance(first, list)
    assert [r.passages[0].content for r in first] == ["", ""]


def test_a_delegate_answer_is_never_cut() -> None:
    """The orchestrator writes its report from these; there is nothing to fetch again."""
    history = [m for i in range(5) for m in _round(i, "finding " * 500, tool="ask_researcher")]
    assert shrink_old_results(history) == history


def test_the_input_is_not_changed() -> None:
    history = [m for i in range(5) for m in _round(i, _page(i))]
    shrink_old_results(history)
    assert _content(history, 0) == _page(0)
