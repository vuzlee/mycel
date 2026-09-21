"""Queries: k-NN with metadata filters (source, time window, view permissions).

Filtering must happen **inside** Qdrant, not after top-k comes back: fetch 10 results, then
drop the ones the user may not see, and you might be left with 2. Permissions are a filter,
not a post-processing step.

Agents call this through a tool in `agents/tools/`, never by importing this module directly.
"""
