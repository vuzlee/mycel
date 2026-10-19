"""Settings reads the environment."""

import pytest

from mycel.core.config import HostModel, Settings, get_settings


def test_defaults_need_no_environment() -> None:
    """A bare process must still produce usable settings — no credential required."""
    s = Settings()
    assert s.mycel_env == "dev"
    assert s.litellm_base_url == "http://localhost:4000"


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCEL_ENV", "prod")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("OTEL_ENABLED", "true")
    s = Settings()
    assert s.mycel_env == "prod"
    assert s.otel_enabled is True
    assert s.litellm_base_url == "http://litellm:4000"


def test_unknown_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` carries DATABASE_URL, RabbitMQ and Qdrant keys this slice never reads."""
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
    monkeypatch.setenv("JIRA_CLIENT_SECRET", "sk-do-not-leak")
    assert "jira_client_secret" in repr(Settings())
    assert "sk-do-not-leak" not in repr(Settings())


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_provider_keys_never_reach_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEFAULT_MODEL_API_KEY is read by the gateway, not by Settings."""
    monkeypatch.setenv("DEFAULT_MODEL_API_KEY", "one")
    assert not hasattr(Settings(), "llm_api_key")


class TestWhereSettingsComeFrom:
    """Four sources, and the order between them is what is tested."""

    def test_the_environment_beats_the_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        assert Settings().log_level == "DEBUG"

    def test_the_yaml_beats_the_class_default(self) -> None:
        """base.yaml carries the real defaults now."""
        assert Settings().embedding_model == "BAAI/bge-small-en-v1.5"

    def test_the_overlay_beats_base(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dev.yaml sets DEBUG over base.yaml's INFO."""
        monkeypatch.setenv("MYCEL_ENV", "dev")
        monkeypatch.delenv("METRICS_PORT", raising=False)  # conftest sets a free one
        settings = Settings()
        assert settings.log_level == "DEBUG"
        assert settings.metrics_port == 9100, "an overlay must not drop what it omits"

    def test_prod_keeps_the_base_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYCEL_ENV", "prod")
        assert Settings().log_level == "INFO"

    def test_reading_the_yaml_does_not_recurse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The source reads MYCEL_ENV from the environment directly, NOT through get_settings()."""
        from mycel.core.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("MYCEL_ENV", "dev")
        try:
            assert get_settings().log_level == "DEBUG"
        finally:
            get_settings.cache_clear()


class TestTheConnectionPool:
    def test_the_engine_takes_pool_and_overflow_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both count against Postgres' max_connections, once per process."""
        from mycel.infra.postgres.engine import POOL_TIMEOUT_SECONDS, get_engine

        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:1/db")
        monkeypatch.setenv("DB_POOL_SIZE", "3")
        monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
        get_settings.cache_clear()
        get_engine.cache_clear()
        try:
            pool = get_engine().pool
            assert pool.size() == 3  # type: ignore[attr-defined]
            assert pool._max_overflow == 2  # type: ignore[attr-defined]
            assert pool._timeout == POOL_TIMEOUT_SECONDS  # type: ignore[attr-defined]
        finally:
            get_engine.cache_clear()


class TestHostModels:
    def test_exactly_one_default(self) -> None:
        with pytest.raises(ValueError, match="exactly one default"):
            Settings(host_models=(HostModel(name="a", label="A"),))

    def test_a_name_listed_twice_is_refused(self) -> None:
        twice = (HostModel(name="a", label="A", default=True), HostModel(name="a", label="B"))
        with pytest.raises(ValueError, match="twice"):
            Settings(host_models=twice)

    def test_the_default_is_found(self) -> None:
        listed = (HostModel(name="a", label="A"), HostModel(name="b", label="B", default=True))
        assert Settings(host_models=listed).default_host_model.name == "b"
