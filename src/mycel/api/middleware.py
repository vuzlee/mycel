"""Hand-written middleware — exactly one: attach a `request_id` to every request.

Everything else is **not** hand-written, because it already exists and rewriting it
means maintaining a re-implementation of something already standardised:

  tracing      `FastAPIInstrumentor.instrument_app(app)` — follows OTel semantic
               conventions (`http.route`, `http.status_code`); a hand-rolled one drifts
  CORS         Starlette's `CORSMiddleware`
  errors       `@app.exception_handler(...)` — FastAPI's own mechanism, not middleware
  rate limit   Nginx/ingress blocks before reaching the app; use `slowapi` for per-user
  auth         `Depends()` — see `dependencies.py`, which explains why it is not here

Why `request_id` still has to be hand-written: the value is in putting the id into
`contextvars` so `observability/logging.py` picks it up on its own, which keeps
controllers from writing `log.info(..., request_id=rid)` on every line. The logger is
ours, so no library can wire that up for us; given that, writing it directly beats
adding a dependency.

Reuse the id from the header when present (preserving the chain across services),
otherwise generate one. Return it in the response header so whoever reports a problem
has the exact id to look up.

**Write it as pure ASGI, not `BaseHTTPMiddleware`.** That one buffers the response and
so stalls SSE, and agent output is meant to reach the client as it is produced. This
failure is silent: tokens just arrive as one lump at the end.

**`contextvars` (Python built-in, not a FastAPI feature) follows the async task only.**
Boundaries it does not cross:

    await                   preserved — same task
    create_task()           child copies the context at creation; a child's set is
                            invisible to the parent
    run_in_executor/thread  NOT carried over, must be passed explicitly
    another process         gone entirely — see `queue/__init__.py`

That last line is the one we actually hit: jobs run in a separate worker process, so the
id does not travel with them.
"""
