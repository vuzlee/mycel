"""Writing to Jira as the person asking, in two steps: read it back, then write it.

Same shape as `tools/calendar.py`, and for the same reason. The difference is what is at
stake in a wrong one — a calendar event is deleted in a second, and a Jira event carries a
name that cannot be corrected afterwards.

**Everything here runs on the asker's own consent.** `deps.principal` is who that is, and
`None` reads nothing and writes nothing: a run with no principal is told to connect an
account, exactly as `tools/query.py` scopes it to no rows. A forgotten principal must never
borrow somebody else's name.

**One draft tool, then one confirm tool.** `draft_jira_write` resolves everything a write
needs — an assignee's name into an account id, a status into a transition the workflow
actually allows — and returns a sentence with full names in it. Nothing reaches Jira. The
person reads that sentence, says yes, and `confirm_jira_write` spends the draft. A draft
lives ten minutes and belongs to one person; see `infra/redis/drafts.py`.

**Resolving at draft time rather than at confirm time is the point.** If the account id
were looked up after the yes, the person would have agreed to "Nam" and the system would
have written to whichever Nam it found later — which is precisely the mistake the read-back
exists to catch.

**Not connecting an account is not a failure.** A person who has never consented gets a
sentence telling them where to, and the turn answers whatever else was asked. The same
shape `tools/calendar.py` and `tools/delegate.py` already use.

**A write that is refused gives the draft back; one that times out does not.** The person
has already read the change and agreed to it, so a refused connection should not cost them
the whole round — `sources.NotWritten` means nothing can have landed, and the draft returns
under its own id for a second yes. A timeout is different: the request may have arrived and
only the answer been lost, so the draft stays spent and the person is told to check Jira.
Retrying there would post the same comment twice.

**No delete, of anything**, and `create_project` appears only where the deployment armed
it. A tool the model cannot see is a tool it cannot be talked into using — which matters
more here than anywhere else, because a project created by mistake is often not removable
over the API at all.
"""

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

#: What the four writes are called where a person reads them. The model picks one of these
#: strings, so they are the vocabulary of the tool rather than an internal enum.
KINDS = ("comment", "move", "issue", "project")

#: Jira's own default issue types on a scrum template. Anything else a site has defined
#: still works — this is what the refusal names when the model sends nothing usable.
KNOWN_TYPES = ("Task", "Story", "Bug", "Epic")


def build_toolset() -> FunctionToolset[MycelDeps]:
    """Writing to Jira, as a toolset an agent can be given."""
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="find_jira_user")
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

    @toolset.tool(name="draft_jira_write")
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
            spelled, payload = await _resolve(
                auth,
                user_id,
                kind,
                issue_key=issue_key,
                text=text,
                to_status=to_status,
                project=project,
                summary=summary,
                issue_type=issue_type,
                assignee_account_id=assignee_account_id,
                project_name=project_name,
            )
        except (SourceError, JiraAuthError) as exc:
            raise ToolFailed("draft_jira_write", str(exc)) from exc

        draft = await drafts.put_jira(user_id, kind, spelled, payload)
        return (
            f"Nothing written yet. {spelled}\n"
            f"Read that back and ask whether it is right. To do it, call "
            f"confirm_jira_write with draft_id={draft.draft_id}."
        )

    @toolset.tool(name="confirm_jira_write")
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
            # Not a retry: there is no argument the model can fix, and the draft it holds
            # is gone. Drafting again is the way forward and the sentence says so.
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
            # Certain that nothing landed, so the draft can come back under its own id and
            # a second yes is a retry. The id has to be IN THE SENTENCE: without it the
            # model drafts afresh, which is the whole round the person already did.
            await drafts.restore_jira(draft)
            raise ToolFailed(
                "confirm_jira_write",
                f"{exc}. Nothing was written and the draft is still here — say so, and "
                f"call confirm_jira_write with draft_id={draft.draft_id} to try again.",
            ) from exc
        except (SourceError, JiraAuthError) as exc:
            # A timeout or a 5xx. The request may have landed and only the answer been
            # lost, so the draft stays spent: offering a retry here offers to write twice.
            raise ToolFailed(
                "confirm_jira_write",
                f"{exc}. It is not known whether this was written — say so and tell them "
                f"to check Jira before trying again.",
            ) from exc

        log.info("jira write done", extra={"user_id": user_id, "kind": draft.kind})
        return done

    return toolset


def offered() -> bool:
    """Whether this deployment writes to Jira at all.

    The toolset is not given to an agent when this is false. A tool that refuses every
    call costs a turn to discover that, and on a free tier of twenty requests a day that
    turn is worth not spending — the same argument that keeps `rag_search` behind
    `QDRANT_URL`.
    """
    from mycel.services.jira_oauth import configured

    return configured() and get_settings().jira_write_enabled


async def _resolve(
    auth: jira.Auth,
    user_id: int,
    kind: str,
    *,
    issue_key: str | None,
    text: str | None,
    to_status: str | None,
    project: str | None,
    summary: str | None,
    issue_type: str,
    assignee_account_id: str | None,
    project_name: str | None,
) -> tuple[str, dict[str, Any]]:
    """Turn what the model said into what will be written, and a sentence saying so.

    Every lookup happens here rather than after the person agrees, so what they read is
    exactly what will be sent. A missing argument raises `ModelRetry`, which the model can
    act on; a lookup that fails raises `SourceError`, which it cannot.
    """
    if kind == "comment":
        key = _required(issue_key, "issue_key", "comment")
        body = _required(text, "text", "comment")
        return f"Comment on {key}: {body!r}", {"issue_key": key, "text": body}

    if kind == "move":
        key = _required(issue_key, "issue_key", "move")
        wanted = _required(to_status, "to_status", "move").strip()
        # Checked now, not at confirm time: a move the workflow forbids should be refused
        # before somebody agrees to it, and the list of what is allowed is what tells the
        # model which name to use instead.
        moves = await jira.transitions_for(auth, key)
        allowed = [str(m.get("to", {}).get("name", "")) for m in moves]
        if not any(name.lower() == wanted.lower() for name in allowed):
            raise ModelRetry(
                f"{key} cannot move to {wanted!r} from where it is. It can move to: "
                f"{', '.join(allowed) or '(nothing)'}."
            )
        return f"Move {key} to {wanted}", {"issue_key": key, "to_status": wanted}

    if kind == "issue":
        proj = _required(project, "project", "issue").upper()
        title = _required(summary, "summary", "issue")
        who = "nobody"
        if assignee_account_id:
            # By name, never by id. The id is what Jira needs and the name is what a person
            # can check, and a draft that reads back an id catches nothing.
            who = await _name_of(auth, assignee_account_id)
        spelled = f"Create a {issue_type} in {proj}: {title!r}, assigned to {who}" + (
            f" — {text!r}" if text else ""
        )
        return spelled, {
            "project": proj,
            "kind": issue_type,
            "summary": title,
            "description": text,
            "assignee_id": assignee_account_id,
        }

    key = _required(project, "project", "project").upper()
    name = _required(project_name or summary, "project_name", "project")
    # The lead is whoever consented, read from their own row rather than searched for: a
    # project must have one, and anyone else would be handed responsibility for a project
    # they did not create.
    row = await connected(user_id)
    if row is None:
        raise ModelRetry("No Jira account is connected, so there is nobody to lead a project.")
    return (
        f"Create a NEW PROJECT {key} named {name!r}, led by {row.display_name}. A project "
        f"cannot be deleted through this app, and on many Jira sites not through the API "
        f"at all — say so when you ask.",
        {"key": key, "name": name, "lead_account_id": row.account_id},
    )


async def _apply(auth: jira.Auth, draft: drafts.JiraDraft) -> str:
    """Do the thing that was agreed to, and say what came of it."""
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
    """The display name behind an account id, for the sentence a person reads.

    Looked up every time rather than cached. A name is the whole of what the read-back is
    worth, so a stale one is worse than an extra call — and the call is one request on a
    draft a person is about to spend a minute reading.
    """
    for person in await jira.find_users(auth, account_id):
        if person.get("accountId") == account_id:
            return str(person.get("displayName") or account_id)
    return account_id


def _required(value: str | None, field: str, kind: str) -> str:
    """One argument the model left out, named so it can fill it in."""
    if value is None or not value.strip():
        raise ModelRetry(f"{field} is needed to draft a {kind}.")
    return value.strip()


def _whose(deps: MycelDeps) -> int | None:
    """Whose Jira this run may touch, or `None` for a run nobody is behind."""
    return deps.principal.id if deps.principal else None


async def _auth(deps: MycelDeps) -> jira.Auth | None:
    """The asker's own grant, or `None` when they have not connected one.

    `None` rather than an exception: not having connected is a sentence to show somebody,
    and raising would end a job over the half of it that is still answerable.
    """
    user_id = _whose(deps)
    if user_id is None:
        return None
    try:
        token, cloud_id = await token_for(user_id)
    except NotConnected:
        return None
    return jira.Auth(access_token=token, cloud_id=cloud_id)
