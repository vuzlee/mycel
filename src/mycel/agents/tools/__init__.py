"""Tools: the capabilities an agent can call.

  compute.py        percentages, growth, basic statistics
  web_search.py     search the open web
  rag_search.py     search the knowledge base via storage/vectors/

Each module owns its tools end to end and exports a `build_toolset()`; an agent lists the
toolsets it wants and writes no wrappers of its own. That is what makes a tool reusable:
the second agent to need one adds a line rather than copying code.

**Two error conventions, and picking the wrong one is expensive.** `compute.py` raises
`ModelRetry` because its failures are argument failures — the model can fix them by calling
again with different numbers. A tool that does I/O cannot: when a quota runs out or Qdrant is
down, re-prompting sends the model round the same loop until `max_retries` turns it into a run
error. Those raise `ToolFailed` instead.
"""
