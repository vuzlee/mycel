"""MCP: tools this system calls on other people's servers.

Client only. Hosting mycel's own tools over MCP is deferred — nothing outside the process
wants to call them yet, so a server would be another thing to keep running in exchange for
nothing. The shape is ready for it when that changes: `tools/compute.py::build_toolset()`
is a single definition that an in-process agent and a future `mcp/server.py` would both
read, so there is no second copy to drift.

Placed here rather than under `agents/core/`, because an MCP server is an edge of the
system — the same kind of thing as the database or the queue — not an internal detail of
how an agent loop works.
"""
