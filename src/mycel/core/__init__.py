"""Shared foundation for the whole system: config from env and from file, logger, base
exception, common types.

Configuration is two modules, split by whether a value can be committed: `config.py` reads
the environment and holds the secrets, `config_files.py` reads the layered YAML under
`config/` and holds everything a reviewer should see in a diff.

Bottom layer: **imports no other module in `mycel`**. Every other layer imports it,
so any dependency pointing back up creates a cycle.

Same shape as `agents/core/`, different scope: that one is the shared foundation for
`agents/` alone. A `core/` nested inside a package always means "shared foundation of
that package".
"""

from mycel.core.config import Settings, get_settings
from mycel.core.config_files import get_config, load_config
from mycel.core.exceptions import ConfigError, MycelError
from mycel.core.logging import get_logger, setup_logging

__all__ = [
    "ConfigError",
    "MycelError",
    "Settings",
    "get_config",
    "get_logger",
    "load_config",
    "get_settings",
    "setup_logging",
]
