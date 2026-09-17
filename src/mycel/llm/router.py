"""Pick the backend for each LLM call.

Boundary:
  local  — high-volume work, short output, or sensitive data that should not leave
           the machine. Classification, entity extraction, relevance scoring,
           per-record summaries.
  cloud  — final reasoning: synthesising multiple sources, writing reports,
           decisions that need long context.

Every LLM call elsewhere goes through here; never import a provider SDK directly. There is
exactly one documented exception, `agents/core/model_builder.py`, which turns the spec this
module parses into a real client. An absolute rule with a silent exception rots, so the
exception is named here.

A model is written `'<tier>:<name>'` — `local:qwen3-4b`, `cloud:claude-sonnet-5`. Switching
model is then an environment variable, not a code change, and the tier is visible at the
call site rather than buried in configuration.
"""

from dataclasses import dataclass
from enum import StrEnum

from mycel.core.exceptions import ConfigError

SEPARATOR = ":"


class Tier(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A parsed `'<tier>:<name>'`. `name` is whatever the backend calls the model."""

    tier: Tier
    name: str

    def __str__(self) -> str:
        return f"{self.tier.value}{SEPARATOR}{self.name}"


def resolve(spec: str) -> ModelSpec:
    """Parse a model spec, or raise `ConfigError` naming what was wrong.

    Fails loudly: a bad spec caught here is a startup error, while one that silently
    defaults to a tier becomes a surprise bill or a leak of sensitive data to a cloud
    provider.
    """
    tier_name, separator, model_name = spec.partition(SEPARATOR)

    if not separator:
        raise ConfigError(
            f"model spec {spec!r} has no tier: write '<tier>:<name>', "
            f"one of {', '.join(t.value for t in Tier)}"
        )

    try:
        tier = Tier(tier_name.strip().lower())
    except ValueError:
        raise ConfigError(
            f"unknown tier {tier_name!r} in model spec {spec!r}: "
            f"expected one of {', '.join(t.value for t in Tier)}"
        ) from None

    if not model_name.strip():
        raise ConfigError(f"model spec {spec!r} names a tier but no model")

    return ModelSpec(tier=tier, name=model_name.strip())
