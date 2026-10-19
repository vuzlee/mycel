"""Jira as a plugin."""

from mycel.core.config import Settings
from mycel.core.principal import Principal
from mycel.plugins.base import Status
from mycel.plugins.jira import oauth
from mycel.services import access, enqueue
from mycel.services.permission import readable_projects


class Jira:
    key = "jira"
    name = "Jira"
    offers = "The projects Jira lets you browse. Writes only after you agree."

    def configured(self, settings: Settings | None = None) -> bool:
        return oauth.configured(settings)

    async def consent_url(self, user_id: int) -> str:
        return await oauth.consent_url(user_id)

    async def connect(self, state: str, code: str, user_id: int) -> None:
        """Connect, then read access and queue a sync so the board fills without the timer."""
        await oauth.connect(state, code, user_id)
        await access.refresh(user_id)
        await enqueue.queue(enqueue.sync_job())

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


PLUGIN = Jira()
