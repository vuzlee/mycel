"""Provider connectors: Jira, Gmail, Google Calendar."""

import httpx2

from mycel.core.exceptions import MycelError

#: One timeout for every Google API call, mail and calendar alike.
GOOGLE_TIMEOUT_SECONDS = 20.0


def google_client(token: str) -> httpx2.AsyncClient:
    """An HTTP client carrying one person's Google access token."""
    return httpx2.AsyncClient(
        timeout=GOOGLE_TIMEOUT_SECONDS, headers={"authorization": f"Bearer {token}"}
    )


class SourceError(MycelError):
    """A provider could not be reached, or answered with something unusable."""


class NotWritten(SourceError):
    """A write failed and certainly wrote nothing, so a retry is safe."""
