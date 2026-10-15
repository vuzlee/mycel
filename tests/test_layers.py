"""Which package may import which. Tools call services; services never reach into agents."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "mycel"

#: package → packages it must never import.
FORBIDDEN = {
    "services": ("mycel.agents",),
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
