"""A run on an own model: its keys rotate, its price is the provider's, its keys never show."""

import json
import logging
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai import models

from mycel.agents.core import model_builder, runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.exceptions import ModelQuota
from mycel.agents.core.own_endpoint import OwnEndpoint
from mycel.agents.registry import build_deps
from mycel.agents.specialists.rewriter import Rewriter
from mycel.core import redact
from mycel.core.logging import JsonFormatter
from mycel.infra.redis import key_rotation

pytestmark = pytest.mark.anyio

GOOD = "AIzaSy-good-key-aaaaaaaaaaaa"
SPENT = "AIzaSy-spent-key-bbbbbbbbbbb"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"


def _completion() -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "gemini-2.5-flash",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200},
    }


def _stream() -> bytes:
    """The same answer as server-sent chunks, usage on the last one."""
    base = {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gemini-2.5-flash",
    }
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {**base, "choices": [], "usage": _completion()["usage"]},
    ]
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks).encode() + b"data: [DONE]\n\n"


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A fake provider: the spent key gets a daily-quota 429, the good one an answer."""
    seen: dict[str, Any] = {"keys": [], "cooled": [], "closed": 0}

    def handle(request: httpx2.Request) -> httpx2.Response:
        key = request.headers["authorization"].removeprefix("Bearer ")
        seen["keys"].append(key)
        if key == SPENT:
            body = {"error": {"message": "Quota exceeded", "details": [{"quotaId": "PerDay"}]}}
            return httpx2.Response(429, json=body)
        if json.loads(request.content).get("stream"):
            return httpx2.Response(
                200, content=_stream(), headers={"content-type": "text/event-stream"}
            )
        return httpx2.Response(200, json=_completion())

    async def cool(model_id: int, position: int, seconds: int) -> None:
        seen["cooled"].append((position, seconds))

    # Requests go to the mock transport only, never the network.
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(model_builder, "_transport", httpx2.MockTransport(handle))
    monkeypatch.setattr(key_rotation, "cool", cool)
    monkeypatch.setattr(model_builder, "OWN_RETRIES", 0)
    return seen


def _deps(*keys: str) -> Any:
    own = OwnEndpoint(
        model_id=3,
        label="My Gemini",
        api_base=GEMINI,
        endpoint_model="gemini-2.5-flash",
        keys=tuple((i, SecretStr(k)) for i, k in enumerate(keys)),
    )
    return build_deps("job-own", ceiling_usd="0.50", settings=AgentSettings(), own=own)


async def test_a_spent_key_hands_over_and_cools_until_the_reset(
    endpoint: dict[str, Any],
) -> None:
    deps = _deps(SPENT, GOOD)
    assert await runner.run(Rewriter.build(deps.settings), "q", deps) == "ok"

    assert endpoint["keys"] == [SPENT, GOOD]
    position, seconds = endpoint["cooled"][0]
    assert position == 0 and seconds > 60, "a daily quota sits out until midnight Pacific"


async def test_the_price_is_the_providers(endpoint: dict[str, Any]) -> None:
    deps = _deps(GOOD)
    await runner.run(Rewriter.build(deps.settings), "q", deps)
    assert deps.budget.spent_usd > Decimal(0)
    assert (deps.budget.tokens_in, deps.budget.tokens_out) == (1000, 200)


async def test_every_key_spent_is_a_quota_error(endpoint: dict[str, Any]) -> None:
    deps = _deps(SPENT)
    with pytest.raises(ModelQuota, match="My Gemini"):
        await runner.run(Rewriter.build(deps.settings), "q", deps)


async def test_a_key_in_a_failure_message_never_reaches_a_log_line(
    endpoint: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """The run holds its keys for redaction; a log written during it shows none."""
    formatter = JsonFormatter()
    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(formatter.format(record))

    handler = Keep()
    logging.getLogger().addHandler(handler)
    try:
        with redact.holding(SPENT):
            logging.getLogger("mycel.test").warning(
                "provider said", extra={"error": f"bad {SPENT}"}
            )
        deps = _deps(SPENT, GOOD)
        await runner.run(Rewriter.build(deps.settings), "q", deps)
    finally:
        logging.getLogger().removeHandler(handler)

    assert lines and not any(SPENT in line or GOOD in line for line in lines)
    assert redact.REDACTED in json.dumps(lines)
