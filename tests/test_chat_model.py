"""A chat turn runs on the model it picked, and says so when another one answered."""

from typing import Any

import pytest

from mycel.agents.core.model_source import GatewayModel
from mycel.core.config import HostModel, Settings
from mycel.core.exceptions import ConfigError
from mycel.core.principal import Principal
from mycel.domains import chat, chat_model
from mycel.queue.job import Job, JobKind
from mycel.services import models

pytestmark = pytest.mark.anyio

TWO = Settings(
    host_models=(
        HostModel(name="model-a", label="A", default=True),
        HostModel(name="model-b", label="B"),
    )
)


@pytest.fixture(autouse=True)
def two_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "get_settings", lambda: TWO)


class TestModelSource:
    async def test_a_host_ref_becomes_a_gateway_spec(self) -> None:
        source = await chat_model.model_source(7, "host:model-b")
        assert source == GatewayModel("cloud:model-b")

    async def test_an_unknown_ref_is_a_config_error(self) -> None:
        with pytest.raises(ConfigError, match="host:gone"):
            await chat_model.model_source(7, "host:gone")


class TestPrepare:
    @pytest.fixture
    def prepared(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        seen: dict[str, Any] = {}

        async def no_turn(job_id: str) -> None: ...

        async def asker(job: Job) -> Principal:
            return Principal(id=7, email="a@example.com")

        async def deps(job: Job, settings: Any, *args: Any) -> Any:
            seen["spec"] = args[-1].name
            return None

        async def resolve(user_id: int, ref: str | None) -> tuple[str, str | None]:
            seen["asked"] = ref
            if ref == "host:model-b":
                return "host:model-a", "model-b is off"
            return ref or "host:model-a", None

        monkeypatch.setattr(chat, "find_turn", no_turn)
        monkeypatch.setattr(chat, "_who_asked", asker)
        monkeypatch.setattr(chat, "_deps", deps)
        monkeypatch.setattr(chat, "RedisEventChannel", lambda job_id: None)
        monkeypatch.setattr(chat, "RecordingChannel", lambda inner: None)
        monkeypatch.setattr(models, "resolve", resolve)
        return seen

    def _job(self, ref: str | None) -> Job:
        payload: dict[str, object] = {"question": "q?", "user_id": 7}
        if ref is not None:
            payload["model_ref"] = ref
        return Job(kind=JobKind.CHAT, payload=payload)

    async def test_the_picked_model_runs(self, prepared: dict[str, Any]) -> None:
        turn = await chat._prepare(self._job("host:model-a"))
        assert turn is not None
        assert (turn.model_ref, turn.notice, prepared["spec"]) == (
            "host:model-a",
            None,
            "cloud:model-a",
        )

    async def test_a_job_queued_before_models_runs_on_the_default(
        self, prepared: dict[str, Any]
    ) -> None:
        turn = await chat._prepare(self._job(None))
        assert turn is not None and turn.model_ref == "host:model-a"

    async def test_a_model_gone_before_the_run_carries_a_notice(
        self, prepared: dict[str, Any]
    ) -> None:
        turn = await chat._prepare(self._job("host:model-b"))
        assert turn is not None
        assert turn.model_ref == "host:model-a"
        assert turn.notice == "model-b is off"
