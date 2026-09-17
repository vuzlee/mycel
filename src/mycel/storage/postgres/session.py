"""A session's lifetime: open, commit on success, rollback on error, always close.

One request = one session. Do not share a session across concurrent tasks — SQLAlchemy
sessions are not concurrency-safe.
"""
