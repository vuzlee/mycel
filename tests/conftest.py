"""Shared test fixtures.

The module-level `ALLOW_MODEL_REQUESTS = False` is the important line: it makes any real
provider call raise instead of going out to the network. A test suite that can spend money
is a test suite nobody runs.
"""

import os
from collections.abc import Iterator

import pytest
from pydantic_ai import models

from mycel.core.config import Settings, get_settings

# No test may reach a real model, whatever else it does.
models.ALLOW_MODEL_REQUESTS = False

# Variables that would otherwise leak a developer's real environment into the tests. A
# machine with a live ANTHROPIC_API_KEY must not behave differently from CI.
_LEAKY_PREFIXES = ("MYCEL_", "ANTHROPIC_", "OTEL_", "LOCAL_LLM_", "LOG_")


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio only; we do not support trio."""
    return "asyncio"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip inherited env vars and reset the settings cache around every test.

    Also stops `Settings` reading the developer's `.env`, so the suite sees defaults
    unless a test sets a variable itself.
    """
    for key in list(os.environ):
        if key.startswith(_LEAKY_PREFIXES):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
