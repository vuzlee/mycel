"""Reading `config/environments/` as a settings source, under the environment.

`config.py` holds what must never reach git; this is how everything else gets into the
same `Settings` object without being a second way to ask the same question.

**One rule, and the order is the whole of it.** A value can arrive from four places, and
later entries win:

    class default  <  config/environments/base.yaml  <  <env>.yaml  <  .env  <  environment

The environment is last because `docker run -e LOG_LEVEL=DEBUG` has to work. A config file
that outranked it would make environment variables decorative, and the first person to
discover that would do so at three in the morning.

**Why not just read YAML in `config_files.py` and be done.** It already does, for agent
settings, and that is the point: a second reader would mean two ways to find out what
`SYNC_INTERVAL_SECONDS` is, which disagree the day somebody edits one. Here the file feeds
the same `Settings` everything already reads, so there is one answer.

**A missing or malformed file is not fatal here.** `config_files.load_config` raises on a
missing `base.yaml`, and it is right to — an agent cannot be built without its limits. But
`Settings` is constructed before anything else, including the logger, so an exception here
has nowhere to be reported. A deployment running on class defaults is wrong; a deployment
that cannot start and cannot say why is worse.
"""

from typing import Any

from pydantic_settings import PydanticBaseSettingsSource

#: The YAML key holding the flat settings block. Nested under one name rather than at the
#: top level, so `settings:` sits beside `agents:` and `etl:` instead of mixing with them.
SETTINGS_KEY = "settings"

#: What `MYCEL_ENV` falls back to. Must match the field default in `Settings`.
DEFAULT_ENV = "dev"


def _env_name() -> str:
    """Which overlay to read, from the environment and the `.env` file directly.

    NOT through `get_settings()`, and this is the one thing in the file that must not be
    tidied. `Settings()` builds this source, which would call `get_settings()`, which is
    itself mid-construction and whose `lru_cache` is still empty — so it would build a
    second `Settings` and the INNER one returns first, before any YAML was read. The
    symptom is a value that is present when you print it and None when the app asks for it,
    which took a `doctor` run to notice.

    Reading two plain files is less clever and cannot recurse.
    """
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
    """`config/environments/*.yaml` as values for `Settings`.

    Keys are read exactly as the field is named — `log_level`, not `LOG_LEVEL` — because
    YAML is not the environment and shouting in it reads as a mistake.
    """

    def __call__(self) -> dict[str, Any]:
        return self._load()

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        # Required by the base class; `__call__` returns everything at once instead, which
        # is one file read rather than one per field.
        return None, field_name, False

    def _load(self) -> dict[str, Any]:
        # Imported here, not at module scope: config_files imports config, and config
        # imports this. At module scope that is a cycle at interpreter start.
        from mycel.core.config_files import load_config

        try:
            block = load_config(env=_env_name()).get(SETTINGS_KEY) or {}
        except Exception:
            # See the module docstring: Settings is built before the logger exists, so
            # there is nowhere to report this. The class defaults are all usable, and
            # `stack.sh doctor` is what says the file was not read.
            return {}

        if not isinstance(block, dict):
            return {}
        return {str(k): v for k, v in block.items() if v is not None}
