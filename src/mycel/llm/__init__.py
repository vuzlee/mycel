"""LLM layer: pick a model (local/cloud), and stop runs that would exceed the cost ceiling.

  router.py   parse a '<tier>:<model_name>' spec and say which backend it means
  budget.py   per-job cost ceiling, accumulated across every run in the job
  cache.py    repeated prompts do not call out again — not built yet

Much smaller than it was. Calling the provider, counting tokens and counting usage are
pydantic-ai's job now (`Model`, `RunUsage`), so `client.py`, `tokens.py`, `usage.py` and
`providers/` are gone. What is left is the part that is Mycel's own policy: which tier a
call belongs to, and when a job has spent enough.

The one place a provider SDK is imported is `agents/core/model_builder.py`, which turns the
spec this layer parses into a client.
"""
