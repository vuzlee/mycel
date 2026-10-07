"""Small readers for what a write statement returns."""

from typing import Any


def rowcount(result: Any) -> int:
    """Rows a write touched. Not every `Result` type declares the attribute, so it is read."""
    return int(getattr(result, "rowcount", 0) or 0)
