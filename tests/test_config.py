"""Settings reads the environment, tolerates variables it has no field for, and keeps
secrets out of reprs."""

import pytest

from mycel.core.config import Settings, get_settings


def test_defaults_need_no_environment() -> None:
    """A bare process must still produce usable settings — no credential required.

    `otel_enabled` is deliberately not asserted here: since batch 059 it comes from
    `config/environments/`, where dev turns it on and prod leaves it off. Asserting one
    value would be asserting which environment the test happens to run in.
    """
    s = Settings()
    assert s.mycel_env == "dev"
    assert s.gemini_api_keys == ""
    assert s.local_llm_base_url == "http://localhost:8001/v1"


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
    """Settings end up in logs and tracebacks; the key must not travel with them.

    Named on a field that still exists. `extra="ignore"` means a variable with no field
    behind it never reaches the repr at all, so this test would pass for the wrong reason
    the day the field it names is deleted — which is exactly what batch 060 did to
    `JIRA_API_TOKEN`.
    """
    monkeypatch.setenv("JIRA_CLIENT_SECRET", "sk-do-not-leak")
    assert "jira_client_secret" in repr(Settings())
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

class TestWhereSettingsComeFrom:
    """Four sources, and the order between them is the whole of batch 059.

        class default  <  config/environments/*.yaml  <  .env  <  environment

    The environment has to win, or `docker run -e LOG_LEVEL=DEBUG` stops working — and a
    person discovering that is a person who has already spent an hour on it.
    """

    def test_the_environment_beats_the_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        assert Settings(_env_file=None).log_level == "DEBUG"

    def test_the_yaml_beats_the_class_default(self) -> None:
        """base.yaml carries the real defaults now; the class default is the fallback for
        a checkout with no config directory at all."""
        assert Settings(_env_file=None).embedding_model == "BAAI/bge-small-en-v1.5"

    def test_the_overlay_beats_base(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """dev.yaml sets DEBUG over base.yaml's INFO. Merged key by key, so an overlay
        that mentions one setting does not drop the rest."""
        monkeypatch.setenv("MYCEL_ENV", "dev")
        settings = Settings(_env_file=None)
        assert settings.log_level == "DEBUG"
        assert settings.metrics_port == 9100, "an overlay must not drop what it omits"

    def test_prod_keeps_the_base_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYCEL_ENV", "prod")
        assert Settings(_env_file=None).log_level == "INFO"

    def test_reading_the_yaml_does_not_recurse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The source reads MYCEL_ENV from the environment directly, NOT through
        get_settings().

        Through it, the lru_cache is still empty mid-construction, so it builds a second
        Settings and the inner one returns first — before any YAML is read. The symptom is
        a value that is present when printed and None when the app asks for it.
        """
        from mycel.core.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("MYCEL_ENV", "dev")
        try:
            assert get_settings().log_level == "DEBUG"
        finally:
            get_settings.cache_clear()
