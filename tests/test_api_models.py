"""The HTTP API: /models."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mycel.api.app import create_app
from mycel.api.dependencies import current_user
from mycel.core.config import Settings
from mycel.core.principal import Principal
from mycel.services import models as domain

SIGNED_IN = Principal(id=1, email="tester@example.com")
FOUND = domain.Models(
    choices=[domain.ModelChoice(ref="host:a", label="A", source="host", enabled=True)],
    default_ref="host:a",
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(otel_enabled=False))
    app.dependency_overrides[current_user] = lambda: SIGNED_IN
    with TestClient(app, raise_server_exceptions=False) as running:
        yield running


def _domain(monkeypatch: pytest.MonkeyPatch, name: str, result: object) -> None:
    async def fake(*args: object) -> object:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(f"mycel.api.routes.models.domain.{name}", fake)


class TestModelsApi:
    def test_list(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _domain(monkeypatch, "models_for", FOUND)
        body = client.get("/models").json()
        assert body == {
            "models": [{"ref": "host:a", "label": "A", "source": "host", "enabled": True}],
            "default_ref": "host:a",
        }

    def test_turning_off_the_last_is_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _domain(monkeypatch, "set_enabled", domain.LastModel("host:a"))
        assert client.put("/models/prefs/host:a", json={"enabled": False}).status_code == 409

    def test_an_unknown_model_is_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _domain(monkeypatch, "set_enabled", domain.UnknownModel("host:x"))
        assert client.put("/models/prefs/host:x", json={"enabled": True}).status_code == 404

    def test_default(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _domain(monkeypatch, "set_default", FOUND)
        assert client.put("/models/default", json={"ref": "host:a"}).status_code == 200

    def test_signed_out_is_401(self) -> None:
        app = create_app(Settings(otel_enabled=False))
        with TestClient(app) as anonymous:
            assert anonymous.get("/models").status_code == 401
