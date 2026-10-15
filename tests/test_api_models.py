"""The HTTP API: /models."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mycel.api.app import create_app
from mycel.api.dependencies import current_user
from mycel.core.config import Settings
from mycel.core.principal import Principal
from mycel.services import models as domain
from mycel.services import own_models

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


VIEW = own_models.OwnModelView(
    id=3,
    ref="own:3",
    label="My Gemini",
    model_id="gemini-3.6-flash",
    api_base="https://generativelanguage.googleapis.com/v1beta/openai",
    key_hints=["…0001"],
)


def _own(monkeypatch: pytest.MonkeyPatch, name: str, result: object) -> None:
    async def fake(*args: object) -> object:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(f"mycel.api.routes.models.own.{name}", fake)


class TestOwnModelsApi:
    BODY = {
        "label": "My Gemini",
        "model_id": "gemini-3.6-flash",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "keys": ["AIzaSy-a-real-looking-key-0001"],
    }

    def test_adding_answers_with_hints_never_keys(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _own(monkeypatch, "add_own", VIEW)
        response = client.post("/models/own", json=self.BODY)
        assert response.status_code == 201
        assert "AIzaSy" not in response.text
        assert response.json()["key_hints"] == ["…0001"]

    def test_a_refusal_is_422_with_the_reason(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _own(monkeypatch, "add_own", own_models.OwnModelRefused("plain http is not allowed"))
        response = client.post("/models/own", json=self.BODY)
        assert response.status_code == 422 and "plain http" in response.text

    def test_too_many_keys_never_reach_the_service(self, client: TestClient) -> None:
        body = {**self.BODY, "keys": [f"k-{i}" for i in range(6)]}
        assert client.post("/models/own", json=body).status_code == 422

    def test_someone_elses_model_is_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _own(monkeypatch, "remove_own", own_models.OwnModelNotFound(3))
        assert client.delete("/models/own/3").status_code == 404
        _own(monkeypatch, "edit_own", own_models.OwnModelNotFound(3))
        assert client.patch("/models/own/3", json=self.BODY).status_code == 404

    def test_presets_and_limits(self, client: TestClient) -> None:
        body = client.get("/models/own/presets").json()
        assert body["max_models"] == 10 and body["max_keys"] == 5
        assert "Gemini" in body["presets"]


class TestTheTestButtonApi:
    def test_starting_a_test_answers_202_with_a_job(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _own(monkeypatch, "start_key_check", "job-kc")
        response = client.post("/models/own/3/test")
        assert response.status_code == 202
        assert response.json() == {"job_id": "job-kc", "status": "running", "checks": []}

    def test_a_finished_test_shows_hints_and_kinds(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        check = {"hint": "…0001", "ok": False, "kind": "auth", "detail": "key rejected"}
        _own(monkeypatch, "key_check_result", [check])
        body = client.get("/models/own/tests/job-kc").json()
        assert body["status"] == "done" and body["checks"] == [check]

    def test_someone_elses_test_is_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _own(monkeypatch, "key_check_result", own_models.OwnModelNotFound("job-kc"))
        assert client.get("/models/own/tests/job-kc").status_code == 404
