"""Shared foundation for `agents/` alone: the agent runtime, everything with no business
logic in it.

Same shape as `mycel/core/` but one level narrower — that one is the foundation for the
whole system.

Kept apart from the agents one level up (`agent/`, `orchestrator.py`) because the
two change at different rates: how runs are wired barely changes, while prompts change
constantly. Mixed together, every prompt edit means re-reading runtime code.

  base.py          what every agent declares, and the one place they are wired
  config.py        model choice, generation parameters, loop limits
  model_builder.py spec '<tier>:<model_name>' -> a client ready to call
  deps.py          what a single run carries: job_id, budget, settings
  guards.py        stop a model repeating itself
  runner.py        `run` starts a job's first agent; `delegate` lets one agent call another
  exceptions.py    the framework's errors

**Built on pydantic-ai.** The agent loop, message types, streaming and usage accounting are
the framework's; this package is only the part that is specific to Mycel. That is why there
is no `agent.py`, no `schemas.py` and no `streaming/` — `Agent`, `ModelMessage` and
`run_stream_events()` replace them outright. Mycel code imports `RunContext`, `ModelRetry`
and `UsageLimits` directly rather than wrapping them; a pass-through layer would only add
bugs on top of theirs.

Never imports back up into the agents or `tools/` — dependencies point one way.
"""
