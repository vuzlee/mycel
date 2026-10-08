"""A tiny MCP server, run as a child process, so the MCP client can be tested for real."""

from pathlib import Path

from mcp.server.mcpserver import MCPServer

#: The only directory this server will read. Everything outside it is refused.
SANDBOX = Path(__file__).parent / "mcp_sandbox"

server = MCPServer("mycel-echo")


@server.tool()
def echo(text: str) -> str:
    """Return the text you were given, unchanged."""
    return text


@server.tool()
def read_note(name: str) -> str:
    """Read one note from the sandbox directory by name, without its extension."""
    # `name` arrives from a model, so it is untrusted input.
    target = (SANDBOX / f"{name}.txt").resolve()
    if not target.is_relative_to(SANDBOX.resolve()):
        raise ValueError(f"{name!r} is outside the sandbox")
    if not target.exists():
        raise ValueError(f"no note named {name!r}")
    return target.read_text(encoding="utf-8")


if __name__ == "__main__":
    server.run()
