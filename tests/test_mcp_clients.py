"""Building MCP toolsets from `config/mcp.yaml`.

Nothing here connects to anything: `MCPToolset` opens its transport when an agent runs, so
construction is exactly the part that can be tested offline — and it is the part that
carries the decisions worth protecting. Which servers get loaded is prompt input, and a
token read from the wrong place is a secret in the wrong file.
"""

from pathlib import Path
from typing import Any

import pytest

from mycel.core.exceptions import ConfigError
from mycel.mcp import clients


def _config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "mcp.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class TestWhichServersLoad:
    def test_a_missing_file_means_no_servers(self, tmp_path: Path) -> None:
        """Calling nobody's MCP server is an ordinary deployment, not a broken one."""
        assert clients.build_toolsets(config_path=tmp_path / "absent.yaml") == []

    def test_a_disabled_server_is_not_loaded(self, tmp_path: Path) -> None:
        path = _config(
            tmp_path,
            "servers:\n"
            "  live: {url: https://a.example/mcp}\n"
            "  dark: {url: https://b.example/mcp, enabled: false}\n",
        )
        toolsets = clients.build_toolsets(config_path=path)
        assert [t.id for t in toolsets] == ["live"]

    def test_an_agent_can_ask_for_a_subset(self, tmp_path: Path) -> None:
        """An agent wanting one server must not inherit every other one in the file."""
        path = _config(
            tmp_path,
            "servers:\n  a: {url: https://a.example/mcp}\n  b: {url: https://b.example/mcp}\n",
        )
        toolsets = clients.build_toolsets(["b"], config_path=path)
        assert [t.id for t in toolsets] == ["b"]

    def test_asking_for_an_undeclared_server_raises(self, tmp_path: Path) -> None:
        """Returning fewer toolsets than asked for is a capability silently missing —
        which is the failure this module is arranged against."""
        path = _config(tmp_path, "servers:\n  a: {url: https://a.example/mcp}\n")
        with pytest.raises(ConfigError, match="typo"):
            clients.build_toolsets(["typo"], config_path=path)


class TestSecrets:
    def test_the_token_is_read_from_the_named_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The config names the variable; the value never appears in a committed file."""
        monkeypatch.setenv("ACME_MCP_TOKEN", "s3cret")
        path = _config(
            tmp_path,
            "servers:\n  acme: {url: https://a.example/mcp, token_env: ACME_MCP_TOKEN}\n",
        )
        captured: dict[str, Any] = {}

        from fastmcp.client import transports

        original = transports.StreamableHttpTransport.__init__

        def _spy(self: Any, url: Any, headers: Any = None, **kw: Any) -> None:
            captured["headers"] = headers
            original(self, url, headers=headers, **kw)

        monkeypatch.setattr(transports.StreamableHttpTransport, "__init__", _spy)
        clients.build_toolsets(config_path=path)

        assert captured["headers"]["Authorization"] == "Bearer s3cret"

    def test_an_unset_token_fails_at_build_rather_than_as_a_401(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The file asked for auth, so continuing without it turns a forgotten variable
        into a confusing 401 several layers from the deployment that forgot it."""
        monkeypatch.delenv("ACME_MCP_TOKEN", raising=False)
        path = _config(
            tmp_path,
            "servers:\n  acme: {url: https://a.example/mcp, token_env: ACME_MCP_TOKEN}\n",
        )
        with pytest.raises(ConfigError, match="ACME_MCP_TOKEN"):
            clients.build_toolsets(config_path=path)


class TestBadConfig:
    def test_an_unknown_transport_names_the_known_ones(self, tmp_path: Path) -> None:
        path = _config(tmp_path, "servers:\n  a: {transport: carrier-pigeon}\n")
        with pytest.raises(ConfigError, match="http, stdio"):
            clients.build_toolsets(config_path=path)

    def test_http_without_a_url_says_so(self, tmp_path: Path) -> None:
        path = _config(tmp_path, "servers:\n  a: {transport: http}\n")
        with pytest.raises(ConfigError, match="url"):
            clients.build_toolsets(config_path=path)

    def test_stdio_without_a_command_says_so(self, tmp_path: Path) -> None:
        path = _config(tmp_path, "servers:\n  a: {transport: stdio}\n")
        with pytest.raises(ConfigError, match="command"):
            clients.build_toolsets(config_path=path)

    def test_a_name_yaml_turned_into_a_boolean_is_rejected(self, tmp_path: Path) -> None:
        """A server named `on` arrives as the key `True` and matches nothing an agent asks
        for. Saying so is cheaper than the hunt."""
        path = _config(tmp_path, "servers:\n  on: {url: https://a.example/mcp}\n")
        with pytest.raises(ConfigError, match="Quote it"):
            clients.build_toolsets(config_path=path)

    def test_a_server_that_is_not_a_mapping_is_rejected(self, tmp_path: Path) -> None:
        path = _config(tmp_path, "servers:\n  a: https://a.example/mcp\n")
        with pytest.raises(ConfigError, match="must be a mapping"):
            clients.build_toolsets(config_path=path)


class TestTheCommittedFile:
    def test_the_repo_s_own_config_builds(self) -> None:
        """`config/mcp.yaml` declares nothing yet, and that must stay loadable rather than
        becoming a file nobody parses until the first server is added."""
        assert clients.build_toolsets() == []
