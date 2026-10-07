"""Encrypt and decrypt the refresh tokens this deployment keeps.

One key, two providers. A refresh token — Google's or Atlassian's — opens one person's
account until they revoke it, so the only thing Postgres ever holds is a ciphertext and a
database dump is not a list of accounts.

**`TOKEN_ENCRYPTION_KEY`, not `GOOGLE_TOKEN_KEY`.** The old name was right while the
calendar was the only thing stored; batch 060 adds Jira to the same column shape and the
same key, and a name that says Google about an Atlassian token is a name that sends the
next reader looking in the wrong file.

Rotating the key makes every stored token unreadable, which from the person's side is the
same situation as a revoked grant — so it is reported the same way, and reconnecting fixes
it. That reporting is each service's own: this module raises `TokenUnreadable` and lets
the caller phrase it for the provider it belongs to.
"""

from cryptography.fernet import Fernet, InvalidToken

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError


class TokenUnreadable(MycelError):
    """A stored token cannot be decrypted. The key was rotated, or the row is corrupt."""


def key_set(settings: Settings | None = None) -> bool:
    """Whether this deployment can store a token at all.

    A deployment with an OAuth client and no key would write a refresh token in the clear,
    so it counts as not configured rather than as configured badly.
    """
    return (settings or get_settings()).token_encryption_key is not None


def seal(refresh_token: str) -> str:
    """Encrypt a refresh token for storage. The only thing that writes those columns."""
    return _fernet().encrypt(refresh_token.encode()).decode()


def unseal(refresh_token_encrypted: str) -> str:
    """Decrypt a stored refresh token, or raise `TokenUnreadable`."""
    try:
        return _fernet().decrypt(refresh_token_encrypted.encode()).decode()
    except InvalidToken as exc:
        raise TokenUnreadable("the stored token cannot be read") from exc


def _fernet() -> Fernet:
    cfg = get_settings()
    if cfg.token_encryption_key is None:
        raise ConfigError("TOKEN_ENCRYPTION_KEY is not set; no account can be connected")
    try:
        return Fernet(cfg.token_encryption_key.get_secret_value())
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"TOKEN_ENCRYPTION_KEY is not a valid Fernet key: {exc}") from exc
