"""Every plugin this build ships. Adding a provider is one line here."""

from mycel.plugins.base import Plugin
from mycel.plugins.google.plugin import PLUGIN as GOOGLE
from mycel.plugins.jira.plugin import PLUGIN as JIRA

PLUGINS: tuple[Plugin, ...] = (GOOGLE, JIRA)


def get(key: str) -> Plugin | None:
    """The plugin with this key, or None."""
    return next((p for p in PLUGINS if p.key == key), None)
