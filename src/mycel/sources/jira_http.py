"""One REST call on one person's Jira grant: retried past 429, failures named."""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx2

from mycel.core.logging import get_logger
from mycel.sources import NotWritten, SourceError

HTTP_TIMEOUT_SECONDS = 30.0

#: Retries after a 429; `Retry-After` is honored, else exponential back-off.
RETRIES = 3

#: OAuth (3LO) tokens address a site only here, under its cloud id.
API_HOST = "https://api.atlassian.com"

log = get_logger(__name__)


@dataclass(frozen=True)
class Auth:
    """Whose grant a call runs on: a short-lived access token and the site it opens."""

    access_token: str
    cloud_id: str


async def call(
    auth: Auth,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One REST call whose answer is an object, which is every endpoint but `/user/search`."""
    payload = await request(auth, method, path, body, params)
    return payload if isinstance(payload, dict) else {}


async def request(
    auth: Auth,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    params: dict[str, str] | None = None,
) -> Any:
    """One REST call on one person's grant, retried past rate limiting, failures named."""
    url = f"{API_HOST}/ex/jira/{auth.cloud_id}/rest/api/3{path}"
    headers = {
        "authorization": f"Bearer {auth.access_token}",
        "accept": "application/json",
    }

    for attempt in range(RETRIES):
        try:
            async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, headers=headers) as client:
                response = await client.request(method, url, json=body, params=params)
        except httpx2.TimeoutException as exc:
            raise SourceError(f"jira: {path} did not respond in {HTTP_TIMEOUT_SECONDS}s") from exc
        except httpx2.HTTPError as exc:
            # A connection never made cannot have written anything.
            raise NotWritten(f"jira: could not reach {url}: {exc}") from exc

        if response.status_code == 429 and attempt < RETRIES - 1:
            await _wait(response, attempt)
            continue
        return _checked(path, response)

    raise SourceError(f"jira: {path} unreachable after {RETRIES} attempts")


async def _wait(response: "httpx2.Response", attempt: int) -> None:
    """Honor `Retry-After` when Jira sends one, and back off when it does not."""
    header = response.headers.get("Retry-After", "")
    delay = float(header) if header.isdigit() else 2.0**attempt
    log.warning("jira rate limited, backing off", extra={"seconds": delay, "attempt": attempt})
    await asyncio.sleep(delay)


def _checked(path: str, response: "httpx2.Response") -> Any:
    """Turn a failed response into an actionable error; a 4xx is `NotWritten`."""
    # Each 4xx below means Jira refused, so nothing was written.
    if response.status_code == 401:
        raise NotWritten(
            "jira: that grant was refused — the account was disconnected or its access "
            "revoked. Connect Jira again in settings."
        )
    if response.status_code == 403:
        raise NotWritten(f"jira: {path} is forbidden for the account that consented")
    if response.status_code == 429:
        raise NotWritten(f"jira: {path} was rate limited {RETRIES} times running")
    if response.status_code == 404:
        raise NotWritten(f"jira: {path} does not exist — check the site and the project key")

    if response.status_code == 204 or not response.content:
        # A successful transition answers 204 with no body.
        return {}

    try:
        payload = response.json()
    except ValueError as exc:
        raise SourceError(f"jira: {path} answered with something that is not JSON") from exc

    if not response.is_success:
        messages: list[Any] = []
        if isinstance(payload, dict):
            messages = list(payload.get("errorMessages") or payload.get("errors", {}).values())
        said = "; ".join(str(m) for m in messages) or response.text[:200]
        # A 4xx is a refusal; a 5xx says nothing about whether the write landed.
        error = NotWritten if response.status_code < 500 else SourceError
        raise error(f"jira: {path} failed: {said}")
    return payload
