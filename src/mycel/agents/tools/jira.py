"""Jira write tools, as the asker: draft and read back, then confirm. No principal writes nothing.

Lookups happen at draft time so the person agrees to exactly what is sent. A refused write
restores the draft; a timeout does not, since it may have landed.
"""

from dataclasses import dataclass
from typing import Any

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.core.guards import guard_repeat
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.redis import drafts
from mycel.services.jira_oauth import JiraAuthError, NotConnected, connected, token_for
from mycel.sources import NotWritten, SourceError, jira

log = get_logger(__name__)

CONNECT = (
    "No Jira account is connected. Open the account menu, choose Settings, and connect "
    "one — then ask again. Anything written to Jira carries the name of whoever connected, "
    "which is why there is no shared account to fall back on."
)

#: The write kinds the model picks from.
KINDS = ("comment", "move", "issue", "project")


def build_toolset() -> FunctionToolset[MycelDeps]:
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()
    toolset.add_function(_find_jira_user, name="find_jira_user")
    toolset.add_function(_draft_jira_write, name="draft_jira_write")
    toolset.add_function(_confirm_jira_write, name="confirm_jira_write")
    return toolset


async def _find_jira_user(ctx: RunContext[MycelDeps], name: str) -> str:
    """Find the people on this Jira site whose name or address matches.

    Use it before drafting anything that assigns work. Two people often share a first
    name; when more than one comes back, ask which one rather than picking.

    Args:
        name: Part of a name or an email address, as the person said it.
    """
    guard_repeat(ctx, "find_jira_user", threshold=ctx.deps.settings.repeat_threshold, name=name)
    auth = await _auth(ctx.deps)
    if auth is None:
        return CONNECT

    try:
        found = await jira.find_users(auth, name)
    except (SourceError, JiraAuthError) as exc:
        raise ToolFailed("find_jira_user", str(exc)) from exc

    people = [u for u in found if u.get("accountId")]
    if not people:
        return f"Nobody on this Jira site matches {name!r}."
    lines = [f"{len(people)} match(es). Columns: name | account_id | active"]
    lines += [
        f"{u.get('displayName', '(no name)')} | {u['accountId']} | {u.get('active', True)}"
        for u in people[:20]
    ]
    return "\n".join(lines)


async def _draft_jira_write(
    ctx: RunContext[MycelDeps],
    kind: str,
    issue_key: str | None = None,
    text: str | None = None,
    to_status: str | None = None,
    project: str | None = None,
    summary: str | None = None,
    issue_type: str = "Task",
    assignee_account_id: str | None = None,
    project_name: str | None = None,
) -> str:
    """Work out a change to Jira and read it back. **This writes nothing to Jira.**

    Show the person the sentence this returns, in full, and wait for them to agree.
    Only then call `confirm_jira_write` with the draft id. If they correct anything,
    draft again.

    Args:
        kind: What to do — "comment", "move", "issue" or "project".
        issue_key: Which issue, for "comment" and "move". For example PROJ-12.
        text: The comment, for "comment". The description, for "issue".
        to_status: The status to move to, for "move". Checked against the workflow
            before you are given a draft, so a move the workflow forbids is refused
            here rather than after they have said yes.
        project: The project key, for "issue" and "project".
        summary: The title, for "issue" and "project".
        issue_type: Task, Story, Bug or Epic. Task unless they said otherwise.
        assignee_account_id: Who to assign it to, for "issue". An account id from
            `find_jira_user`, never a name — a name is not something Jira can write.
        project_name: Ignored except for "project", where it is the project's name and
            `project` is its key.
    """
    guard_repeat(
        ctx,
        "draft_jira_write",
        threshold=ctx.deps.settings.repeat_threshold,
        kind=kind,
        issue_key=issue_key,
        summary=summary,
    )
    user_id = _whose(ctx.deps)
    if user_id is None:
        return CONNECT
    if kind not in KINDS:
        raise ModelRetry(f"kind must be one of {', '.join(KINDS)}.")

    auth = await _auth(ctx.deps)
    if auth is None:
        return CONNECT

    try:
        asked = Asked(
            issue_key=issue_key,
            text=text,
            to_status=to_status,
            project=project,
            summary=summary,
            issue_type=issue_type,
            assignee_account_id=assignee_account_id,
            project_name=project_name,
        )
        spelled, payload = await _resolve(auth, user_id, kind, asked)
    except (SourceError, JiraAuthError) as exc:
        raise ToolFailed("draft_jira_write", str(exc)) from exc

    draft = await drafts.put_jira(user_id, kind, spelled, payload)
    return (
        f"Nothing written yet. {spelled}\n"
        f"Read that back and ask whether it is right. To do it, call "
        f"confirm_jira_write with draft_id={draft.draft_id}."
    )


async def _confirm_jira_write(ctx: RunContext[MycelDeps], draft_id: str) -> str:
    """Carry out a drafted change. Call this only after the person has agreed to it.

    Args:
        draft_id: The id `draft_jira_write` returned for the change they agreed to.
    """
    user_id = _whose(ctx.deps)
    if user_id is None:
        return CONNECT

    draft = await drafts.take_jira(draft_id, user_id)
    if draft is None:
        # Not a retry: the draft is gone and no argument can fix that.
        return (
            "That draft has expired or was already done. Nothing was written. "
            "Draft it again if they still want it."
        )

    auth = await _auth(ctx.deps)
    if auth is None:
        return CONNECT

    try:
        done = await _apply(auth, draft)
    except NotWritten as exc:
        # Nothing landed: restore the draft, and name its id so the model retries it.
        await drafts.restore_jira(draft)
        raise ToolFailed(
            "confirm_jira_write",
            f"{exc}. Nothing was written and the draft is still here — say so, and "
            f"call confirm_jira_write with draft_id={draft.draft_id} to try again.",
        ) from exc
    except (SourceError, JiraAuthError) as exc:
        # May have landed: keep the draft spent so a retry cannot write twice.
        raise ToolFailed(
            "confirm_jira_write",
            f"{exc}. It is not known whether this was written — say so and tell them "
            f"to check Jira before trying again.",
        ) from exc

    log.info("jira write done", extra={"user_id": user_id, "kind": draft.kind})
    return done


def offered() -> bool:
    """Whether this deployment writes to Jira; when false the toolset is not offered."""
    from mycel.services.jira_oauth import configured

    return configured() and get_settings().jira_write_enabled


@dataclass(frozen=True, slots=True)
class Asked:
    """What the model passed to `draft_jira_write`, before anything is looked up."""

    issue_key: str | None
    text: str | None
    to_status: str | None
    project: str | None
    summary: str | None
    issue_type: str
    assignee_account_id: str | None
    project_name: str | None


async def _resolve(
    auth: jira.Auth, user_id: int, kind: str, asked: Asked
) -> tuple[str, dict[str, Any]]:
    """Resolve the model's arguments into the payload and its read-back sentence."""
    return await _RESOLVERS[kind](auth, user_id, asked)


async def _resolve_comment(auth: jira.Auth, user_id: int, a: Asked) -> tuple[str, dict[str, Any]]:
    key = _required(a.issue_key, "issue_key", "comment")
    body = _required(a.text, "text", "comment")
    return f"Comment on {key}: {body!r}", {"issue_key": key, "text": body}


async def _resolve_move(auth: jira.Auth, user_id: int, a: Asked) -> tuple[str, dict[str, Any]]:
    key = _required(a.issue_key, "issue_key", "move")
    wanted = _required(a.to_status, "to_status", "move").strip()
    # Checked before the person agrees; the allowed list tells the model what to use.
    moves = await jira.transitions_for(auth, key)
    if jira.find_transition(moves, wanted) is None:
        raise ModelRetry(
            f"{key} cannot move to {wanted!r} from where it is. It can move to: "
            f"{', '.join(jira.target_names(moves)) or '(nothing)'}."
        )
    return f"Move {key} to {wanted}", {"issue_key": key, "to_status": wanted}


async def _resolve_issue(auth: jira.Auth, user_id: int, a: Asked) -> tuple[str, dict[str, Any]]:
    proj = _required(a.project, "project", "issue").upper()
    title = _required(a.summary, "summary", "issue")
    who = "nobody"
    if a.assignee_account_id:
        # Read back by name: an id is not something a person can check.
        who = await _name_of(auth, a.assignee_account_id)
    spelled = f"Create a {a.issue_type} in {proj}: {title!r}, assigned to {who}" + (
        f" — {a.text!r}" if a.text else ""
    )
    return spelled, {
        "project": proj,
        "kind": a.issue_type,
        "summary": title,
        "description": a.text,
        "assignee_id": a.assignee_account_id,
    }


async def _resolve_project(auth: jira.Auth, user_id: int, a: Asked) -> tuple[str, dict[str, Any]]:
    key = _required(a.project, "project", "project").upper()
    name = _required(a.project_name or a.summary, "project_name", "project")
    # The lead is whoever consented, never someone searched for.
    row = await connected(user_id)
    if row is None:
        raise ModelRetry("No Jira account is connected, so there is nobody to lead a project.")
    return (
        f"Create a NEW PROJECT {key} named {name!r}, led by {row.display_name}. A project "
        f"cannot be deleted through this app, and on many Jira sites not through the API "
        f"at all — say so when you ask.",
        {"key": key, "name": name, "lead_account_id": row.account_id},
    )


_RESOLVERS = {
    "comment": _resolve_comment,
    "move": _resolve_move,
    "issue": _resolve_issue,
    "project": _resolve_project,
}


async def _apply(auth: jira.Auth, draft: drafts.JiraDraft) -> str:
    p = draft.payload
    if draft.kind == "comment":
        await jira.add_comment(auth, p["issue_key"], p["text"])
        return f"Commented on {p['issue_key']}, under your own name."

    if draft.kind == "move":
        await jira.transition(auth, p["issue_key"], p["to_status"])
        return f"{p['issue_key']} is now {p['to_status']}."

    if draft.kind == "issue":
        created = await jira.create_issue(
            auth,
            project=p["project"],
            kind=p["kind"],
            summary=p["summary"],
            description=p.get("description"),
            assignee_id=p.get("assignee_id"),
        )
        return f"Created {created.get('key', '(no key)')}: {p['summary']}."

    created = await jira.create_project(auth, p["key"], p["name"], p["lead_account_id"])
    return f"Created project {created.get('key', p['key'])}: {p['name']}."


async def _name_of(auth: jira.Auth, account_id: str) -> str:
    """The display name behind an account id, looked up fresh for the read-back."""
    for person in await jira.find_users(auth, account_id):
        if person.get("accountId") == account_id:
            return str(person.get("displayName") or account_id)
    return account_id


def _required(value: str | None, field: str, kind: str) -> str:
    if value is None or not value.strip():
        raise ModelRetry(f"{field} is needed to draft a {kind}.")
    return value.strip()


def _whose(deps: MycelDeps) -> int | None:
    return deps.principal.id if deps.principal else None


async def _auth(deps: MycelDeps) -> jira.Auth | None:
    """The asker's own grant, or `None` when they have not connected one."""
    user_id = _whose(deps)
    if user_id is None:
        return None
    try:
        token, cloud_id = await token_for(user_id)
    except NotConnected:
        return None
    return jira.Auth(access_token=token, cloud_id=cloud_id)
