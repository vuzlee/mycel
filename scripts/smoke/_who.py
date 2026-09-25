"""Who a smoke script runs as.

Deps built without a principal read nothing from gold — that is the rule batch 055 put in,
and it is what makes a forgotten argument fail closed instead of open. A script that wants
real work data therefore has to say whose data it is, which is this:

    SMOKE_USER=someone@example.com uv run python scripts/smoke/try_analyst.py

Left unset the script still runs and the tools come back empty, which is the honest result
rather than a crash: the run itself is what is being smoke-tested.
"""

import asyncio
import os

from mycel.infra.postgres.repositories.app import AppRepository
from mycel.infra.postgres.session import session_scope
from mycel.services.auth import Principal


def whoami() -> Principal | None:
    """The account named by `SMOKE_USER`, or None."""
    email = os.environ.get("SMOKE_USER", "").strip()
    if not email:
        print("SMOKE_USER unset — running as nobody, so gold reads as empty\n")
        return None
    return asyncio.run(_lookup(email))


async def _lookup(email: str) -> Principal | None:
    async with session_scope() as session:
        user = await AppRepository(session).user_by_email(email)
    if user is None:
        print(f"no account for {email} — running as nobody\n")
        return None
    return Principal(id=user.id, email=user.email)
