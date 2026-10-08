"""Settings source reading `config/environments/` YAML.

Precedence: class default < base.yaml < <env>.yaml < .env < environment.
"""

from typing import Any

from pydantic_settings import PydanticBaseSettingsSource

SETTINGS_KEY = "settings"

#: What `MYCEL_ENV` falls back to. Must match the field default in `Settings`.
DEFAULT_ENV = "dev"


def _env_name() -> str:
    """`MYCEL_ENV` from the environment or `.env`; never `get_settings()`, which would recurse."""
    import os
    from pathlib import Path

    if value := os.environ.get("MYCEL_ENV", "").strip():
        return value

    dotenv = Path(".env")
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            name, _, raw = line.partition("=")
            if name.strip() == "MYCEL_ENV" and (value := raw.strip().strip("\"'")):
                return value

    return DEFAULT_ENV


class EnvironmentFileSource(PydanticBaseSettingsSource):
    """`config/environments/*.yaml` as `Settings` values, keyed by field name (`log_level`)."""

    def __call__(self) -> dict[str, Any]:
        return self._load()

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        # Unused: `__call__` returns every field from one file read.
        return None, field_name, False

    def _load(self) -> dict[str, Any]:
        # Local import: config_files -> config -> this is a cycle at module scope.
        from mycel.core.config_files import load_config

        try:
            block = load_config(env=_env_name()).get(SETTINGS_KEY) or {}
        except Exception:
            # Settings is built before the logger exists; fall back to class defaults.
            return {}

        if not isinstance(block, dict):
            return {}
        return {str(k): v for k, v in block.items() if v is not None}
