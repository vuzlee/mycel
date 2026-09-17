"""HTTP shell — as thin as it can be.

  app.py           create the app, mount routers, enable middleware, wire observability
  middleware.py    only `request_id` — the rest is off-the-shelf, see its docstring
  dependencies.py  what controllers declare via Depends(): auth, DB session, pagination
  health.py        /health/live and /health/ready — belong to no business domain

Business endpoints do not live here. They live in managers/<domain>/controller.py;
app.py only gathers them.

**When streaming lands, events need a sequence number.** pydantic-ai's
`run_stream_events()` yields typed events but no `seq`, and over SSE a client cannot
otherwise tell a quiet stream from a dropped one. The envelope is this module's job, not
the agent layer's: `{type, seq, data}`, with `seq` incrementing per connection. That
shape is a contract with clients — adding a field is fine, changing one is breaking.
"""
