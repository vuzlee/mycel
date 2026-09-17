"""Agent layer: an orchestrator coordinates, each agent specialises, tools are the
capabilities an agent can call.

  core/            the runtime — run loop wiring, budget, guards, errors
  agent/           the agents themselves: analyst, researcher, librarian
  orchestrator.py  coordination: split tasks, assign work, merge results
  registry.py      declares which agents and tools the orchestrator may use
  tools/           capabilities an agent can call: compute, web_search, rag_search

One job per agent keeps prompts short, lets evals score each one separately, and makes a
failure point at the exact agent that broke.
"""
