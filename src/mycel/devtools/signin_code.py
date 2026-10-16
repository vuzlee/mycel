"""Print a sign-in code for an address, so scripts can sign in without a mailbox.

    uv run python -m mycel.devtools.signin_code someone@example.com

Refuses outside `mycel_env=dev`: a code printed to a terminal is a door left open.
"""

import asyncio
import sys

from mycel.core.config import get_settings
from mycel.infra.redis.client import close_clients
from mycel.services import signin_code


async def _issue(email: str) -> str | None:
    try:
        return await signin_code.issue(email)
    finally:
        await close_clients()


def main(argv: list[str]) -> int:
    if get_settings().mycel_env != "dev":
        print("refused: only on a dev machine (MYCEL_ENV=dev)", file=sys.stderr)
        return 2
    if len(argv) != 1:
        print("usage: python -m mycel.devtools.signin_code <email>", file=sys.stderr)
        return 2
    code = asyncio.run(_issue(argv[0]))
    if code is None:
        print("refused: that address may not sign in here", file=sys.stderr)
        return 1
    print(code)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
