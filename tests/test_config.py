"""Settings reads the environment, tolerates variables it has no field for, and keeps
secrets out of reprs."""

import pytest

from mycel.core.config import Settings, get_settings


def test_defaults_need_no_environment() -> None:
    """A bare process must still produce usable settings — no credential required."""
    s = Settings()
    assert s.mycel_env == "dev"
    assert s.anthropic_api_key is None
    assert s.local_llm_base_url == "http://localhost:8001/v1"
    assert s.otel_enabled is False


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCEL_ENV", "prod")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OTEL_ENABLED", "true")
    s = Settings()
    assert s.mycel_env == "prod"
    assert s.otel_enabled is True
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-test"


def test_unknown_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` carries DATABASE_URL, Kafka and MinIO keys this slice never reads.

    A strict model would refuse to start over them.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    assert Settings().mycel_env == "dev"


def test_invalid_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in MYCEL_ENV must fail loudly at startup, not select a silent default."""
    monkeypatch.setenv("MYCEL_ENV", "producton")
    with pytest.raises(ValueError):
        Settings()


def test_secret_is_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings end up in logs and tracebacks; the key must not travel with them."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-do-not-leak")
    assert "sk-do-not-leak" not in repr(Settings())


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
