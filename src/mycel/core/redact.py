"""Secrets the process holds right now, and the one place that strips them from text.

A run registers the keys it unsealed and forgets them when it ends. Logs and exported spans
pass through `scrub`, so a key that ends up in an error message, a URL or a span attribute
leaves as `[redacted]`, whatever path it took.
"""

from collections.abc import Iterator
from contextlib import contextmanager

REDACTED = "[redacted]"
#: Shorter values are too likely to match ordinary text.
MIN_LENGTH = 12

_live: dict[str, int] = {}


@contextmanager
def holding(*secrets: str) -> Iterator[None]:
    """Redact these values everywhere while the block runs; counted, so overlapping runs work."""
    kept = [s for s in secrets if len(s) >= MIN_LENGTH]
    for s in kept:
        _live[s] = _live.get(s, 0) + 1
    try:
        yield
    finally:
        for s in kept:
            _live[s] -= 1
            if not _live[s]:
                del _live[s]


def scrub(text: str) -> str:
    for secret in _live:
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text
