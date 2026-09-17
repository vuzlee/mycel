"""Agent framework configuration: model choice, generation parameters, loop limits.

Holds only knobs *every* agent needs. An agent's own knobs live with that agent.

Models are declared as `'<tier>:<model_name>'` (`local:qwen3-4b`, `cloud:claude-sonnet-5`);
`llm/router.py` translates the tier into a real backend. That way switching models is an
environment variable, not a code change.

A plain frozen dataclass, not `BaseSettings`: none of these are secret, so they belong in
the YAML under `config/` where a reviewer sees them change in a diff. `from_config()` reads
those files — `agents.defaults` from the environment's layer, then `config/agents/<name>.yaml`
over it — so an agent's model and limits are configuration, not a literal in its module.

The defaults on the fields below are the fallback for a process with no `config/` at all: a
test, a script, an import on a machine that only checked out `src/`. They are deliberately
conservative, because the cost of a wrong guess is a real API bill.

The limits here are the runaway guard. pydantic-ai enforces them itself once `run`
turns them into `UsageLimits`; nothing in Mycel counts loops by hand.
"""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from mycel.core.config_files import CONFIG_DIR, get_config, load_config, read_yaml
from mycel.core.exceptions import ConfigError


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """What one agent needs to be built and run safely."""

    model_spec: str = "cloud:gemini-3.8-flash"

    # Zero by default: a report that changes between identical runs cannot be reviewed.
    # Gemini 3 and later removed the sampling parameters, so `model_builder.py` drops this
    # rather than sending a value the API rejects.
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_s: float = 60.0

    tool_retries: int = 3

    # Handed to pydantic-ai as `UsageLimits`. `tool_calls_limit` is checked *before* a tool
    # runs, so it is a real circuit breaker rather than a post-mortem.
    request_limit: int = 12
    tool_calls_limit: int = 20
    total_tokens_limit: int | None = None

    # How many identical (tool, arguments) calls to tolerate before `guards.py` steps in.
    repeat_threshold: int = 2

    @classmethod
    def from_config(
        cls, name: str, env: str | None = None, config_dir: Path | None = None
    ) -> "AgentSettings":
        """Build one agent's settings from `config/`.

        Three layers, each overriding the last: this class's own defaults, the environment's
        `agents.defaults` block, and `config/agents/<name>.yaml`. An agent with no file of
        its own is not an error — it wants the shared defaults, which is the common case.
        """
        directory = config_dir or CONFIG_DIR
        # The cache is keyed by environment alone, so a caller pointing at its own
        # directory (a test, mostly) reads from disk rather than poisoning it.
        cfg = get_config(env) if config_dir is None else load_config(env, directory)

        merged: dict[str, Any] = {}
        merged.update(_mapping(cfg.get("agents", {}).get("defaults", {}), "agents.defaults"))

        own = directory / "agents" / f"{name}.yaml"
        if own.exists():
            merged.update(_mapping(read_yaml(own), str(own)))

        return cls(**_checked(merged, name))


def _checked(values: dict[str, Any], name: str) -> dict[str, Any]:
    """Reject keys that are not fields, naming the ones that are.

    Silently ignoring an unknown key is how a misspelt `tool_call_limit` leaves an agent on
    the default limit for months while its YAML says otherwise.
    """
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
