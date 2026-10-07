"""Small stand-ins shared by several test files."""

import pytest

from mycel.core.config import get_settings
from mycel.sources import google_calendar


class FakeRedis:
    """Enough of the client for a state round or a draft: set with a TTL, and read-and-delete.

    The TTL is recorded rather than honoured — nothing here waits, and what a test wants to
    know is that an expiry was asked for at all.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


@pytest.fixture
def bangkok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not UTC, so a dropped `timeZone` or a host-zone reading shows up as a wrong hour."""
    monkeypatch.setenv("TIMEZONE", "Asia/Bangkok")
    get_settings.cache_clear()


@pytest.fixture
def google_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """The grant is `services/google_oauth.py`'s; here it is a string in a header."""

    async def _token(user_id: int) -> str:
        return "access-token"

    monkeypatch.setattr(google_calendar, "token_for", _token)
