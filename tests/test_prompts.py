"""Prompts live beside the agents but apart from them, so drift has to fail loudly."""

import pkgutil

import pytest

from mycel.agents import prompts
from mycel.agents.registry import AGENTS
from mycel.core.exceptions import ConfigError


class TestLoad:
    def test_every_registered_agent_has_a_prompt(self) -> None:
        """An agent whose prompt module was renamed starts with no instructions at all —
        and the model answers anyway, plausibly, off nothing."""
        for name in AGENTS:
            assert prompts.load(name)

    def test_a_missing_prompt_names_the_module(self) -> None:
        with pytest.raises(ConfigError, match="no prompt module"):
            prompts.load("no_such_agent")

    def test_prompts_and_agents_do_not_drift_apart(self) -> None:
        found = {m.name for m in pkgutil.iter_modules(prompts.__path__)}
        assert found == set(AGENTS)
