"""The web search tool, against a fake Tavily.

No request leaves the machine: `httpx2.MockTransport` answers in place of the API, which
makes the failure cases — a spent quota, a rejected key, a timeout — testable at all. They
are the ones worth pinning down, because each has to fail in a way the *operator* can act
on rather than sending the model round another loop.
"""

from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai import ModelRetry

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.tools import web_search
from mycel.core.config import Settings
from mycel.llm.budget import JobBudget

pytestmark = pytest.mark.anyio


def _settings(**kw: Any) -> Settings:
    kw.setdefault("tavily_api_key", SecretStr("tvly-test"))
    return Settings(**kw)


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key by default; the tests that care about its absence override this."""
    monkeypatch.setattr(web_search, "get_settings", _settings)


#: Captured before any test patches the name, so the factory below builds a real client
#: rather than recursing into its own replacement.
_REAL_CLIENT = httpx2.AsyncClient


def _mock(handler: Any) -> Any:
    """A client factory whose requests are answered by `handler` instead of the network."""

    def _client(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=httpx2.MockTransport(handler), **kwargs)

    return _client


def _responds(payload: dict[str, Any], status: int = 200) -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=payload)

    return _mock(handler)


def _deps() -> MycelDeps:
    return MycelDeps(
        job_id="job-1",
        budget=JobBudget("job-1", Decimal("1.00")),
        settings=AgentSettings(model_spec="local:qwen3-4b", repeat_threshold=1_000_000),
    )


async def _search(ctx_query: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Call the tool the way an agent would, through its toolset."""
    toolset = web_search.build_toolset()
    tool = toolset.tools["web_search"]
    ctx = _fake_ctx()
    return await tool.function(ctx, ctx_query)


def _fake_ctx() -> Any:
    """A RunContext carrying only what the tool reads: deps and the message history."""

    class _Ctx:
        deps = _deps()
        messages: list[Any] = []

    return _Ctx()


class TestResults:
    async def test_passages_keep_their_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole reason the tool exists: a passage that cannot be cited is useless."""
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            _responds(
                {
                    "results": [
                        {
                            "title": "Q2 report",
                            "url": "https://example.com/q2",
                            "content": "Revenue rose 17.5%.",
                            "published_date": "2026-07-01",
                        }
                    ]
                }
            ),
        )
        result = await _search("q2 revenue", monkeypatch)
        assert len(result.passages) == 1
        assert result.passages[0].url == "https://example.com/q2"
        assert result.passages[0].published == "2026-07-01"

    async def test_a_result_without_a_url_is_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An uncitable passage is what this tool exists to prevent."""
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            _responds(
                {
                    "results": [
                        {"title": "no url", "content": "..."},
                        {"title": "ok", "url": "https://example.com/a", "content": "..."},
                    ]
                }
            ),
        )
        result = await _search("anything", monkeypatch)
        assert [p.url for p in result.passages] == ["https://example.com/a"]

    async def test_no_results_is_not_a_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """That the web is silent on a question is a finding the model should report."""
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({"results": []}))
        result = await _search("nothing at all", monkeypatch)
        assert result.passages == []

    async def test_an_undated_page_stays_undated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Null means unknown age. Filling it in would make a stale page look current."""
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            _responds({"results": [{"url": "https://example.com/x", "content": "..."}]}),
        )
        result = await _search("x", monkeypatch)
        assert result.passages[0].published is None


class TestFailures:
    """Split by who can fix it. The model fixes its arguments; nobody re-prompts their way
    out of a spent quota."""

    async def test_an_empty_query_is_the_model_s_to_fix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ModelRetry):
            await _search("   ", monkeypatch)

    async def test_a_missing_key_names_the_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(web_search, "get_settings", lambda: Settings(tavily_api_key=None))
        with pytest.raises(ToolFailed, match="TAVILY_API_KEY"):
            await _search("anything", monkeypatch)

    async def test_a_rejected_key_is_distinct_from_a_spent_quota(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rotating a key and topping up an account are different actions."""
        monkeypatch.setattr(httpx2, "AsyncClient", _responds({}, status=401))
        with pytest.raises(ToolFailed, match="rejected"):
            await _search("anything", monkeypatch)

        monkeypatch.setattr(httpx2, "AsyncClient", _responds({}, status=432))
        with pytest.raises(ToolFailed, match="usage limit"):
            await _search("anything", monkeypatch)

    async def test_a_timeout_says_how_long_it_waited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.TimeoutException("too slow", request=request)

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))
        with pytest.raises(ToolFailed, match="did not respond"):
            await _search("anything", monkeypatch)

    async def test_an_unreachable_api_fails_rather_than_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`ToolFailed`, not `ModelRetry`: re-prompting cannot bring a host back."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("no route", request=request)

        monkeypatch.setattr(httpx2, "AsyncClient", _mock(handler))
        with pytest.raises(ToolFailed, match="could not reach"):
            await _search("anything", monkeypatch)
