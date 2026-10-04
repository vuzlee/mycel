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


class NotWritten(SourceError):
    """A write failed, and it is certain that nothing was written.

    The distinction matters to exactly one caller — `agents/tools/jira.py`, which holds a
    draft the person has already read back and agreed to. If the request cannot have
    landed, that draft can be offered again and a second yes is a retry. If it *might*
    have landed, offering a retry is offering to post the same comment twice.

    So this is raised only where the certainty is real: the provider refused the request
    outright, or the connection was never made. A timeout or a 5xx stays a plain
    `SourceError` — the request may well have arrived and only the answer been lost.
    """
