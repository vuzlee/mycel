"""Where the whole HTTP layer is assembled.

`uvicorn mycel.api.app:app` points here. This is the only file that knows which
domains the system has:

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
