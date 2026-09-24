"""The Jira connector: read issues and worklogs, and write comments and transitions back.

Returns payloads exactly as they arrived. Nothing is parsed here — `services/fetch.py`
puts them in bronze, `etl/` gives them meaning.

**The write half is off unless `JIRA_WRITE_ENABLED` says otherwise.** Reading someone's
tracker wrongly is recoverable; commenting on fifty issues, or moving them, is not. It is
one flag rather than a per-call argument so that a deployment cannot be half-armed.

Basic auth with an API token, not OAuth: one deployment, one Atlassian account, and a
token needs no redirect URI or refresh loop. The token expires after exactly one year,
silently and with nothing in the API to warn about it, which is why a 401 gets its own
message rather than being folded in with the rest.

Two calls, and deliberately not a third. `GET /issue/{key}/changelog` would give status
transitions, but Jira stamps a transition with the moment of the API call, so for any
issue entered retroactively the history would be a confident lie. Worklogs are the
exception — their `started` is whatever it is told — so effort over time comes from
those, and nothing downstream claims to know how long something sat in a status.
"""

from typing import Any

import httpx2

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.sources import SourceError

#: Issues per search page. Jira's own ceiling for this endpoint; a sync with more to read
#: follows the page token rather than asking for a bigger page.
PAGE = 100

HTTP_TIMEOUT_S = 30.0

#: Retries after a 429. Jira's rate limits are adaptive and undocumented, so the only
#: honest strategy is to believe `Retry-After` and back off when it is absent.
RETRIES = 3

#: The fields a work item is built from. Asking for the set we use rather than `*all`
#: keeps a payload that has to fit in bronze down to what is actually read.
FIELDS = (
    "summary",
    "issuetype",
    "status",
    "priority",
    "parent",
    "assignee",
    "duedate",
    "created",
    "resolutiondate",
    "updated",
    "labels",
    "timetracking",
    "timeoriginalestimate",
    "timespent",
)

log = get_logger(__name__)


async def search_issues(jql: str) -> list[dict[str, Any]]:
    """Every issue matching `jql`, following Jira's page token to the end.

    The caller writes the JQL because "which project, changed since when" is a question
    about the deployment, not about the transport.
    """
    issues: list[dict[str, Any]] = []
    token: str | None = None

    while True:
        # The sprint field is a custom field and its id differs per site, so it is
        # appended from settings rather than living in FIELDS. Jira ignores an id the
        # site does not have, which is what makes asking for it unconditionally safe.
        fields = [*FIELDS, get_settings().jira_sprint_field]
        body: dict[str, Any] = {"jql": jql, "fields": fields, "maxResults": PAGE}
        if token:
            body["nextPageToken"] = token

        page = await _call("POST", "/search/jql", body)
        issues += [i for i in page.get("issues", []) if isinstance(i, dict)]

        token = page.get("nextPageToken")
        if not token:
            break

    log.info("fetched jira issues", extra={"count": len(issues), "jql": jql})
    return issues


async def issue_worklogs(key: str) -> list[dict[str, Any]]:
    """Every logged entry on one issue, each with the date it was logged *for*.

    One request per issue, which is why `services/fetch.py` only asks for the issues a
    sync actually brought in rather than for the whole project every tick.
    """
    payload = await _call("GET", f"/issue/{key}/worklog", None)
    return [w for w in payload.get("worklogs", []) if isinstance(w, dict)]


async def add_comment(key: str, text: str) -> dict[str, Any]:
    """Leave a comment on one issue. Returns the created comment as Jira describes it.

    The body is Atlassian Document Format, not a string: the v3 API rejects plain text, and
    a plain-text field on v2 would tie this to an endpoint Atlassian is retiring. One
    paragraph, because what Mycel has to say is a sentence about progress, not a document.
    """
    _writable()
    body = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }
    }
    created = await _call("POST", f"/issue/{key}/comment", body)
    log.info("commented on jira issue", extra={"key": key, "chars": len(text)})
    return created


async def transitions_for(key: str) -> list[dict[str, Any]]:
    """The moves this issue can make right now, each with the id `transition` needs.

    Read first, always. Transition ids are per workflow and not stable across projects, so
    a hardcoded "31 means Done" is right until the day somebody edits the workflow — and
    then it silently moves issues somewhere else.
    """
    payload = await _call("GET", f"/issue/{key}/transitions", None)
    return [t for t in payload.get("transitions", []) if isinstance(t, dict)]


async def transition(key: str, to_status: str) -> None:
    """Move an issue to the named status, if the workflow allows it from where it is.

    Named by status rather than by id for the reason above. Matched case-insensitively, and
    a status this issue cannot currently reach raises rather than passing quietly: a
    transition that did not happen looks exactly like one that did, from the response.
    """
    _writable()
    wanted = to_status.strip().lower()
    for move in await transitions_for(key):
        if str(move.get("to", {}).get("name", "")).lower() == wanted:
            await _call("POST", f"/issue/{key}/transitions", {"transition": {"id": move["id"]}})
            log.info("transitioned jira issue", extra={"key": key, "to": to_status})
            return
    raise SourceError(f"jira: {key} cannot move to {to_status!r} from where it is")


def _writable() -> None:
    """Refuse every write unless the deployment has armed them."""
    if not get_settings().jira_write_enabled:
        raise SourceError("jira: writing is off — set JIRA_WRITE_ENABLED to turn it on")


async def _call(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
    """One REST call, retried past rate limiting, with every failure named."""
    settings = get_settings()
    if not settings.jira_base_url:
        raise SourceError("JIRA_BASE_URL is not set")
    if not settings.jira_email or settings.jira_api_token is None:
        raise SourceError("JIRA_EMAIL and JIRA_API_TOKEN are both needed")

    url = f"{settings.jira_base_url.rstrip('/')}/rest/api/3{path}"
    auth = (settings.jira_email, settings.jira_api_token.get_secret_value())

    for attempt in range(RETRIES):
        try:
            async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S, auth=auth) as client:
                response = await client.request(method, url, json=body)
        except httpx2.TimeoutException as exc:
            raise SourceError(f"jira: {path} did not respond in {HTTP_TIMEOUT_S}s") from exc
        except httpx2.HTTPError as exc:
            raise SourceError(f"jira: could not reach {url}: {exc}") from exc

        if response.status_code == 429 and attempt < RETRIES - 1:
            await _wait(response, attempt)
            continue
        return _checked(path, response)

    raise SourceError(f"jira: {path} unreachable after {RETRIES} attempts")


async def _wait(response: "httpx2.Response", attempt: int) -> None:
    """Honour `Retry-After` when Jira sends one, and back off when it does not."""
    import asyncio

    header = response.headers.get("Retry-After", "")
    delay = float(header) if header.isdigit() else 2.0**attempt
    log.warning("jira rate limited, backing off", extra={"seconds": delay, "attempt": attempt})
    await asyncio.sleep(delay)


def _checked(path: str, response: "httpx2.Response") -> dict[str, Any]:
    """Turn a failed response into a message an operator can act on.

    401 is given its own sentence because after a year it is the expected failure and not
    a bug: the token has quietly reached its expiry and a new one has to be issued. A 429
    reaching here means the retries are spent, and the message has to say that rather than
    quote an empty error body.
    """
    if response.status_code == 401:
        raise SourceError("JIRA_API_TOKEN was rejected — tokens expire one year after issue")
    if response.status_code == 403:
        raise SourceError(f"jira: {path} is forbidden for {get_settings().jira_email}")
    if response.status_code == 429:
        raise SourceError(f"jira: {path} was rate limited {RETRIES} times running")
    if response.status_code == 404:
        raise SourceError(f"jira: {path} does not exist — check JIRA_BASE_URL and the project key")

    if response.status_code == 204 or not response.content:
        # A successful transition answers 204 with nothing in it. Only the write calls do
        # this; a read that came back empty still falls through to the JSON error below.
        return {}

    try:
        payload = dict(response.json())
    except ValueError as exc:
        raise SourceError(f"jira: {path} answered with something that is not JSON") from exc

    if not response.is_success:
        messages = payload.get("errorMessages") or [response.text]
        raise SourceError(f"jira: {path} failed: {'; '.join(str(m) for m in messages)}")
    return payload
