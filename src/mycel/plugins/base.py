"""What core asks of every connector plugin."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mycel.core.config import Settings
from mycel.core.principal import Principal


@dataclass(frozen=True)
class Status:
    """What one person has attached, for the Connections panel."""

    configured: bool
    who: str | None = None
    since: datetime | None = None
    note: str | None = None


class Plugin(Protocol):
    """One provider: its consent round, what a person has attached, and how to drop it."""

    key: str
    name: str
    #: One line shown before connecting: what connecting opens.
    offers: str

    def configured(self, settings: Settings | None = None) -> bool: ...

    async def consent_url(self, user_id: int) -> str: ...

    async def connect(self, state: str, code: str, user_id: int) -> None: ...

    async def status(self, user: Principal) -> Status: ...

    async def disconnect(self, user_id: int) -> bool: ...
