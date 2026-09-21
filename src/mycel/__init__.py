"""Mycel - multi-agent system that builds reports from multiple data sources."""

from pathlib import Path

__version__ = "0.1.0"

#: Repo root, resolved from this file rather than counted from each caller: modules move
#: between packages and a `parents[n]` written elsewhere goes silently wrong when they do.
REPO_ROOT = Path(__file__).resolve().parents[2]
