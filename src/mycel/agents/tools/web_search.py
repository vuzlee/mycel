"""Tool: search the web via Tavily, returning passages with their URLs."""

import asyncio
import re
from datetime import datetime
from typing import Any, Literal

import httpx2
from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.chips import opens
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.core.guards import guard_repeat
from mycel.core.chips import Chip
from mycel.core.config import get_settings
from mycel.infra.http import shared

_ENDPOINT = "https://api.tavily.com/search"

#: Enough to cross-check a claim; the ranked tail is mostly noise.
_MAX_RESULTS = 5

#: Searches per call; enough angles for one question, few enough to keep results readable.
_MAX_QUERIES = 5

#: Tavily's "plan spent" codes, distinct from a 429 rate limit.
_QUOTA_EXHAUSTED = (432, 433)

#: Tavily's `time_range`; a filter, so "recent" never depends on the model knowing the year.
Recency = Literal["day", "week", "month", "year"]


class Passage(BaseModel):
    """One extract from one page, with where to find it again."""

    title: str = Field(description="The page's title.")
    url: str = Field(description="The page this passage came from. Cite it verbatim.")
    content: str = Field(description="The part of the page that answers the query.")
    published: str | None = Field(
        default=None,
        description="Publication date as YYYY-MM-DD, when the page states one. Null "
        "otherwise — treat an undated page as of unknown age, not as current.",
    )


class SearchResult(BaseModel):
    """What one search brought back."""

    query: str = Field(description="The query that was run, echoed back.")
    warning: str | None = Field(
        default=None, description="Set when the query looks dated; read it before searching again."
    )
    passages: list[Passage] = Field(
        description="Extracts, most relevant first. Empty when the web has nothing."
    )

    def brief(self) -> "SearchResult":
        """Kept for citing once the model has moved on: where each passage was, not its text."""
        return self.model_copy(
            update={"passages": [p.model_copy(update={"content": ""}) for p in self.passages]}
        )


def build_toolset() -> FunctionToolset[MycelDeps]:
    toolset: FunctionToolset[MycelDeps] = FunctionToolset(metadata=opens(Chip.WEB))

    @toolset.tool(name="web_search")
    async def _web_search(
        ctx: RunContext[MycelDeps], queries: list[str], recency: Recency | None = None
    ) -> list[SearchResult]:
        """Search the web for current information, returning passages with their URLs.

        Use for anything the prompt does not contain and that may have changed recently.
        Put every search you already know you need in one call; they run together.
        Cite the url of every passage you rely on.

        Args:
            queries: One to five searches, each on one angle. No year or date in them; use
                `recency` instead.
            recency: Only pages from the last day, week, month or year. Leave empty for any age.
        """
        guard_repeat(ctx, "web_search", queries=queries, recency=recency)

        asked = [q.strip() for q in queries if q.strip()]
        if not asked:
            raise ModelRetry("web_search needs at least one non-empty query")
        if len(asked) > _MAX_QUERIES:
            raise ModelRetry(f"web_search takes at most {_MAX_QUERIES} queries; keep the best")

        year = datetime.now(ctx.deps.tz).year
        payloads = await asyncio.gather(
            *(_post(q, recency, timeout_s=ctx.deps.settings.timeout_s) for q in asked)
        )
        return [
            _result(q, stale_year(q, recency, year), payload)
            for q, payload in zip(asked, payloads, strict=True)
        ]

    return toolset


def _result(query: str, warning: str | None, payload: dict[str, Any]) -> SearchResult:
    return SearchResult(
        query=query,
        warning=warning,
        passages=[
            Passage(
                title=item.get("title") or item.get("url", ""),
                url=item["url"],
                content=item.get("content", ""),
                published=item.get("published_date"),
            )
            # Uncitable without a url, so dropped.
            for item in payload.get("results", [])
            if item.get("url")
        ],
    )


def stale_year(query: str, recency: "Recency | None", this_year: int) -> str | None:
    """A recent search naming an earlier year: a model's training year, not the asker's."""
    if recency not in ("day", "week"):
        return None
    old = sorted({y for y in map(int, re.findall(r"\b(?:19|20)\d{2}\b", query)) if y < this_year})
    if not old:
        return None
    return f"It is {this_year}; this query names {', '.join(map(str, old))}. Drop the year."


async def _post(query: str, recency: Recency | None, timeout_s: float) -> dict[str, Any]:
    """One call to Tavily; every failure raises `ToolFailed`."""
    settings = get_settings()
    if settings.tavily_api_key is None:
        raise ToolFailed("web_search", "TAVILY_API_KEY is not set")

    try:
        response = await shared().post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {settings.tavily_api_key.get_secret_value()}"},
            json={
                "query": query,
                "max_results": _MAX_RESULTS,
                "include_published_date": True,
                **({"time_range": recency} if recency else {}),
            },
            timeout=timeout_s,
        )
    except httpx2.TimeoutException as exc:
        raise ToolFailed("web_search", f"the search API did not respond in {timeout_s}s") from exc
    except httpx2.HTTPError as exc:
        raise ToolFailed("web_search", f"could not reach the search API: {exc}") from exc

    _raise_for_status(response)
    return dict(response.json())


def _raise_for_status(response: "httpx2.Response") -> None:
    """Turn Tavily's status codes into failures that say what to do about them."""
    if response.is_success:
        return

    if response.status_code == 401:
        raise ToolFailed("web_search", "TAVILY_API_KEY was rejected")
    if response.status_code in _QUOTA_EXHAUSTED:
        raise ToolFailed("web_search", "the Tavily plan's usage limit is spent")
    if response.status_code == 429:
        raise ToolFailed("web_search", "the search API is rate limiting this key")

    raise ToolFailed("web_search", f"the search API returned HTTP {response.status_code}")
