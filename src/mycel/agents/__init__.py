"""Agent layer: an orchestrator coordinates, each agent specialises, tools are the
capabilities an agent can call.

  core/            the runtime — agent loop, streaming, trace/budget hooks, MCP
  orchestrator.py  coordination: split tasks, assign work, merge results
  analyst.py       analyses figures
  writer.py        writes prose
  reviewer.py      cross-checks against sources
  registry.py      declares which agents and tools the orchestrator may use
  tools/           capabilities an agent can call: query_gold, chart, compute
  prompts/         prompts kept out of the code

One job per agent keeps prompts short, lets evals score each one separately, and makes a
failure point at the exact agent that broke.
"""
