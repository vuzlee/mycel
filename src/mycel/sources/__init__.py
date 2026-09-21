"""Connectors to individual providers: Slack, Gmail, Confluence...

One module per provider, all with the same interface: take the time window to sync, return
raw records, write them down to `bronze`. No cleaning, no normalising — that is `etl/`'s job.

Adding a source = adding a file here, with no changes to existing code. Per-source
configuration (endpoint, scopes, rate limits) lives in `config/sources/`.
"""

from mycel.core.exceptions import MycelError


class SourceError(MycelError):
    """A provider could not be reached, or answered with something unusable.

    One class for every source: a caller upstream of `sources/` reacts to "no data this
    run" the same way whichever provider produced it. Which one, and why, is in the message.
    """
