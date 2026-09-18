"""Build toolsets for the MCP servers named in `config/mcp.yaml`.

**Declared servers only, never discovery.** An MCP tool arrives carrying a name and a
description written by whoever runs that server, and both go straight into the model's
prompt. That makes a tool list an input to the prompt, and a tool list fetched from
wherever a registry happens to point is an input nobody reviewed. So a server is used
because it is written down in a file that lives in git, and for no other reason.

**Secrets stay in the environment.** The YAML names the variable holding a token
(`token_env: SLACK_MCP_TOKEN`), never the token, so the file documents what a deployment
needs without carrying it — the same split as the rest of `config/`.

**Nothing connects at build time.** `MCPToolset` opens its connection when the agent that
holds it runs, so listing a server that is down costs an unreachable tool during a run
rather than a process that will not start. That is deliberate: a report that loses one
tool is still a report, and the failure surfaces where a run can record it as a gap.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_ai.mcp import MCPToolset

from mycel.core.config_files import CONFIG_DIR, read_yaml
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
    """The MCP toolsets an agent asked for, or every enabled server.

    `names` is how an agent picks a subset: the researcher wanting one company's server
    should not also inherit whatever else the file lists. Naming a server that is not in
    the file raises rather than returning fewer toolsets than asked for — a silently
    missing capability is the failure mode this whole module is arranged against.
    """
    servers = _load(config_path or CONFIG_DIR / "mcp.yaml")

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
    """Read the file, or treat its absence as "no servers".

    A deployment that calls nobody's MCP server is an ordinary deployment, not a broken
    one, so a missing file is empty rather than an error.
    """
    if not path.exists():
        return {}

    servers = read_yaml(path).get("servers", {})
    if not isinstance(servers, dict):
        raise ConfigError(f"{path}: 'servers' must be a mapping, got {type(servers).__name__}")
    for name, spec in servers.items():
        # YAML 1.1 reads bare `on`, `off`, `yes` and `no` as booleans, so a server innocently
        # named `on` arrives as the key `True` and never matches anything an agent asks for.
        # Quoting it in the file fixes it; saying so is cheaper than the hunt.
        if not isinstance(name, str):
            raise ConfigError(
                f"{path}: server name {name!r} is not a string — YAML read it as "
                f"{type(name).__name__}. Quote it."
            )
        if not isinstance(spec, dict):
            raise ConfigError(f"{path}: server {name!r} must be a mapping")
    return servers


def _toolset(name: str, spec: dict[str, Any]) -> "AbstractToolset[MycelDeps]":
    """One server's toolset, built from its config block."""
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
    """A server reached over streamable HTTP, the usual case for a hosted one."""
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
    """A server run as a child process — a local tool, not a hosted service."""
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
    """Read the secret the config *names*, insisting it is actually set.

    An empty token is not treated as "no auth": the file asked for one, so continuing
    unauthenticated would turn a missing variable into a confusing 401 at run time,
    several layers away from the deployment that forgot it.
    """
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
