"""Where the whole HTTP layer is assembled.

`uvicorn --factory mycel.api.app:create_app` points here. This is the only file that
knows which domains the system has:

    include_router(managers.report.controller.router)
    include_router(managers.sync.controller.router)
    include_router(health.router)

Adding a domain = one directory under managers/ and one line here. Existing domains
stay untouched.

This file only assembles: create the app, mount routers, enable middleware, wire
observability. No endpoints, no business logic.

The assembly, almost entirely off-the-shelf calls:

    observability.tracing.setup()          set up OTel once, BEFORE anything else
    FastAPIInstrumentor.instrument_app()   root span per request
    add_middleware(RequestIdMiddleware)    the only hand-written one
    add_middleware(CORSMiddleware)         origins read from per-environment config
    add_exception_handler(...)             one error shape, carrying request_id,
                                           never leaking a traceback

`tracing.setup()` must run before instrumenting, otherwise spans land in an empty
provider — no error, just empty traces.

Mount order matters: `request_id` must be outermost, so spans and every log line
produced afterwards have an id to attach. Starlette runs middleware in **reverse**
order of `add_middleware`, so what is added last sits outermost — which is why
`request_id` is added *after* the others.

Auth is not here: it is a `Depends()`, see `dependencies.py`.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mycel.agents.core.exceptions import AgentError, RunawayStopped
from mycel.api import dependencies, health
from mycel.api.middleware import RequestIdMiddleware
from mycel.api.routes import reports
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.core.logging import current_request_id, get_logger, setup_logging
from mycel.llm.budget import BudgetExceeded
from mycel.observability.tracing import setup_tracing

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble the application.

    A factory, not a module-level `app`: an app built at import time forces every test to
    accept the real configuration, because by the time a test could override anything the
    app already exists.

    Served with uvicorn's `--factory`, which calls this rather than importing an instance:

        uv run uvicorn --factory mycel.api.app:create_app

    The module docstring above says `mycel.api.app:app`. It predates this decision; there
    is no module-level `app`, on purpose.
    """
    cfg = settings or get_settings()
    setup_logging(cfg.log_level)
    dependencies.reset_caches()

    # Before instrumenting, as the docstring above says: instrumenting first attaches the
    # HTTP spans to the default no-op provider, and they vanish with no error.
    provider = setup_tracing(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Flush spans on the way out.

        `BatchSpanProcessor` holds spans in memory until its timer fires, so a process
        that exits promptly exports nothing — the same reason every `scripts/try_*.py`
        calls `shutdown()`.
        """
        yield
        if provider is not None:
            provider.shutdown()

    app = FastAPI(
        title="Mycel",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(reports.router)

    _install_error_handlers(app)

    if provider is not None:
        # Imported here rather than at module level: the instrumentation package is only
        # needed when tracing is on, and importing it patches things process-wide.
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

    # Added last so it sits outermost — Starlette runs middleware in reverse order of
    # `add_middleware`. Outermost is where request_id must be: everything inside it,
    # including the tracing span and every log line, needs the id already bound.
    app.add_middleware(RequestIdMiddleware)

    return app


def _install_error_handlers(app: FastAPI) -> None:
    """One error shape for everything, carrying the request id and no traceback.

    The mapping is the point. These are not all 500s, and treating them as such is how a
    caller who asked for too much gets told the server is broken:

      BudgetExceeded    402 — the request was refused on purpose, and retrying it
                              unchanged will be refused again
      RunawayStopped    504 — the run hit its own ceiling; the request was valid
      ConfigError       500 — a deployment is misconfigured; genuinely our fault
      AgentError        502 — something upstream of us failed (a provider, a tool)
    """

    def problem(status: int, kind: str, detail: str) -> JSONResponse:
        """The one error shape. The id goes in the body only — `RequestIdMiddleware`
        owns the header, and setting it here too is how it ends up sent twice."""
        return JSONResponse(
            status_code=status,
            content={
                "error": kind,
                "detail": detail,
                "request_id": current_request_id.get() or None,
            },
        )

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
        """Anything raised on purpose that the handlers above did not name.

        Not a catch-all for bugs: an exception that is *not* a `MycelError` is left alone
        so it reaches the server's own handler as a 500 with a logged traceback, which is
        what an unhandled bug should look like.
        """
        log.error("unhandled mycel error", extra={"detail": str(exc)})
        return problem(500, "internal_error", str(exc))
