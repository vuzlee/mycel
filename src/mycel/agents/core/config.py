"""Agent framework configuration: model choice, generation parameters, loop limits.

Holds only knobs *every* agent needs. An agent's own knobs live with that agent.

Models are declared as `'<tier>:<model_name>'` (`local:qwen3-4b`, `cloud:claude-sonnet-5`);
`llm/router.py` translates the tier into a real backend. That way switching models is an
environment variable, not a code change.

A plain frozen dataclass, not `BaseSettings`: these are per-agent choices a developer makes
in code, not per-deployment configuration. Where one *should* come from the environment,
`registry.py` reads `Settings` and passes it in — one place doing the env reading.

The limits here are the runaway guard. pydantic-ai enforces them itself once `run_agent`
turns them into `UsageLimits`; nothing in Mycel counts loops by hand.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """What one agent needs to be built and run safely."""

    model_spec: str = "cloud:claude-sonnet-5"

    # Generation. Temperature 0 by default: these agents report figures, and a report that
    # changes between identical runs cannot be reviewed.
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_s: float = 60.0

    # How many times a tool may answer with `ModelRetry` before the run fails.
    tool_retries: int = 3

    # Runaway limits, handed to pydantic-ai as `UsageLimits`. `tool_calls_limit` is checked
    # *before* a tool runs, so it is a real circuit breaker rather than a post-mortem.
    request_limit: int = 12
    tool_calls_limit: int = 20
    total_tokens_limit: int | None = None

    # How many identical (tool, arguments) calls to tolerate before `guards.py` steps in.
    repeat_threshold: int = 2
