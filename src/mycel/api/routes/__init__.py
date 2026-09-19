"""Endpoints, kept out of `app.py` so that file only assembles.

`reports.py` is the one route this batch has. It runs a report inside the request, which
is a deliberate placeholder: batch 004 moves the work to a worker process and this route
becomes a `202` with a job id. Nothing should be built on top of it in the meantime.
"""
