"""Where the whole HTTP layer is assembled.

`uvicorn --factory mycel.api.app:create_app` points here. This is the only file that
knows which routers the system has:

    include_router(health.router)
    include_router(auth.router)
    include_router(projects.router)
    include_router(members.router)
    include_router(chat.router)
    include_router(events.router)

Adding a domain = a module under `domains/`, a module under `api/routes/`, and one line
here. Existing domains stay untouched.

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

Auth is not here beyond mounting its router: who a request is comes from a `Depends()`,
see `dependencies.py`.
"""

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
from mycel.api import dependencies, health
from mycel.api.middleware import RequestIdMiddleware
from mycel.api.routes import auth, chat, events, members, projects
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.core.logging import current_request_id, get_logger, setup_logging
from mycel.infra.postgres.engine import dispose_engine
from mycel.llm.budget import BudgetExceeded
from mycel.observability.tracing import setup_tracing
from mycel.services.auth import AuthError

log = get_logger(__name__)

#: Where `web/` lands once built. Relative to the repo root in a checkout and to `/app` in
#: the image, which is why it is found by walking up from this file rather than configured.
WEB_DIST = REPO_ROOT / "web" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble the application.

    A factory, not a module-level `app`: an app built at import time forces every test to
    accept the real configuration, because by the time a test could override anything the
    app already exists.

    Served with uvicorn's `--factory`, which calls this rather than importing an instance:

        uv run uvicorn --factory mycel.api.app:create_app

    The module docstring above says `mycel.api.app:app`. It predates this
    decision; there is no module-level `app`, on purpose.
    """
    cfg = settings or get_settings()
    setup_logging(cfg.log_level)
    dependencies.reset_caches()

    # Before instrumenting, as the docstring above says: instrumenting first attaches the
    # HTTP spans to the default no-op provider, and they vanish with no error.
    provider = setup_tracing(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Flush spans and close the connection pool on the way out.

        `BatchSpanProcessor` holds spans in memory until its timer fires, so a process
        that exits promptly exports nothing — the same reason every `scripts/try_*.py`
        calls `shutdown()`.
        """
        yield
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
    app.include_router(projects.router)
    app.include_router(members.router)
    app.include_router(chat.router)
    app.include_router(events.router)

    _install_error_handlers(app)
    _mount_web(app)

    if provider is not None:
        # Imported here rather than at module level: the instrumentation package is only
        # needed when tracing is on, and importing it patches things process-wide.
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=provider, excluded_urls=UNTRACED
        )

    # Added last so it sits outermost — Starlette runs middleware in reverse order of
    # `add_middleware`. Outermost is where request_id must be: everything inside it,
    # including the tracing span and every log line, needs the id already bound.
    app.add_middleware(RequestIdMiddleware)

    return app


#: Requests that make a span and say nothing with it.
#:
#: A trace is meant to be one unit of work, and here that is one turn: `POST /chat` is its
#: root, and the job the worker picks up minutes later hangs off it through the
#: `traceparent` in the message headers. Everything below is the *page*, not the work —
#: and it is the page that talks constantly.
#:
#: The poll is the reason this list exists at all. `web/src/run.ts` asks
#: `GET /chat/{job_id}` every three seconds, so a two-minute run buries its one real trace
#: under forty empty ones, each an equal root in the UI. The stream, the session check and
#: the static app are the same kind of noise, more slowly.
#:
#: Matched on a 32-hex job id rather than on `chat/`, so `POST /chat` keeps its span.
#: Dropping that would cost the tree its root and leave every worker run an orphan.
#:
#: Agent spans come from pydantic-ai and never pass through this instrumentation, so
#: nothing here can hide a model or tool call.
UNTRACED = ",".join(
    [
        r"chat/[0-9a-f]{32}",  # the poll, and the stream under it
        r"auth/me",
        r"health/",
        r"app",  # the single-page mount and its assets
    ]
)

class _SinglePage(StaticFiles):
    """Static files, with every unknown path answering `index.html`.

    The router lives in the browser, so `/app/login` is a real address there and no file
    at all here. `html=True` alone does not cover it — it falls back to `index.html` for a
    directory, not for a miss — and a route declared after the mount never runs, because a
    mount owns its whole prefix. So the fallback belongs here, inside the mount.

    A missing asset still 404s: only a path without a file extension is a route, and
    answering HTML to a request for a `.js` that is not there hides a broken build behind
    a syntax error.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


def _mount_web(app: FastAPI) -> None:
    """Serve the built `web/` app at `/app`, if it was built.

    After every router, so a static path can never shadow an API one. Conditional, so a
    source checkout without `npm run build` still starts — the UI is a client of this
    service, not a part of it that it fails without.
    """
    if not WEB_DIST.is_dir():
        log.info("web/dist not built, /app not served")
        return

    app.mount("/app", _SinglePage(directory=WEB_DIST, html=True), name="web")


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

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError) -> JSONResponse:
        """A refused registration or login. 400, not 500: the caller's input was wrong.

        The message is whatever `services/auth.py` chose, which is deliberately vague
        about which half of a credential pair failed.
        """
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
        """Anything raised on purpose that the handlers above did not name.

        Not a catch-all for bugs: an exception that is *not* a `MycelError` is left alone
        so it reaches the server's own handler as a 500 with a logged traceback, which is
        what an unhandled bug should look like.
        """
        log.error("unhandled mycel error", extra={"detail": str(exc)})
        return problem(500, "internal_error", str(exc))
