"""Jira connector: read issues and worklogs, write as whoever's `Auth` is passed."""

from dataclasses import dataclass
from typing import Any

import httpx2

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.sources import NotWritten, SourceError

#: Issues per search page, Jira's ceiling for this endpoint.
PAGE = 100

HTTP_TIMEOUT_S = 30.0

#: Retries after a 429; `Retry-After` is honored, else exponential back-off.
RETRIES = 3

#: OAuth (3LO) tokens address a site only here, under its cloud id.
API_HOST = "https://api.atlassian.com"

#: Only the fields a work item is built from, to keep bronze small.
FIELDS = (
    "project",
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
    """Whose grant a call runs on: a short-lived access token and the site it opens."""

    access_token: str
    cloud_id: str


#: Jira's schema type for its Sprint field. The field's id differs per site; its type does not.
SPRINT_SCHEMA = "com.pyxis.greenhopper.jira:gh-sprint"


async def sprint_field(auth: Auth) -> str | None:
    """This site's Sprint field id, found by its schema, or None on a site without sprints."""
    fields = await _request(auth, "GET", "/field", None)
    for field in fields if isinstance(fields, list) else []:
        if isinstance(field, dict) and (field.get("schema") or {}).get("custom") == SPRINT_SCHEMA:
            return str(field["id"])
    return None


async def search_issues(auth: Auth, jql: str) -> list[dict[str, Any]]:
    """Every issue matching `jql`, paged; the sprint is copied to `fields["sprint"]`."""
    issues: list[dict[str, Any]] = []
    token: str | None = None
    sprint = await sprint_field(auth)

    while True:
        fields = [*FIELDS, sprint] if sprint else list(FIELDS)
        body: dict[str, Any] = {"jql": jql, "fields": fields, "maxResults": PAGE}
        if token:
            body["nextPageToken"] = token

        page = await _call(auth, "POST", "/search/jql", body)
        for issue in page.get("issues", []):
            if not isinstance(issue, dict):
                continue
            if sprint and isinstance(issue.get("fields"), dict):
                issue["fields"]["sprint"] = issue["fields"].get(sprint)
            issues.append(issue)

        token = page.get("nextPageToken")
        if not token:
            break

    log.info("fetched jira issues", extra={"count": len(issues), "jql": jql})
    return issues


async def issue_worklogs(auth: Auth, key: str) -> list[dict[str, Any]]:
    """Every logged entry on one issue; one request per issue."""
    payload = await _call(auth, "GET", f"/issue/{key}/worklog", None)
    return [w for w in payload.get("worklogs", []) if isinstance(w, dict)]


async def browsable_projects(auth: Auth) -> list[str]:
    """Keys of every project this grant may browse, per Jira's permission scheme."""
    keys: list[str] = []
    start = 0
    while True:
        page = await _call(
            auth, "GET", "/project/search", None, params={"startAt": str(start), "maxResults": "50"}
        )
        values = [v for v in page.get("values", []) if isinstance(v, dict)]
        keys.extend(str(v["key"]) for v in values if v.get("key"))
        if page.get("isLast", True) or not values:
            return keys
        start += len(values)


async def find_users(auth: Auth, query: str) -> list[dict[str, Any]]:
    """People whose name or address fuzzily matches, for assigning work."""
    # The only endpoint answering a bare array, hence `_request` vs `_call`.
    found = await _request(auth, "GET", "/user/search", None, params={"query": query})
    users = found if isinstance(found, list) else []
    return [u for u in users if isinstance(u, dict)]


async def add_comment(auth: Auth, key: str, text: str) -> dict[str, Any]:
    """Comment on one issue as the token's owner, in ADF as the v3 API requires."""
    _writable()
    created = await _call(auth, "POST", f"/issue/{key}/comment", {"body": _document(text)})
    log.info("commented on jira issue", extra={"key": key, "chars": len(text)})
    return created


async def transitions_for(auth: Auth, key: str) -> list[dict[str, Any]]:
    """The moves this issue can make now; ids are per workflow, so always read first."""
    payload = await _call(auth, "GET", f"/issue/{key}/transitions", None)
    return [t for t in payload.get("transitions", []) if isinstance(t, dict)]


async def transition(auth: Auth, key: str, to_status: str) -> None:
    """Move an issue to the named status, raising when the workflow cannot reach it."""
    _writable()
    move = find_transition(await transitions_for(auth, key), to_status)
    if move is None:
        raise NotWritten(f"jira: {key} cannot move to {to_status!r} from where it is")
    await _call(auth, "POST", f"/issue/{key}/transitions", {"transition": {"id": move["id"]}})
    log.info("transitioned jira issue", extra={"key": key, "to": to_status})


def target_names(moves: list[dict[str, Any]]) -> list[str]:
    """The status names these transitions lead to, as Jira spells them."""
    return [str(m.get("to", {}).get("name", "")) for m in moves]


def find_transition(moves: list[dict[str, Any]], to_status: str) -> dict[str, Any] | None:
    """The transition that reaches `to_status`, matched case-insensitively, or `None`."""
    wanted = to_status.strip().lower()
    for move, name in zip(moves, target_names(moves), strict=True):
        if name.lower() == wanted:
            return move
    return None


async def create_issue(
    auth: Auth,
    project: str,
    kind: str,
    summary: str,
    description: str | None = None,
    assignee_id: str | None = None,
    sprint_id: int | None = None,
) -> dict[str, Any]:
    """Create one issue; the sprint field is sent only when a sprint is given."""
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
        sprint = await sprint_field(auth)
        if sprint is None:
            raise NotWritten("jira: this site has no sprints to put the issue in")
        fields[sprint] = sprint_id

    created = await _call(auth, "POST", "/issue", {"fields": fields})
    log.info("created jira issue", extra={"key": created.get("key"), "project": project})
    return created


async def create_project(auth: Auth, key: str, name: str, lead_account_id: str) -> dict[str, Any]:
    """Create a team-managed project; behind its own switch, as it cannot be undone."""
    _writable()
    if not get_settings().jira_allow_create_project:
        raise NotWritten(
            "jira: creating a project is off — set JIRA_ALLOW_CREATE_PROJECT to turn it on"
        )
    body = {
        "key": key.upper(),
        "name": name,
        "projectTypeKey": "software",
        "projectTemplateKey": ("com.pyxis.greenhopper.jira:gh-simplified-agility-scrum"),
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
            # A connection never made cannot have written anything.
            raise NotWritten(f"jira: could not reach {url}: {exc}") from exc

        if response.status_code == 429 and attempt < RETRIES - 1:
            await _wait(response, attempt)
            continue
        return _checked(path, response)

    raise SourceError(f"jira: {path} unreachable after {RETRIES} attempts")


async def _wait(response: "httpx2.Response", attempt: int) -> None:
    """Honor `Retry-After` when Jira sends one, and back off when it does not."""
    import asyncio

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
