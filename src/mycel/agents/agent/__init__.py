"""The agents themselves: one file per specialist, each a prompt and an output schema.

  analyst.py       analyses figures
  orchestrator.py  splits a request across the specialists
  researcher.py    searches the web
  librarian.py     searches the knowledge base

Kept apart from the machinery one level up (`core/`, `tools/`, `registry.py`) because the
two change at different rates: a prompt is edited constantly, how a run is wired almost
never. Mixed together, every prompt edit means re-reading runtime code.

`orchestrator.py` is here with the rest: coordinating other agents makes it a different
*kind* of agent, not a different kind of thing. What stops a specialist delegating back to
it is `registry.py`'s `_DECLARED`, which is an actual check rather than a directory
boundary anyone can step over by writing one import.

An agent module holds an agent and nothing else — its tools are in `tools/`, its prompt in
`prompts/`, and any output schema the world outside `agents/` names is in `schemas.py`.
"""
