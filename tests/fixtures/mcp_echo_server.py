"""A tiny MCP server, run as a child process, so the MCP client can be tested for real.

`mcp/clients.py` builds toolsets but never opens a connection, so every test of it stops
at construction. That leaves the half that matters unproven: whether a toolset this repo
builds can actually speak to a server, list its tools, and carry arguments across the
process boundary.

**Why a server in the repo rather than somebody else's.** The question under test is
whether *our client* is correct. A third-party server answers a different question and
answers it unreliably — a new release of it turns into a red test here, and a test that
goes red for reasons outside the repo is a test people learn to ignore. This one is
pinned by being checked in.

It is deliberately trivial, and must stay that way: two tools, no state, no I/O beyond
the sandbox directory next to this file. It is not a product and does not belong under
`src/`.

Run directly to speak MCP over stdin/stdout:

    uv run python tests/fixtures/mcp_echo_server.py
"""

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
    # `name` arrives from a model, so it is untrusted input: `../../.env` is a perfectly
    # ordinary string. Resolve first, then insist the result is still inside the sandbox —
    # checking the name for ".." instead would miss symlinks and absolute paths.
    target = (SANDBOX / f"{name}.txt").resolve()
    if not target.is_relative_to(SANDBOX.resolve()):
        raise ValueError(f"{name!r} is outside the sandbox")
    if not target.exists():
        raise ValueError(f"no note named {name!r}")
    return target.read_text(encoding="utf-8")


if __name__ == "__main__":
    server.run()
