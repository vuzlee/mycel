"""Encrypt and decrypt the refresh tokens this deployment keeps."""

from cryptography.fernet import Fernet, InvalidToken

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError


class TokenUnreadable(MycelError):
    """A stored token cannot be decrypted. The key was rotated, or the row is corrupt."""


def key_set(settings: Settings | None = None) -> bool:
    """Whether this deployment can store a token at all."""
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
