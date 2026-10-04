"""The Jira connector: read issues and worklogs, and write back as whoever is asking.

Returns payloads exactly as they arrived. Nothing is parsed here — `services/fetch.py`
puts them in bronze, `etl/` gives them meaning.

**Every call runs on one person's OAuth token, and which person is the caller's to decide.**
Until batch 060 this file used one API token out of `.env`, and that was adequate while it
only read: everyone saw the same board and nobody's name was recorded. It stopped being
adequate the moment it wrote — a comment on a shared token appears under the host's name
whoever typed it, and Jira cannot correct the author of an event already recorded. So a
call takes an `Auth`, and `services/jira_oauth.py` is where one comes from: the syncer's
for a background read, the asker's for anything a question caused.

**A failed write says whether it is certain nothing happened.** `NotWritten` — a 4xx, a
connection never made, a switch that is off — means the request cannot have landed, and
`agents/tools/jira.py` offers the draft again on it. A timeout or a 5xx stays a plain
`SourceError`, because the request may have arrived and only the answer been lost, and a
retry there posts the same comment twice.

**The write half is off unless `JIRA_WRITE_ENABLED` says otherwise, and creating a project
has a second switch of its own.** Commenting on fifty issues by mistake is recoverable in
Jira; a project created by mistake often is not — many sites refuse to delete one over the
API and a project key is never reusable. Two switches rather than one, so a deployment can
have the first three writes without being made to take the fourth.

**No delete, of anything.** The scope asked for is wide enough to create and to change and
no wider. Removing an issue or a project is done in Jira, where the person can see what
they are removing.

Two reads, and deliberately not a third. `GET /issue/{key}/changelog` would give status
transitions, but Jira stamps a transition with the moment of the API call, so for any
issue entered retroactively the history would be a confident lie. Worklogs are the
exception — their `started` is whatever it is told — so effort over time comes from
those, and nothing downstream claims to know how long something sat in a status.
"""

from dataclasses import dataclass
from typing import Any

import httpx2

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.sources import NotWritten, SourceError

#: Issues per search page. Jira's own ceiling for this endpoint; a sync with more to read
#: follows the page token rather than asking for a bigger page.
PAGE = 100

HTTP_TIMEOUT_S = 30.0

#: Retries after a 429. Jira's rate limits are adaptive and undocumented, so the only
#: honest strategy is to believe `Retry-After` and back off when it is absent.
RETRIES = 3

#: Where an OAuth token addresses a site. Not the `*.atlassian.net` host: that one takes
#: basic auth, and a 3LO access token is only accepted here, under the site's cloud id.
API_HOST = "https://api.atlassian.com"

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


@dataclass(frozen=True)
class Auth:
    """Whose grant this call runs on: an access token, and the site it opens.

    A value rather than a global, because the whole point of the batch is that two calls in
    one process may run as two different people — the scheduler as the syncer, a tool as
    whoever typed the question. A module-level credential cannot express that.

    Short-lived by construction: an access token lives under an hour, so one of these is
    built per unit of work and never stored.
    """

    access_token: str
    cloud_id: str


async def search_issues(auth: Auth, jql: str) -> list[dict[str, Any]]:
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

        page = await _call(auth, "POST", "/search/jql", body)
        issues += [i for i in page.get("issues", []) if isinstance(i, dict)]

        token = page.get("nextPageToken")
        if not token:
            break

    log.info("fetched jira issues", extra={"count": len(issues), "jql": jql})
    return issues


async def issue_worklogs(auth: Auth, key: str) -> list[dict[str, Any]]:
    """Every logged entry on one issue, each with the date it was logged *for*.

    One request per issue, which is why `services/fetch.py` only asks for the issues a
    sync actually brought in rather than for the whole project every tick.
    """
    payload = await _call(auth, "GET", f"/issue/{key}/worklog", None)
    return [w for w in payload.get("worklogs", []) if isinstance(w, dict)]


async def find_users(auth: Auth, query: str) -> list[dict[str, Any]]:
    """People on this site whose name or address matches, for assigning work.

    Needed because an assignment is written with an account id and a person says a name.
    The match is Jira's own and it is fuzzy — two people called Nam both come back, which
    is exactly the ambiguity a draft exists to put in front of a human before anything is
    written.
    """
    # The one endpoint here that answers with a bare array rather than an object, which is
    # why `_request` returns whatever Jira sent and `_call` is the dict-shaped wrapper.
    found = await _request(auth, "GET", "/user/search", None, params={"query": query})
    users = found if isinstance(found, list) else []
    return [u for u in users if isinstance(u, dict)]


async def add_comment(auth: Auth, key: str, text: str) -> dict[str, Any]:
    """Leave a comment on one issue, under the name whose token this is.

    The body is Atlassian Document Format, not a string: the v3 API rejects plain text, and
    a plain-text field on v2 would tie this to an endpoint Atlassian is retiring. One
    paragraph, because what Mycel has to say is a sentence about progress, not a document.
    """
    _writable()
    created = await _call(auth, "POST", f"/issue/{key}/comment", {"body": _document(text)})
    log.info("commented on jira issue", extra={"key": key, "chars": len(text)})
    return created


async def transitions_for(auth: Auth, key: str) -> list[dict[str, Any]]:
    """The moves this issue can make right now, each with the id `transition` needs.

    Read first, always. Transition ids are per workflow and not stable across projects, so
    a hardcoded "31 means Done" is right until the day somebody edits the workflow — and
    then it silently moves issues somewhere else.
    """
    payload = await _call(auth, "GET", f"/issue/{key}/transitions", None)
    return [t for t in payload.get("transitions", []) if isinstance(t, dict)]


async def transition(auth: Auth, key: str, to_status: str) -> None:
    """Move an issue to the named status, if the workflow allows it from where it is.

    Named by status rather than by id for the reason above. Matched case-insensitively, and
    a status this issue cannot currently reach raises rather than passing quietly: a
    transition that did not happen looks exactly like one that did, from the response.
    """
    _writable()
    wanted = to_status.strip().lower()
    for move in await transitions_for(auth, key):
        if str(move.get("to", {}).get("name", "")).lower() == wanted:
            body = {"transition": {"id": move["id"]}}
            await _call(auth, "POST", f"/issue/{key}/transitions", body)
            log.info("transitioned jira issue", extra={"key": key, "to": to_status})
            return
    raise NotWritten(f"jira: {key} cannot move to {to_status!r} from where it is")


async def create_issue(
    auth: Auth,
    project: str,
    kind: str,
    summary: str,
    description: str | None = None,
    assignee_id: str | None = None,
    sprint_id: int | None = None,
) -> dict[str, Any]:
    """Create one issue and return it as Jira describes it, key and all.

    `assignee_id` is an account id rather than a name, and that is the one argument this
    function will not guess: `find_users` turns a name into candidates and a person picks
    between them, because two people share a name far more often than an account id is
    mistyped.

    The sprint goes in the site's own custom field, whose id differs per site — the same
    field `search_issues` reads. Jira rejects an unknown field id outright rather than
    ignoring it, so it is only sent when a sprint was actually asked for.
    """
    _writable()
    fields: dict[str, Any] = {
        "project": {"key": project},
        "issuetype": {"name": kind},
        "summary": summary,
    }
    if description:
        fields["description"] = _document(description)
    if assignee_id:
        fields["assignee"] = {"id": assignee_id}
    if sprint_id is not None:
        fields[get_settings().jira_sprint_field] = sprint_id

    created = await _call(auth, "POST", "/issue", {"fields": fields})
    log.info("created jira issue", extra={"key": created.get("key"), "project": project})
    return created


async def create_project(
    auth: Auth, key: str, name: str, lead_account_id: str
) -> dict[str, Any]:
    """Create one project. **The only call here that cannot be undone from the app.**

    Behind its own switch, and the reason is not that it is hard to write. Many Jira sites
    refuse to delete a project over the API, and a project key is never reusable once
    taken — so a mistake here is cleaned up through a site administrator's console, if at
    all, while a wrong comment is deleted in a second.

    A team-managed (`next-gen`) software project, which is what a site creates by default
    through its own UI and the only template that needs no scheme ids nobody has typed in.
    """
    _writable()
    if not get_settings().jira_allow_create_project:
        raise NotWritten(
            "jira: creating a project is off — set JIRA_ALLOW_CREATE_PROJECT to turn it on"
        )
    body = {
        "key": key.upper(),
        "name": name,
        "projectTypeKey": "software",
        "projectTemplateKey": (
            "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum"
        ),
        "leadAccountId": lead_account_id,
    }
    created = await _call(auth, "POST", "/project", body)
    log.warning("created jira project", extra={"key": key, "name": name})
    return created


def _document(text: str) -> dict[str, Any]:
    """One paragraph as Atlassian Document Format, which the v3 API requires."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _writable() -> None:
    """Refuse every write unless the deployment has armed them."""
    if not get_settings().jira_write_enabled:
        raise NotWritten("jira: writing is off — set JIRA_WRITE_ENABLED to turn it on")


async def _call(
    auth: Auth,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One REST call whose answer is an object, which is every endpoint but `/user/search`."""
    payload = await _request(auth, method, path, body, params)
    return payload if isinstance(payload, dict) else {}


async def _request(
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
            async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S, headers=headers) as client:
                response = await client.request(method, url, json=body, params=params)
        except httpx2.TimeoutException as exc:
            raise SourceError(f"jira: {path} did not respond in {HTTP_TIMEOUT_S}s") from exc
        except httpx2.HTTPError as exc:
            # A connection that was never made cannot have written anything. Unlike the
            # timeout above, where the request may have arrived and only the answer lost.
            raise NotWritten(f"jira: could not reach {url}: {exc}") from exc

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


def _checked(path: str, response: "httpx2.Response") -> Any:
    """Turn a failed response into a message an operator can act on.

    401 gets its own sentence because it is now a *lapsed consent* rather than an expired
    token in a file: somebody revoked the app, or an admin removed it, and the fix is to
    connect again in settings rather than to edit anything. A 429 reaching here means the
    retries are spent, and the message has to say that rather than quote an empty body.
    """
    # Every branch below is a 4xx: Jira answered, and an answer of "no" is proof it did
    # not act. That is what makes them `NotWritten` and a timeout or a 5xx not.
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
        # A successful transition answers 204 with nothing in it. Only the write calls do
        # this; a read that came back empty still falls through to the JSON error below.
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
        # A 4xx with a body is still Jira refusing; a 5xx is Jira failing partway, which
        # says nothing about whether the write landed.
        error = NotWritten if response.status_code < 500 else SourceError
        raise error(f"jira: {path} failed: {said}")
    return payload
