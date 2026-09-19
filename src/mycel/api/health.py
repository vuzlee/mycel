"""Health checks.

/health/live   — is the process alive. Used by the restart policy.
/health/ready  — is it ready to take requests (DB reachable, migrations applied).
                 Used by the load balancer, to avoid sending traffic to an instance
                 that is not ready yet.
"""

from typing import Literal

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, Literal["ok"]]:
    """Is the process alive. Answers without touching anything outside it.

    Deliberately trivial: this drives the restart policy, so it must not fail for any
    reason other than the process being unable to serve. A liveness check that consults
    a database restarts a healthy container every time that database blinks.
    """
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str]:
    """Is it ready to take traffic. Separate from liveness, for the reason above.

    Nothing to check yet: this batch holds no connection to Postgres, RabbitMQ or Redis,
    so claiming to verify them would be a lie that passes. Each becomes a check here as
    the batch that introduces it lands — 004 adds the broker, and the storage batch adds
    the database and its migration state.
    """
    return {"status": "ok"}
