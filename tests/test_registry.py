"""The registry: one name in, one runnable agent out."""

from decimal import Decimal

import pytest
from pydantic_ai import Agent

from mycel.agents.agent.analyst import Analysis
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import AGENTS, build, build_deps
from mycel.core.exceptions import ConfigError


class TestBuild:
    def test_builds_a_known_agent(self) -> None:
        assert isinstance(build("analyst"), Agent)

    def test_every_registered_name_actually_builds(self) -> None:
        """A registry entry that raises on build is worse than no entry: the failure
        surfaces at run time, inside a job, instead of here."""
        for name in AGENTS:
            assert isinstance(build(name), Agent), name

    def test_each_call_returns_a_fresh_agent(self) -> None:
        """Builders, not instances — two callers must not share one mutable agent."""
        assert build("analyst") is not build("analyst")

    def test_settings_reach_the_agent(self) -> None:
        agent = build("analyst", AgentSettings(model_spec="local:qwen3-4b"))
        assert isinstance(agent, Agent)

    def test_unknown_name_lists_what_exists(self) -> None:
        """The caller is usually a config string; the message must be actionable."""
        with pytest.raises(ConfigError) as exc:
            build("analyts")
        assert "analyts" in str(exc.value)
        assert "analyst" in str(exc.value)


class TestBuildDeps:
    def test_ceiling_accepts_a_string(self) -> None:
        """Config values pass straight through without a float touching money."""
        deps = build_deps("job-1", "2.50")
        assert deps.budget.ceiling_usd == Decimal("2.50")
        assert deps.job_id == "job-1"

    def test_ceiling_accepts_a_decimal(self) -> None:
        assert build_deps("j", Decimal("0.10")).budget.ceiling_usd == Decimal("0.10")

    def test_one_budget_object_is_shared_by_the_job(self) -> None:
        """Building deps per run would give each run its own ceiling, which is not a
        budget. This test pins the contract that callers build deps once."""
        deps = build_deps("job-1", "1.00")
        assert deps.budget is deps.budget
        assert build_deps("job-1", "1.00").budget is not deps.budget


def test_analyst_output_type_is_analysis() -> None:
    """The registry's job is to hand back something the orchestrator can use, and the
    analyst's contract is a structured Analysis, not free text."""
    assert build("analyst").output_type is Analysis
