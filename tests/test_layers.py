"""Which package may import which. Tools call services; services never reach into agents."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "mycel"

#: package → packages it must never import.
FORBIDDEN = {
    "services": ("mycel.agents", "mycel.domains", "mycel.plugins", "mycel.api"),
    "etl": ("mycel.services", "mycel.domains", "mycel.agents", "mycel.plugins", "mycel.api"),
    "domains": ("mycel.api",),
    "core": ("mycel.agents", "mycel.services", "mycel.domains", "mycel.api"),
    # Stores and value types sit under everything that runs work.
    "infra": (
        "mycel.agents",
        "mycel.services",
        "mycel.domains",
        "mycel.api",
        "mycel.queue",
        "mycel.lifecycle",
    ),
    # Value types: `infra` may store them, so they never reach back into `infra`.
    "llm": (
        "mycel.infra",
        "mycel.agents",
        "mycel.services",
        "mycel.domains",
        "mycel.api",
        "mycel.queue",
        "mycel.lifecycle",
    ),
    "events": (
        "mycel.infra",
        "mycel.agents",
        "mycel.services",
        "mycel.domains",
        "mycel.api",
        "mycel.queue",
        "mycel.lifecycle",
    ),
    # The queue moves jobs; the process that runs it is `worker.py`.
    "queue": ("mycel.agents", "mycel.services", "mycel.domains", "mycel.api", "mycel.lifecycle"),
    # The API queues work; agents run only in the worker.
    "api": ("mycel.agents", "mycel.domains"),
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_no_import_crosses_a_layer_upward(package: str) -> None:
    crossing = [
        f"{path.relative_to(SRC)} imports {name}"
        for path in (SRC / package).rglob("*.py")
        for name in _imports(path)
        if name.startswith(FORBIDDEN[package])
    ]
    assert crossing == []


#: A provider's HTTP client: talks to the provider, knows nothing of mycel above `core`.
CLIENTS = ("errors.py", "http.py", "client.py", "mail_client.py", "calendar_client.py")
CLIENT_MAY_IMPORT = ("mycel.core", "mycel.infra.http", "mycel.plugins.errors")


def test_a_provider_client_imports_only_core_and_its_siblings() -> None:
    crossing = [
        f"{path.relative_to(SRC)} imports {name}"
        for path in (SRC / "plugins").rglob("*.py")
        if path.name in CLIENTS
        for name in _imports(path)
        if name.startswith("mycel.")
        and not name.startswith(CLIENT_MAY_IMPORT)
        and not name.startswith(f"mycel.plugins.{path.parent.name}.")
    ]
    assert crossing == []


#: What a tool outside `agents/` may use from it: the run's deps, chip gating, guards, errors.
TOOL_KIT = (
    "mycel.agents.core.deps",
    "mycel.agents.core.chip_filter",
    "mycel.agents.core.guards",
    "mycel.agents.core.exceptions",
    "mycel.agents.tools.limits",
)


@pytest.mark.parametrize("package", ["plugins", "mcp"])
def test_tools_outside_agents_use_only_the_tool_kit(package: str) -> None:
    reaching = [
        f"{path.relative_to(SRC)} imports {name}"
        for path in (SRC / package).rglob("*.py")
        for name in _imports(path)
        if name.startswith("mycel.agents") and name not in TOOL_KIT
    ]
    assert reaching == []


def test_the_app_never_imports_devtools() -> None:
    importing = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if path.relative_to(SRC).parts[0] != "devtools"
        and any(name.startswith("mycel.devtools") for name in _imports(path))
    ]
    assert importing == []
