"""Connectors to individual providers: Slack, Gmail, Confluence...

One module per provider, all with the same interface: take the time window to sync, return
raw records, write them down to `raw`. No cleaning, no normalising — that is `etl/`'s job.

Adding a source = adding a file here, with no changes to existing code. Per-source
configuration (endpoint, scopes, rate limits) lives in `config/sources/`.
"""
