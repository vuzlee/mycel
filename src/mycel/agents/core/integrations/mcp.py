"""MCP client: mount tools from an external server without writing a wrapper.

Connect to the servers declared in config, read their tool list, turn them into tools the
agent can call. MCP tools travel the same path as internal ones — same logging, same
tracing, same guard counting calls.

External tools are someone else's code: they need a timeout and a cap on result size.
"""
