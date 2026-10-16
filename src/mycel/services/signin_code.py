"""Sign in with a six-digit code sent by mail: the way in without a Google account."""

import hashlib
import secrets

from mycel.core.logging import get_logger
from mycel.infra import smtp
from mycel.infra.redis._kv import key
from mycel.infra.redis.client import get_client
from mycel.services.auth import EMAIL_SHAPE, AuthError, check_allowed, normalize

log = get_logger(__name__)

#: How long a code works.
CODE_TTL_SECONDS = 600

#: Wrong guesses one code survives before it is burned.
MAX_TRIES = 5

DIGITS = 6


def configured() -> bool:
    """Whether this deployment can mail a code at all."""
    return smtp.configured()


async def issue(email: str) -> str | None:
    """Make a code for `email` and remember its hash. None when that address may not sign in."""
    email = normalize(email)
    if not EMAIL_SHAPE.fullmatch(email):
        raise AuthError("that is not an email address")
    try:
        check_allowed(email)
    except AuthError:
        # Said the same way as success, so the endpoint cannot be used to map the allowlist.
        return None
    code = f"{secrets.randbelow(10**DIGITS):0{DIGITS}d}"
    client = await get_client()
    pipe = client.pipeline()
    pipe.set(_code_key(email), _digest(code), ex=CODE_TTL_SECONDS)
    pipe.delete(_tries_key(email))
    await pipe.execute()
    return code


async def send(email: str, code: str) -> None:
    """Best effort, after the response: a failure is logged, never shown."""
    minutes = CODE_TTL_SECONDS // 60
    try:
        await smtp.send(
            normalize(email),
            f"{code} is your Mycel sign-in code",
            f"Your sign-in code is {code}.\n\n"
            f"It works once and stops working in {minutes} minutes. "
            "If you did not ask for it, you can ignore this mail.",
        )
    except Exception:
        log.warning("sign-in code not sent", exc_info=True)


async def spend(email: str, code: str) -> str:
    """The normalized address if `code` is right; else `AuthError`. A right code works once."""
    email = normalize(email)
    client = await get_client()
    stored = await client.get(_code_key(email))
    if stored is None:
        raise AuthError("that code has expired; ask for a new one")

    tries = await client.incr(_tries_key(email))
    await client.expire(_tries_key(email), CODE_TTL_SECONDS)
    if tries > MAX_TRIES:
        await client.delete(_code_key(email))
        raise AuthError("too many wrong codes; ask for a new one")

    expected = stored.decode() if isinstance(stored, bytes) else str(stored)
    if not secrets.compare_digest(expected, _digest(code.strip())):
        raise AuthError("that code is not right")

    # GETDEL, not DEL: two requests racing with the same right code end with one winner.
    if await client.getdel(_code_key(email)) is None:
        raise AuthError("that code has expired; ask for a new one")
    await client.delete(_tries_key(email))
    return email


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _code_key(email: str) -> str:
    return key("signin", "code", email)


def _tries_key(email: str) -> str:
    return key("signin", "tries", email)
