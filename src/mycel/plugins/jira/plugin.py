"""Jira as a plugin."""

from typing import TYPE_CHECKING

from mycel.core.config import Settings, get_settings
from mycel.core.principal import Principal
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.session import session_scope
from mycel.plugins.base import Role, Status
from mycel.plugins.jira import access, oauth
from mycel.services import enqueue
from mycel.services.permission import readable_projects

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from mycel.agents.core.deps import MycelDeps


class Jira:
    key = "jira"
    name = "Jira"
    offers = "The projects Jira lets you browse. Writes only after you agree."
    syncs = True

    def configured(self, settings: Settings | None = None) -> bool:
        return oauth.configured(settings)

    async def consent_url(self, user_id: int) -> str:
        return await oauth.consent_url(user_id)

    async def connect(self, state: str, code: str, user_id: int) -> None:
        """Connect, then read access and queue a sync so the board fills without the timer."""
        await oauth.connect(state, code, user_id)
        await access.refresh(user_id)
        await enqueue.queue(enqueue.sync_job(self.key))

    async def status(self, user: Principal) -> Status:
        if not self.configured():
            return Status(configured=False)
        row = await oauth.connected(user.id)
        if row is None:
            return Status(configured=True)
        projects = sorted(await readable_projects(user))
        note = (
            f"Reads {', '.join(projects)}"
            if projects
            else "Jira lets this account browse no project"
        )
        return Status(configured=True, who=row.display_name, since=row.connected_at, note=note)

    async def disconnect(self, user_id: int) -> bool:
        return await oauth.disconnect(user_id)

    async def sync(self) -> None:
        from mycel.plugins.jira.sync import sync_jira

        await sync_jira()

    async def probe(self) -> str:
        """How many people have Jira connected, and how the last sync went."""
        async with session_scope() as session:
            repo = AccountRepository(session)
            people = len(await repo.jira_connected_users())
            state = await repo.sync_state()
        last = (
            state.last_success_at.strftime("%Y-%m-%d %H:%M") if state.last_success_at else "never"
        )
        if state.last_error and (
            state.last_success_at is None
            or (state.last_failure_at and state.last_failure_at > state.last_success_at)
        ):
            raise RuntimeError(f"last sync failed: {state.last_error[:160]} (last success {last})")
        writes = "writes on" if get_settings().jira_write_enabled else "writes off"
        return f"{people} people connected; last sync {last}; {writes}"

    def toolsets(self, role: Role) -> "list[AbstractToolset[MycelDeps]]":
        """Live reads and writes for the analyst, when this deployment writes to Jira."""
        if role != "analyst":
            return []
        from mycel.plugins.jira import tools

        return [tools.build_toolset()] if tools.offered() else []


PLUGIN = Jira()
