"""`GET /metrics` — the registry, in the text format Prometheus reads.

The only route in the system with no authentication, and it has to be: Prometheus sends
no session token and there is nowhere to put one. What keeps it private is the network —
`docker-compose.yml` does not publish this port outside the compose network, and a
deployment that faces the internet must keep it that way or block the path at the proxy.

Nothing here is per-request: the counters are incremented where the work happens, and this
only renders whatever they hold. See `observability/metrics.py` for the label rule, which
is the part that can go badly wrong.
"""

from fastapi import APIRouter, Response

from mycel.observability.metrics import render

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Kept out of the OpenAPI schema: it is for a scraper, not for a client."""
    body, content_type = render()
    return Response(content=body, media_type=content_type)
