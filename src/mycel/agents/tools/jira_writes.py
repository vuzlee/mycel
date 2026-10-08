"""Turning a draft_jira_write call into a read-back and payload, and applying it."""

from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelRetry

from mycel.infra.redis import drafts
from mycel.services.jira_oauth import connected
from mycel.sources import jira


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


async def resolve(
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


async def apply(auth: jira.Auth, draft: drafts.JiraDraft) -> str:
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
