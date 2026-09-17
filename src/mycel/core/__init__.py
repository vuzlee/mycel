"""Shared foundation for the whole system: config from env/file, logger, base
exception, common types.

Bottom layer: **imports no other module in `mycel`**. Every other layer imports it,
so any dependency pointing back up creates a cycle.

Same shape as `agents/core/`, different scope: that one is the shared foundation for
`agents/` alone. A `core/` nested inside a package always means "shared foundation of
that package".
"""

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.core.logging import get_logger, setup_logging

__all__ = [
    "ConfigError",
    "MycelError",
    "Settings",
    "get_logger",
    "get_settings",
    "setup_logging",
]
