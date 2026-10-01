"""Settings reads the environment, tolerates variables it has no field for, and keeps
secrets out of reprs."""

import pytest

from mycel.core.config import Settings, get_settings


def test_defaults_need_no_environment() -> None:
    """A bare process must still produce usable settings — no credential required."""
    s = Settings()
    assert s.mycel_env == "dev"
    assert s.gemini_api_keys == ""
    assert s.local_llm_base_url == "http://localhost:8001/v1"
    assert s.otel_enabled is False


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCEL_ENV", "prod")
    monkeypatch.setenv("GEMINI_API_KEYS", "sk-test")
    monkeypatch.setenv("OTEL_ENABLED", "true")
    s = Settings()
    assert s.mycel_env == "prod"
    assert s.otel_enabled is True
    assert s.gemini_api_keys == "sk-test"


def test_unknown_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` carries DATABASE_URL, RabbitMQ and Qdrant keys this slice never reads.

    A strict model would refuse to start over them.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost:5672/")
    assert Settings().mycel_env == "dev"


def test_invalid_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in MYCEL_ENV must fail loudly at startup, not select a silent default."""
    monkeypatch.setenv("MYCEL_ENV", "producton")
    with pytest.raises(ValueError):
        Settings()


def test_secret_is_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings end up in logs and tracebacks; the key must not travel with them."""
    monkeypatch.setenv("JIRA_API_TOKEN", "sk-do-not-leak")
    assert "sk-do-not-leak" not in repr(Settings())


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()

def test_keys_are_split_and_kept_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order matters: the ring hands them out in turn, so it is the order written."""
    monkeypatch.setenv("GEMINI_API_KEYS", "one, two ,three")
    assert Settings().llm_keys("google") == ["one", "two", "three"]

def test_a_blank_entry_is_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`GEMINI_API_KEYS=` in a .env documents that the variable exists; it is not a key.

    Counting it meant llm_keys returned [""], which reaches the provider as a request
    carrying an empty credential rather than as a deployment that has none.
    """
    monkeypatch.setenv("GEMINI_API_KEYS", "  ,  ")
    assert Settings().llm_keys("google") == []

def test_an_unknown_provider_has_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """One provider is configurable. Asking for another is not an error, it is empty —
    `build_model` is where an unreachable model becomes a refusal, and it says which
    variable is missing."""
    monkeypatch.setenv("GEMINI_API_KEYS", "one")
    assert Settings().llm_keys("anthropic") == []
