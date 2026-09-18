"""The researcher's tool: search the open web and bring back passages with their URLs.

Backed by Tavily, which is built for this caller. A general search API answers with a page
of links, and an agent handed ten links has to fetch and read each one before it can say
anything — ten round trips, ten pages of navigation chrome, and a context window spent on
markup. Tavily returns the relevant passage from each page instead, so one call is enough
to write a sourced statement.

**Every passage keeps its URL, and that is the point of the tool.** A finding the report
cannot attribute is indistinguishable from one the model invented, so `SearchResult` has no
shape in which a passage exists without the place it came from.

**Failures here are not the model's to fix.** `compute.py` raises `ModelRetry` because its
errors are argument errors — wrong numbers, fixable by calling again. An exhausted quota or
a search API that is down is not: re-prompting walks the model round the same loop until
`max_retries` turns an outage into an unreadable run error. Those raise `ToolFailed`, and
the one genuinely fixable case — an empty query — stays `ModelRetry`.

No results is a *result*, not a failure: the model is told the search was empty so it can
say the web has nothing on this, which is a legitimate finding.
"""

from typing import Any

import httpx2
from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.core.guards import guard_repeat
from mycel.core.config import get_settings

_ENDPOINT = "https://api.tavily.com/search"

#: Ranked by relevance, so the tail of a long list is mostly noise the model still pays
#: for in context. Five is enough to cross-check a claim against more than one source.
_MAX_RESULTS = 5

#: Tavily's own codes for "your plan is spent" — distinct from 429, which is a rate limit
#: that would pass on its own. Neither is recoverable inside this run.
_QUOTA_EXHAUSTED = (432, 433)


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
    passages: list[Passage] = Field(
        description="Extracts, most relevant first. Empty when the web has nothing."
    )


def build_toolset() -> FunctionToolset[MycelDeps]:
    """The web search capability as a toolset an agent can be given."""
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="web_search")
    async def _web_search(ctx: RunContext[MycelDeps], query: str) -> SearchResult:
        """Search the web for current information, returning passages with their URLs.

        Use for anything the prompt does not contain and that may have changed recently.
        Cite the url of every passage you rely on.
        """
        guard_repeat(ctx, "web_search", threshold=ctx.deps.settings.repeat_threshold, query=query)

        if not query.strip():
            raise ModelRetry("web_search needs a non-empty query; say what to search for")

        payload = await _post(query, timeout_s=ctx.deps.settings.timeout_s)
        return SearchResult(
            query=query,
            passages=[
                Passage(
                    title=item.get("title") or item.get("url", ""),
                    url=item["url"],
                    content=item.get("content", ""),
                    published=item.get("published_date"),
                )
                # A result without a url cannot be cited, and an uncitable passage is
                # exactly what this tool exists to prevent — so it is dropped rather
                # than passed on with an empty source.
                for item in payload.get("results", [])
                if item.get("url")
            ],
        )

    return toolset


async def _post(query: str, timeout_s: float) -> dict[str, Any]:
    """One call to Tavily, with every failure named in terms the caller can act on."""
    settings = get_settings()
    if settings.tavily_api_key is None:
        raise ToolFailed("web_search", "TAVILY_API_KEY is not set")

    try:
        async with httpx2.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {settings.tavily_api_key.get_secret_value()}"},
                json={
                    "query": query,
                    "max_results": _MAX_RESULTS,
                    "include_published_date": True,
                },
            )
    except httpx2.TimeoutException as exc:
        raise ToolFailed("web_search", f"the search API did not respond in {timeout_s}s") from exc
    except httpx2.HTTPError as exc:
        raise ToolFailed("web_search", f"could not reach the search API: {exc}") from exc

    _raise_for_status(response)
    return dict(response.json())


def _raise_for_status(response: "httpx2.Response") -> None:
    """Turn Tavily's status codes into failures that say what to do about them.

    Split by who can fix it: a key or quota problem is the operator's, and saying which one
    is the difference between rotating a key and topping up an account.
    """
    if response.is_success:
        return

    if response.status_code == 401:
        raise ToolFailed("web_search", "TAVILY_API_KEY was rejected")
    if response.status_code in _QUOTA_EXHAUSTED:
        raise ToolFailed("web_search", "the Tavily plan's usage limit is spent")
    if response.status_code == 429:
        raise ToolFailed("web_search", "the search API is rate limiting this key")

    raise ToolFailed("web_search", f"the search API returned HTTP {response.status_code}")
