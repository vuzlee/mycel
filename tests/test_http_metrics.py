"""API request timing, the pool-full answer, and uvicorn's logs in JSON."""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.exc import TimeoutError as PoolTimeout

from mycel.api.app import create_app
from mycel.api.middleware import UNMATCHED
from mycel.core.config import Settings
from mycel.core.logging import setup_logging


def _count(route: str, status: str) -> float:
    value = REGISTRY.get_sample_value(
        "mycel_http_request_seconds_count",
        {"method": "GET", "route": route, "status": status},
    )
    return value or 0.0


@pytest.fixture
def app() -> FastAPI:
    built = create_app(Settings(otel_enabled=False))

    @built.get("/test/pool-full")
    async def pool_full() -> None:
        raise PoolTimeout("QueuePool limit reached")

    @built.get("/test/crash/{thing_id}")
    async def crash(thing_id: str) -> None:
        raise RuntimeError("boom")

    return built


def test_a_request_counts_under_its_route_template(app: FastAPI) -> None:
    before = _count("/health/live", "200")
    TestClient(app).get("/health/live")
    assert _count("/health/live", "200") == before + 1


def test_ids_in_the_path_do_not_make_new_series(app: FastAPI) -> None:
    before = _count("/test/crash/{thing_id}", "500")
    client = TestClient(app, raise_server_exceptions=False)
    client.get("/test/crash/a")
    client.get("/test/crash/b")
    assert _count("/test/crash/{thing_id}", "500") == before + 2


def test_an_unknown_path_shares_one_label(app: FastAPI) -> None:
    before = _count(UNMATCHED, "404")
    TestClient(app).get("/no/such/thing-123")
    assert _count(UNMATCHED, "404") == before + 1


def test_a_full_pool_answers_503_with_retry_after(app: FastAPI) -> None:
    response = TestClient(app).get("/test/pool-full")
    assert response.status_code == 503
    assert response.json()["error"] == "overloaded"
    assert response.headers["retry-after"] == "5"


def test_uvicorn_errors_come_out_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    logging.getLogger("uvicorn.error").addHandler(logging.StreamHandler())
    setup_logging("INFO")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["level"] == "ERROR"
    assert "RuntimeError: boom" in line["exception"]
