"""The non-secret half of configuration: YAML files under `config/`, read and merged.

Two halves, split by whether a value can be committed. `config.py` reads the environment
and holds everything secret or per-machine; this module reads files that live in git and
hold everything a reviewer should see in a diff — batch sizes, model choices, limits.

**YAML, not INI.** The configuration is nested (`agents.defaults.request_limit`) and typed:
INI would make every value a string and every nesting a naming convention.

**Layered, not duplicated.** `base.yaml` holds the real configuration; `dev.yaml` and
`prod.yaml` hold only what differs and are merged over it, key by key and at every depth.
A full copy per environment drifts — someone fixes a value in one file and the other keeps
the bug for months.

**Secrets are never here.** These files are committed. Where a value must stay private the
YAML names the variable that holds it (`api_key_env: GEMINI_API_KEY`) and `config.py`
reads it. That way the file still documents what a deployment needs without carrying it.
"""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError

# Repo root: this file is <root>/src/mycel/core/config_files.py.
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def load_config(env: str | None = None, config_dir: Path | None = None) -> dict[str, Any]:
    """Return `base.yaml` with `<env>.yaml` merged over it.

    `env` defaults to `MYCEL_ENV`, so a process configures itself from one variable.
    """
    directory = config_dir or CONFIG_DIR
    name = env or get_settings().mycel_env

    merged = _read(directory / "base.yaml", required=True)
    overlay = _read(directory / f"{name}.yaml", required=False)
    return _deep_merge(merged, overlay)


@lru_cache(maxsize=8)
def get_config(env: str | None = None) -> dict[str, Any]:
    """`load_config` for the process, read once.

    Cached because config is read on every agent build and the files never change while a
    process runs. Tests call `get_config.cache_clear()`.
    """
    return load_config(env)


def read_yaml(path: Path) -> dict[str, Any]:
    """Parse one YAML mapping that must exist — for files outside the layered merge, like
    `config/agents/<name>.yaml`."""
    return _read(path, required=True)


def _read(path: Path, *, required: bool) -> dict[str, Any]:
    """Parse one YAML file into a dict, or raise `ConfigError` saying which file is wrong.

    A missing overlay is fine — an environment that overrides nothing needs no file. A
    missing `base.yaml` is not: it means the process is running from somewhere that has no
    configuration at all, and continuing with defaults would hide that.
    """
    if not path.exists():
        if required:
            raise ConfigError(f"missing configuration file: {path}")
        return {}

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if loaded is None:  # an empty or all-comment file
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must contain a mapping, got {type(loaded).__name__}")
    return loaded


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Merge `overlay` into `base` at every depth, without mutating either.

    Nested rather than top-level merging is the whole point of the layering: `dev.yaml`
    setting `agents.defaults.request_limit` must keep the other `defaults` keys, not
    replace the block with a one-key dict.
    """
    result = dict(base)
    for key, value in overlay.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result
