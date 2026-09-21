"""The YAML half of configuration: layered files merge at depth, bad files fail loudly, and
an agent's settings come out of them rather than out of its module."""

from pathlib import Path

import pytest

from mycel.agents.core.config import AgentSettings
from mycel.core.config_files import (
    AGENTS_SUBDIR,
    CONFIG_DIR,
    ENV_SUBDIR,
    get_config,
    load_config,
    read_yaml,
)
from mycel.core.exceptions import ConfigError


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A miniature `config/` tree: the environment layers, one agent."""
    (tmp_path / AGENTS_SUBDIR).mkdir()
    (tmp_path / ENV_SUBDIR).mkdir()
    (tmp_path / ENV_SUBDIR / "base.yaml").write_text(
        "etl:\n"
        "  batch_size: 500\n"
        "  workers: 4\n"
        "agents:\n"
        "  defaults:\n"
        "    model_spec: cloud:gemini-2.5-flash\n"
        "    request_limit: 12\n"
        "    tool_calls_limit: 20\n",
        encoding="utf-8",
    )
    (tmp_path / ENV_SUBDIR / "dev.yaml").write_text(
        "etl:\n  batch_size: 50\nagents:\n  defaults:\n    request_limit: 8\n",
        encoding="utf-8",
    )
    (tmp_path / AGENTS_SUBDIR / "analyst.yaml").write_text(
        "model_spec: cloud:claude-sonnet-5\ntool_calls_limit: 30\n", encoding="utf-8"
    )
    return tmp_path


class TestLayering:
    def test_the_overlay_wins(self, config_dir: Path) -> None:
        assert load_config("dev", config_dir)["etl"]["batch_size"] == 50

    def test_the_overlay_keeps_its_siblings(self, config_dir: Path) -> None:
        """The reason the merge is recursive: `dev.yaml` sets one key of `etl` and must
        not take the rest of the block with it."""
        assert load_config("dev", config_dir)["etl"]["workers"] == 4

    def test_it_merges_at_every_depth(self, config_dir: Path) -> None:
        """Two levels down, where a top-level merge would drop `model_spec` entirely."""
        defaults = load_config("dev", config_dir)["agents"]["defaults"]
        assert defaults["request_limit"] == 8
        assert defaults["model_spec"] == "cloud:gemini-2.5-flash"

    def test_an_environment_with_no_overlay_is_fine(self, config_dir: Path) -> None:
        """Not every environment differs from base, and inventing an empty file to say so
        is noise."""
        assert load_config("staging", config_dir)["etl"]["batch_size"] == 500


class TestBadFiles:
    def test_a_missing_base_is_an_error(self, tmp_path: Path) -> None:
        """Running with no configuration at all is a broken deployment, not a default."""
        with pytest.raises(ConfigError, match="missing configuration file"):
            load_config("dev", tmp_path)

    def test_malformed_yaml_names_the_file(self, config_dir: Path) -> None:
        (config_dir / ENV_SUBDIR / "dev.yaml").write_text("etl:\n  - [unclosed\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="dev.yaml"):
            load_config("dev", config_dir)

    def test_a_non_mapping_is_rejected(self, config_dir: Path) -> None:
        (config_dir / ENV_SUBDIR / "dev.yaml").write_text("- one\n- two\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="must contain a mapping"):
            load_config("dev", config_dir)

    def test_an_empty_overlay_is_not(self, config_dir: Path) -> None:
        """A file holding only comments parses to None, which means "override nothing"."""
        (config_dir / ENV_SUBDIR / "dev.yaml").write_text("# nothing yet\n", encoding="utf-8")
        assert load_config("dev", config_dir)["etl"]["batch_size"] == 500


class TestAgentSettings:
    def test_all_three_layers_show_up(self, config_dir: Path) -> None:
        cfg = AgentSettings.from_config("analyst", env="dev", config_dir=config_dir)
        assert cfg.model_spec == "cloud:claude-sonnet-5"  # the agent's own file
        assert cfg.request_limit == 8  # dev.yaml
        assert cfg.tool_calls_limit == 30  # the agent's file beating base.yaml
        assert cfg.temperature == 0.0  # the dataclass default, unset everywhere

    def test_an_agent_with_no_file_gets_the_defaults(self, config_dir: Path) -> None:
        cfg = AgentSettings.from_config("researcher", env="dev", config_dir=config_dir)
        assert cfg.model_spec == "cloud:gemini-2.5-flash"
        assert cfg.tool_calls_limit == 20

    def test_an_unknown_key_fails_with_the_real_names(self, config_dir: Path) -> None:
        """A misspelt setting must not be silently ignored — that leaves an agent running on
        a limit its YAML says it is not."""
        (config_dir / AGENTS_SUBDIR / "analyst.yaml").write_text(
            "tool_call_limit: 30\n", encoding="utf-8"
        )
        with pytest.raises(ConfigError, match="tool_call_limit"):
            AgentSettings.from_config("analyst", env="dev", config_dir=config_dir)


class TestTheRealConfigDir:
    """The files actually committed must load — otherwise every test above passes on a tree
    nobody ships."""

    def test_the_committed_config_loads(self) -> None:
        for env in ("dev", "prod"):
            assert load_config(env)["etl"]["batch_size"] > 0

    def test_the_analyst_file_is_valid(self) -> None:
        cfg = AgentSettings.from_config("analyst", env="prod")
        assert cfg.model_spec.startswith("cloud:")  # the shared default, not an override

    def test_every_agent_file_parses(self) -> None:
        for path in sorted((CONFIG_DIR / AGENTS_SUBDIR).glob("*.yaml")):
            assert read_yaml(path), f"{path} is empty"
            AgentSettings.from_config(path.stem, env="prod")

    def test_get_config_is_cached(self) -> None:
        get_config.cache_clear()
        assert get_config("dev") is get_config("dev")
