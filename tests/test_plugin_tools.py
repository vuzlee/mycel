"""Plugins hand each specialist its tools, and only when someone could connect them."""

import pytest

from mycel.plugins import registry
from mycel.plugins.google import oauth as google_oauth
from mycel.plugins.google.plugin import PLUGIN as GOOGLE
from mycel.plugins.jira.plugin import PLUGIN as JIRA


def test_google_offers_nothing_when_no_client_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google_oauth, "configured", lambda settings=None: False)
    assert GOOGLE.toolsets("researcher") == []


def test_google_gives_the_researcher_mail_and_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google_oauth, "configured", lambda settings=None: True)
    assert len(GOOGLE.toolsets("researcher")) == 2
    assert GOOGLE.toolsets("analyst") == []


def test_jira_gives_the_researcher_nothing() -> None:
    assert JIRA.toolsets("researcher") == []


def test_the_registry_gathers_every_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google_oauth, "configured", lambda settings=None: True)
    assert len(registry.toolsets("researcher")) == 2
