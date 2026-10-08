from typing import Any


def rowcount(result: Any) -> int:
    """Rows a write touched; read via getattr since not every `Result` type declares it."""
    return int(getattr(result, "rowcount", 0) or 0)
