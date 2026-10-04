"""The syncer's Jira grant, for a one-off script run by a person at a shell.

Since batch 060 there is no deployment-wide Jira token to pick up out of `.env` — every
call runs on somebody's consent, and for anything with nobody signed in that somebody is
the syncer. A script is exactly that case, so it borrows the same grant the scheduler uses
rather than inventing a second way in.

Synchronous on purpose. These scripts are short, linear and run by hand; the one async
thing they need is the token, so it is fetched once here and the rest stays plain `httpx`.

Imported as a bare module rather than from a package: `scripts/tools/` is a directory of
commands, not an importable package, and `uv run python scripts/tools/x.py` puts that
directory first on the path. The leading underscore is what says it is not one of the
commands.
"""

import asyncio

from mycel.services.jira_oauth import NotConnected, syncer_token


def jira_grant() -> tuple[str, dict[str, str]]:
    """`(base_url, headers)` for the syncer's own site, ready to pass to `httpx`.

    Exits with a sentence rather than a traceback when nobody has connected: that is the
    expected state on a fresh deployment, and the fix is a click in Settings.
    """
    try:
        token, cloud_id, _ = asyncio.run(syncer_token())
    except NotConnected as exc:
        raise SystemExit(str(exc)) from exc
    return (
        f"https://api.atlassian.com/ex/jira/{cloud_id}",
        {"authorization": f"Bearer {token}", "accept": "application/json"},
    )
