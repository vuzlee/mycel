"""Jira write tools, as the asker: draft and read back, then confirm. No principal writes nothing.

Lookups happen at draft time so the person agrees to exactly what is sent. A refused write
restores the draft; a timeout does not, since it may have landed.
"""

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.core.guards import guard_repeat
from mycel.agents.tools.jira_writes import JiraWriteRequest, apply, resolve
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.redis import drafts
from mycel.services.jira_oauth import JiraAuthError, NotConnected, token_for
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
    guard_repeat(ctx, "find_jira_user", name=name)
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
        kind=kind,
        issue_key=issue_key,
        summary=summary,
    )
    user_id = ctx.deps.user_id
    if user_id is None:
        return CONNECT
    if kind not in KINDS:
        raise ModelRetry(f"kind must be one of {', '.join(KINDS)}.")

    auth = await _auth(ctx.deps)
    if auth is None:
        return CONNECT

    try:
        asked = JiraWriteRequest(
            issue_key=issue_key,
            text=text,
            to_status=to_status,
            project=project,
            summary=summary,
            issue_type=issue_type,
            assignee_account_id=assignee_account_id,
            project_name=project_name,
        )
        spelled, payload = await resolve(auth, user_id, kind, asked)
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
    user_id = ctx.deps.user_id
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
        done = await apply(auth, draft)
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


async def _auth(deps: MycelDeps) -> jira.Auth | None:
    """The asker's own grant, or `None` when they have not connected one."""
    user_id = deps.user_id
    if user_id is None:
        return None
    try:
        token, cloud_id = await token_for(user_id)
    except NotConnected:
        return None
    return jira.Auth(access_token=token, cloud_id=cloud_id)
