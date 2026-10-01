"""Model specs parse, round-trip, and fail loudly when malformed."""

import pytest

from mycel.core.exceptions import ConfigError
from mycel.llm.router import ModelSpec, Tier, resolve


def test_parses_both_tiers() -> None:
    assert resolve("cloud:gemini-3.8-flash") == ModelSpec(Tier.CLOUD, "gemini-3.8-flash")
    assert resolve("local:qwen3-4b") == ModelSpec(Tier.LOCAL, "qwen3-4b")


def test_round_trips() -> None:
    """str(spec) must be re-parseable, so a spec can be logged and replayed."""
    for text in ("cloud:gemini-3.8-flash", "local:qwen3-4b"):
        assert str(resolve(text)) == text


def test_model_name_may_contain_a_colon() -> None:
    """Only the first colon separates; HuggingFace-style names keep the rest."""
    assert resolve("local:org/model:v2").name == "org/model:v2"


def test_tier_is_case_insensitive_and_trimmed() -> None:
    assert resolve(" CLOUD : gemini-3.8-flash ").tier is Tier.CLOUD


@pytest.mark.parametrize(
    "bad",
    [
        "gemini-3.8-flash",  # no tier at all
        "gpu:qwen3-4b",  # tier that does not exist
        "cloud:",  # tier but no model
        "cloud:   ",
        "",
    ],
)
def test_bad_specs_raise_config_error(bad: str) -> None:
    """A silent default here is a surprise bill, or data sent to the wrong place."""
    with pytest.raises(ConfigError):
        resolve(bad)


def test_error_names_the_offending_spec() -> None:
    """The message has to be actionable without opening the source."""
    with pytest.raises(ConfigError, match="gpu"):
        resolve("gpu:qwen3-4b")


def test_spec_is_hashable() -> None:
    """Frozen, so it can key a cache of built models."""
    assert len({resolve("cloud:x"), resolve("cloud:x")}) == 1
