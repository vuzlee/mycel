"""An HTTP client on one person's Google token, shared by mail and calendar."""

import httpx2

#: One timeout for every Google API call, mail and calendar alike.
GOOGLE_TIMEOUT_SECONDS = 20.0


def google_client(token: str) -> httpx2.AsyncClient:
    """An HTTP client carrying one person's Google access token."""
    return httpx2.AsyncClient(
        timeout=GOOGLE_TIMEOUT_SECONDS, headers={"authorization": f"Bearer {token}"}
    )
