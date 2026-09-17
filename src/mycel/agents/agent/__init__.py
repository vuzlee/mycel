"""The agents themselves: one file per specialist, each a prompt and an output schema.

  analyst.py     analyses figures
  researcher.py  searches the web
  librarian.py   searches the knowledge base

Kept apart from the machinery one level up (`core/`, `tools/`, `registry.py`) because the
two change at different rates: a prompt is edited constantly, how a run is wired almost
never. Mixed together, every prompt edit means re-reading runtime code.

`orchestrator.py` stays outside this package. It coordinates specialists rather than being
one, and a registry that listed it alongside them would invite an agent to delegate to the
thing that called it.
"""
