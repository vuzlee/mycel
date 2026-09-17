"""System prompts, one module per agent, each exporting `INSTRUCTIONS`.

Kept out of the agent modules because the two change at different rates and for different
reasons: a prompt is edited constantly, often by someone tuning behaviour rather than
writing code, while the schema and toolsets beside it barely move. Separated, a prompt
change is a one-file diff a reviewer can read as a behaviour change — and `evals/` can be
gated on this directory alone.

`<name>.py` matches `config/agents/<name>.yaml` and the registry key, so an agent's name
remains the one thing that locates everything about it.
"""

from importlib import import_module

from mycel.core.exceptions import ConfigError


def load(name: str) -> str:
    """The system prompt for one agent, or `ConfigError` saying which module is missing."""
    try:
        module = import_module(f"{__name__}.{name}")
    except ModuleNotFoundError:
        raise ConfigError(f"no prompt module {__name__}.{name}") from None

    instructions: str = getattr(module, "INSTRUCTIONS", "")
    if not instructions.strip():
        raise ConfigError(f"{__name__}.{name} has no non-empty INSTRUCTIONS")
    return instructions
