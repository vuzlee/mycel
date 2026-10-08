"""Parse a `'<tier>:<name>'` model spec (`local` or `cloud`)."""

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
    """Parse a model spec, or raise `ConfigError` naming what was wrong."""
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
