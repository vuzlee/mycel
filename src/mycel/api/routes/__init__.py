"""Endpoints, kept out of `app.py` so that file only assembles.

One module per surface: `chat.py` queues a question and reads what became of it,
`events.py` streams a running job, `auth.py` and `projects.py` the rest. A route validates,
calls a domain and shapes the response — the order of steps is `domains/`.
"""
