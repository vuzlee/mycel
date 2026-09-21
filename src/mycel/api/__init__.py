"""HTTP shell — as thin as it can be.

  app.py           create the app, mount routers, enable middleware, wire observability
  middleware.py    only `request_id` — the rest is off-the-shelf, see its docstring
  dependencies.py  what routes declare via Depends(): auth, DB session, pagination
  health.py        /health/live and /health/ready — belong to no business domain

Business endpoints live in routes/<name>.py and call domains/<name>.py; app.py only
gathers them.

**When streaming lands, the envelope is this module's job, not the agent layer's.**
`run_stream_events()` yields typed events, and nothing else: no ordering, and no way to
tell one agent's events from another's. A client needs four things the framework does not
provide:

  seq                  per connection, so a quiet stream is distinguishable from a dropped
                       one — and ordered only WITHIN one agent, never across two that ran
                       in parallel
  agent                which agent produced this, so the client can separate sources on one
                       connection rather than opening one per agent
  parent_tool_call_id  which tool call it sits under, so delegated work nests instead of
                       interleaving into noise
  backpressure         a bounded queue. Without it an agent faster than the client is an
                       unbounded buffer

That shape is a contract with clients — adding a field is fine, changing one is breaking.

**The hard part is not the envelope.** Jobs run in a separate worker process (see
`queue/__init__.py`), so the events are produced somewhere the HTTP handler cannot reach:
an in-process queue does not cross that boundary, and a pub/sub hop between them changes
what the envelope has to carry. Settle the transport before designing the wire format.
"""
