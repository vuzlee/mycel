"""Google as a plugin."""

from typing import TYPE_CHECKING

from mycel.core.config import Settings
from mycel.core.principal import Principal
from mycel.plugins.base import Role, Status
from mycel.plugins.google import oauth

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from mycel.agents.core.deps import MycelDeps


class Google:
    key = "google"
    name = "Google"
    offers = "Your own calendar and mail. Mail is read-only; nothing is deleted."

    def configured(self, settings: Settings | None = None) -> bool:
        return oauth.configured(settings)

    async def consent_url(self, user_id: int) -> str:
        return await oauth.consent_url(user_id)

    async def connect(self, state: str, code: str, user_id: int) -> None:
        await oauth.connect(state, code, user_id)

    async def status(self, user: Principal) -> Status:
        if not self.configured():
            return Status(configured=False)
        row = await oauth.connected(user.id)
        if row is None:
            return Status(configured=True)
        return Status(configured=True, who=row.email, since=row.connected_at)

    async def disconnect(self, user_id: int) -> bool:
        return await oauth.disconnect(user_id)

    def toolsets(self, role: Role) -> "list[AbstractToolset[MycelDeps]]":
        """Calendar and mail for the researcher, only when someone could connect them."""
        if role != "researcher" or not self.configured():
            return []
        from mycel.plugins.google import calendar, mail

        return [mail.build_toolset(), calendar.build_toolset()]


PLUGIN = Google()
