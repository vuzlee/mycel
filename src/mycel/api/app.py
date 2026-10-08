"""Where the whole HTTP layer is assembled."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from mycel import REPO_ROOT
from mycel.agents.core.exceptions import AgentError, RunawayStopped
from mycel.api import health
from mycel.api.middleware import RequestIdMiddleware
from mycel.api.routes import (
    auth,
    chat,
    connections,
    conversations,
    dashboard,
    documents,
    events,
    projects,
)
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.core.logging import current_request_id, get_logger, setup_logging
from mycel.infra.postgres.engine import dispose_engine
from mycel.llm.budget import BudgetExceeded
from mycel.observability.metrics_server import serve_metrics
from mycel.observability.tracing import setup_tracing
from mycel.services.auth import AuthError

log = get_logger(__name__)

#: Where `web/` lands once built.
WEB_DIST = REPO_ROOT / "web" / "dist"


#: The api's metrics port, after the worker (+0), scheduler (+1) and ingest (+2).
METRICS_OFFSET = 3


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble the application."""
    cfg = settings or get_settings()
    setup_logging(cfg.log_level)

    # Before instrumenting, or the HTTP spans attach to the no-op provider and vanish.
    provider = setup_tracing(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Flush spans and close the connection pool on the way out."""
        metrics = await serve_metrics(cfg.metrics_port + METRICS_OFFSET, cfg.metrics_host)
        yield
        metrics.close()
        await dispose_engine()
        if provider is not None:
            provider.shutdown()

    app = FastAPI(
        title="Mycel",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(connections.router)
    app.include_router(projects.router)
    app.include_router(conversations.router)
    app.include_router(dashboard.router)
    app.include_router(chat.router)
    app.include_router(documents.router)
    app.include_router(events.router)

    _install_error_handlers(app)
    _mount_web(app)

    if provider is not None:
        # Imported lazily: it is only needed with tracing on, and importing it patches globally.
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls=UNTRACED)

    # Added last so it runs outermost: everything inside needs the request id bound.
    app.add_middleware(RequestIdMiddleware)

    return app


#: Requests that make a span and say nothing with it.
UNTRACED = ",".join(
    [
        r"chat/[0-9a-f]{32}",  # the poll, and the stream under it
        r"auth/me",
        r"health/",
        r"app",  # the single-page mount and its assets
    ]
)


class _SinglePage(StaticFiles):
    """Static files, with every unknown path answering `index.html`."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


def _mount_web(app: FastAPI) -> None:
    """Serve the built `web/` app at `/app`, if it was built."""
    if not WEB_DIST.is_dir():
        log.info("web/dist not built, /app not served")
        return

    app.mount("/app", _SinglePage(directory=WEB_DIST, html=True), name="web")


def _install_error_handlers(app: FastAPI) -> None:
    """One error shape for everything, carrying the request id and no traceback."""

    def problem(status: int, kind: str, detail: str) -> JSONResponse:
        """The one error shape."""
        return JSONResponse(
            status_code=status,
            content={
                "error": kind,
                "detail": detail,
                "request_id": current_request_id.get() or None,
            },
        )

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError) -> JSONResponse:
        """A refused registration or login. 400, not 500: the caller's input was wrong."""
        return problem(400, "auth_failed", str(exc))

    @app.exception_handler(BudgetExceeded)
    async def _budget(request: Request, exc: BudgetExceeded) -> JSONResponse:
        log.warning("request refused for budget", extra={"detail": str(exc)})
        return problem(402, "budget_exceeded", str(exc))

    @app.exception_handler(RunawayStopped)
    async def _runaway(request: Request, exc: RunawayStopped) -> JSONResponse:
        log.warning("run hit its ceiling", extra={"detail": str(exc)})
        return problem(504, "runaway_stopped", str(exc))

    @app.exception_handler(ConfigError)
    async def _config(request: Request, exc: ConfigError) -> JSONResponse:
        # Logged at error: this one is a deployment problem, not a caller's mistake.
        log.error("misconfigured", extra={"detail": str(exc)})
        return problem(500, "config_error", str(exc))

    @app.exception_handler(AgentError)
    async def _agent(request: Request, exc: AgentError) -> JSONResponse:
        log.warning("agent run failed", extra={"detail": str(exc)})
        return problem(502, "agent_failed", str(exc))

    @app.exception_handler(MycelError)
    async def _mycel(request: Request, exc: MycelError) -> JSONResponse:
        """Anything raised on purpose that the handlers above did not name."""
        log.error("unhandled mycel error", extra={"detail": str(exc)})
        return problem(500, "internal_error", str(exc))
