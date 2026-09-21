"""Health checks.

/health/live   — is the process alive. Drives the restart policy.
/health/ready  — is it ready to take traffic. Drives the load balancer.

They are separate because a liveness check that consults a database restarts a healthy
container every time that database blinks.
"""

from typing import Literal

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from mycel.core.logging import get_logger
from mycel.infra.postgres.session import session_scope

router = APIRouter(prefix="/health", tags=["health"])

log = get_logger(__name__)


@router.get("/live")
async def live() -> dict[str, Literal["ok"]]:
    """Alive. Touches nothing outside the process, for the reason above."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict[str, str]:
    """Ready. Reaches Postgres, because readiness that checks nothing always passes.

    Answers 503 rather than raising: a load balancer reads the status code, and an
    unhandled exception would also log a stack trace on every poll of a known-down
    dependency.
    """
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("readiness failed", extra={"error": str(exc)})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
