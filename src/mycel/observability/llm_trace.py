"""Attach LLM-specific attributes to spans, following the conventions Langfuse reads.

One model call is one child span; input, output, model, tokens and cost live on it. A
question is therefore a tree: HTTP -> domain -> queue -> worker -> orchestrator ->
each agent -> each model call. When an answer gets a number wrong, it can be traced back to
the exact call that produced it.

**pydantic-ai already emits most of this.** `Agent.instrument_all()`, called from
`observability/tracing.py`, produces a span per agent run and per model call carrying the
GenAI semantic-convention attributes — model, tokens, cost. So this module is not the
source of those spans, and there is no hook here that every run must remember to call.

What is left for this file is the part upstream cannot know: Mycel's own attributes
(`job_id`, budget remaining, which tier the router picked) and any Langfuse-specific
naming that the GenAI conventions do not cover. It is docstring-only until something
needs one of those.

The tree is still only whole if `queue/context.py` bridges the process boundary — a
worker that starts a fresh trace leaves the request half of the story unlinked, and
nothing raises an error when it happens.
"""
