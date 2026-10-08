"""Agent settings shared by every agent: model, generation parameters, loop limits.

Field defaults are the fallback when `config/` is absent; `from_config()` layers the YAML over them.
"""

from collections.abc import Iterable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from mycel.core.config_files import (
    AGENTS_SUBDIR,
    CONFIG_DIR,
    get_config,
    load_config,
    read_yaml,
)
from mycel.core.exceptions import ConfigError


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """What one agent needs to be built and run safely."""

    model_spec: str = "cloud:claude-sonnet-5"

    # Zero so identical runs give reviewable, identical reports.
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_s: float = 60.0

    tool_retries: int = 3

    # HTTP-level retries in the provider SDK (not a replay of the agent loop); 0 disables.
    transient_retries: int = 2

    # Passed to pydantic-ai as `UsageLimits`.
    request_limit: int = 12
    tool_calls_limit: int = 20
    total_tokens_limit: int | None = None

    # Identical (tool, arguments) calls tolerated before `guards.py` steps in.
    repeat_threshold: int = 2

    # Servers from `config/mcp/servers.yaml` this agent may call.
    mcp_servers: tuple[str, ...] = ()

    # Models tried in order when `model_spec` is unavailable (see `model_builder.py`).
    fallback_specs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Freeze list-valued fields (YAML lists) into tuples."""
        for name in ("mcp_servers", "fallback_specs"):
            value = getattr(self, name)
            if isinstance(value, tuple):
                continue
            if isinstance(value, str) or not isinstance(value, Iterable):
                raise ConfigError(f"{name} must be a list, got {value!r}")
            object.__setattr__(self, name, tuple(value))

    @classmethod
    def from_config(
        cls, name: str, env: str | None = None, config_dir: Path | None = None
    ) -> "AgentSettings":
        """Class defaults < env `agents.defaults` < `config/agents/<name>.yaml` (optional)."""
        directory = config_dir or CONFIG_DIR
        # The cache is keyed by env alone, so a custom directory bypasses it.
        cfg = get_config(env) if config_dir is None else load_config(env, directory)

        merged: dict[str, Any] = {}
        merged.update(_mapping(cfg.get("agents", {}).get("defaults", {}), "agents.defaults"))

        own = directory / AGENTS_SUBDIR / f"{name}.yaml"
        if own.exists():
            merged.update(_mapping(read_yaml(own), str(own)))

        return cls(**_checked(merged, name))


def _checked(values: dict[str, Any], name: str) -> dict[str, Any]:
    """Reject keys that are not fields, naming the ones that are."""
    known = {f.name for f in fields(AgentSettings)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ConfigError(
            f"unknown agent setting(s) for {name!r}: {', '.join(unknown)}; "
            f"known settings: {', '.join(sorted(known))}"
        )
    return values


def _mapping(value: object, where: str) -> dict[str, Any]:
    """Insist a config block is a mapping, saying where the bad one is."""
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping, got {type(value).__name__}")
    return dict(value)
