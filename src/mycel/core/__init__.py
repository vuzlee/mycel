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
