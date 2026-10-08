"""Committed YAML config under `config/`: `environments/base.yaml` with `<env>.yaml` over it."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from mycel import REPO_ROOT
from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError

CONFIG_DIR = REPO_ROOT / "config"

#: Subdirectories of `CONFIG_DIR`.
ENV_SUBDIR = "environments"
AGENTS_SUBDIR = "agents"
MCP_SUBDIR = "mcp"


def load_config(env: str | None = None, config_dir: Path | None = None) -> dict[str, Any]:
    """`environments/base.yaml` with `<env>.yaml` over it; `env` defaults to `MYCEL_ENV`."""
    directory = (config_dir or CONFIG_DIR) / ENV_SUBDIR
    name = env or get_settings().mycel_env

    merged = _read(directory / "base.yaml", required=True)
    overlay = _read(directory / f"{name}.yaml", required=False)
    return _deep_merge(merged, overlay)


@lru_cache(maxsize=8)
def get_config(env: str | None = None) -> dict[str, Any]:
    """Cached `load_config`; tests call `get_config.cache_clear()`."""
    return load_config(env)


def read_yaml(path: Path) -> dict[str, Any]:
    """Parse one YAML mapping that must exist."""
    return _read(path, required=True)


def _read(path: Path, *, required: bool) -> dict[str, Any]:
    """Parse one YAML mapping, or raise `ConfigError` naming the file."""
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
    """Merge `overlay` into `base` at every depth, without mutating either."""
    result = dict(base)
    for key, value in overlay.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result
