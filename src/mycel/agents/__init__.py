"""Agent layer: an orchestrator coordinates, each agent specialises, tools are the
capabilities an agent can call.

  core/            the runtime — run loop wiring, budget, guards, chips, errors
  agent/           the agents themselves: orchestrator, analyst, researcher, summariser
  prompts/         one system prompt per agent
  registry.py      declares which agents exist and builds their deps
  schemas.py       output types the world outside `agents/` names
  tools/           capabilities an agent can call: SQL, Jira, mail, calendar, web search

One job per agent keeps prompts short, lets evals score each one separately, and makes a
failure point at the exact agent that broke.
"""
