"""Every plugin this build ships. Adding a provider is one line here."""

from typing import TYPE_CHECKING

from mycel.plugins.base import Plugin, Role
from mycel.plugins.google.plugin import PLUGIN as GOOGLE
from mycel.plugins.jira.plugin import PLUGIN as JIRA

PLUGINS: tuple[Plugin, ...] = (GOOGLE, JIRA)


if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from mycel.agents.core.deps import MycelDeps


def toolsets(role: Role) -> "list[AbstractToolset[MycelDeps]]":
    """Every plugin's tools for one specialist."""
    return [t for p in PLUGINS for t in p.toolsets(role)]


def get(key: str) -> Plugin | None:
    """The plugin with this key, or None."""
    return next((p for p in PLUGINS if p.key == key), None)
