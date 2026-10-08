"""Health checks."""

from typing import Literal

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from mycel.core.logging import get_logger
from mycel.infra.postgres.session import session_scope

router = APIRouter(prefix="/health", tags=["health"])

log = get_logger(__name__)


@router.get("/live")
async def live() -> dict[str, Literal["ok"]]:
    """Alive. Touches nothing outside the process."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict[str, str]:
    """Ready. Reaches Postgres, because readiness that checks nothing always passes."""
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # any failure means not ready
        log.warning("readiness failed", extra={"error": str(exc), "error_type": type(exc).__name__})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
