"""Coordinating agent: takes a report request, splits it into tasks, assigns them to
specialist agents, merges the results.

It does not analyse figures or write prose itself — it decides *what is needed* and hands
the work out. Independent tasks run in parallel; if one fails the report still comes out,
with the gap stated explicitly rather than invented.

Not called "manager" to avoid confusion with `managers/` — that one is the per-domain HTTP
entry point.
"""
