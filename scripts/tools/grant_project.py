"""Give someone a project, from a shell. The first grant on a new deployment.

    uv run python scripts/tools/grant_project.py                     # who has what
    uv run python scripts/tools/grant_project.py someone@example.com MYC
    uv run python scripts/tools/grant_project.py someone@example.com MYC --revoke

`api/routes/members.py` is the everyday way in, and it has one rule: you may grant a
project you can read. That rule cannot bootstrap itself — on a database where nobody has
been granted anything, nobody can grant anything, and the whole of gold is unreadable by
everyone. This script is the way out of that, and the reason it is a shell command rather
than an endpoint is that it has no such rule and must not be reachable over HTTP.

Migration 0007 granted every account that existed at upgrade time every project that
existed with it, so an upgraded deployment already has people who can invite. A *fresh*
one does not: the first account registers into an empty `app.membership` and can read
nothing until this is run once.
"""

import asyncio
import sys

from mycel.infra.postgres.repositories.app import AppRepository
from mycel.infra.postgres.session import session_scope
from mycel.services.permission import grant, revoke


async def _show() -> int:
    """Every account and what it may read. The answer to 'is this a fresh database'."""
    async with session_scope() as session:
        repo = AppRepository(session)
        users = await repo.all_users()
        if not users:
            print("no accounts yet — register one first")
            return 0
        for user in users:
            projects = sorted(await repo.projects_for(user.id))
            print(f"{user.email:40} {', '.join(projects) or '(nothing)'}")
    return 0


async def _change(email: str, project: str, taking_back: bool) -> int:
    async with session_scope() as session:
        repo = AppRepository(session)
        user = await repo.user_by_email(email)
        if user is None:
            print(f"no account for {email}")
            return 1
        if taking_back:
            await revoke(session, user.id, project)
        else:
            await grant(session, user.id, project)
    did, to = ("revoked", "from") if taking_back else ("granted", "to")
    print(f"{did} {project} {to} {email}")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        return asyncio.run(_show())
    if len(args) != 2:
        print(__doc__)
        return 2
    email, project = args
    return asyncio.run(_change(email, project, "--revoke" in sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())
