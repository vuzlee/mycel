"""Toolsets for the MCP servers declared in `config/mcp/servers.yaml`; nothing connects at build."""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_ai.mcp import MCPToolset

from mycel.core.config_files import CONFIG_DIR, MCP_SUBDIR, read_yaml
from mycel.core.exceptions import ConfigError
from mycel.core.logging import get_logger

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from mycel.agents.core.deps import MycelDeps

log = get_logger(__name__)

_TRANSPORTS = ("http", "stdio")


def build_toolsets(
    names: list[str] | None = None, config_path: Path | None = None
) -> "list[AbstractToolset[MycelDeps]]":
    """The named MCP toolsets, or every enabled server; an undeclared name raises."""
    servers = _load(config_path or CONFIG_DIR / MCP_SUBDIR / "servers.yaml")

    if names is not None:
        unknown = sorted(set(names) - set(servers))
        if unknown:
            known = ", ".join(sorted(servers)) or "(none)"
            raise ConfigError(f"unknown mcp server(s): {', '.join(unknown)}; declared: {known}")
        wanted = {name: servers[name] for name in names}
    else:
        wanted = {n: s for n, s in servers.items() if s.get("enabled", True)}

    return [_toolset(name, spec) for name, spec in wanted.items()]


def _load(path: Path) -> dict[str, dict[str, Any]]:
    """Read the server map; a missing file means no servers."""
    if not path.exists():
        return {}

    servers = read_yaml(path).get("servers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f"{path}: 'servers' must be a mapping, got {type(servers).__name__}")
    for name, spec in servers.items():
        # YAML 1.1 reads bare `on`/`yes`/`no` keys as booleans.
        if not isinstance(name, str):
            raise ConfigError(
                f"{path}: server name {name!r} is not a string — YAML read it as "
                f"{type(name).__name__}. Quote it."
            )
        if not isinstance(spec, dict):
            raise ConfigError(f"{path}: server {name!r} must be a mapping")
    return servers


def _toolset(name: str, spec: dict[str, Any]) -> "AbstractToolset[MycelDeps]":
    transport = spec.get("transport", "http")
    if transport not in _TRANSPORTS:
        raise ConfigError(
            f"mcp server {name!r}: unknown transport {transport!r}; known: "
            + ", ".join(_TRANSPORTS)
        )

    if transport == "stdio":
        return _stdio(name, spec)
    return _http(name, spec)


def _http(name: str, spec: dict[str, Any]) -> "AbstractToolset[MycelDeps]":
    from fastmcp.client import Client
    from fastmcp.client.transports import StreamableHttpTransport

    url = spec.get("url")
    if not url:
        raise ConfigError(f"mcp server {name!r}: transport 'http' needs a 'url'")

    headers = dict(spec.get("headers", {}))
    token = _token(name, spec)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    log.debug("mcp server declared", extra={"server": name, "transport": "http", "url": url})
    return MCPToolset(Client(StreamableHttpTransport(url, headers=headers)), id=name)


def _stdio(name: str, spec: dict[str, Any]) -> "AbstractToolset[MycelDeps]":
    from fastmcp.client import Client
    from fastmcp.client.transports import StdioTransport

    command = spec.get("command")
    if not command:
        raise ConfigError(f"mcp server {name!r}: transport 'stdio' needs a 'command'")

    env = dict(spec.get("env", {}))
    token = _token(name, spec)
    if token is not None:
        # The variable the *server* expects, which is rarely the one holding it here.
        env[str(spec.get("token_arg", "MCP_TOKEN"))] = token

    log.debug("mcp server declared", extra={"server": name, "transport": "stdio"})
    transport = StdioTransport(command, list(spec.get("args", [])), env=env or None)
    return MCPToolset(Client(transport), id=name)


def _token(name: str, spec: dict[str, Any]) -> str | None:
    """The secret named by `token_env`; raise if it is named but unset."""
    variable = spec.get("token_env")
    if not variable:
        return None

    token = os.environ.get(str(variable))
    if not token:
        raise ConfigError(
            f"mcp server {name!r} needs {variable}, which is unset. Set it, or drop "
            f"'token_env' if the server takes no auth."
        )
    return token
