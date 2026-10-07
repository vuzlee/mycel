"""Helpers both suites share."""

import json
from pathlib import Path
from typing import Any

#: What one eval call may spend. Small on purpose: a runaway here is a bill, not a failed test.
CEILING_USD = "1.00"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Every non-blank line of a JSONL file; empty when the file does not exist."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def ids(path: Path) -> set[str]:
    """The `id` of every row already saved in a JSONL file."""
    return {str(row["id"]) for row in read_jsonl(path)}
