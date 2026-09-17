"""Answers *when to run*: sync sources on a timer, transform after a sync completes,
periodic reports.

Calls pipelines in `managers/` directly — the same place the controller calls, just without
the HTTP link in between. It never makes an HTTP call to itself.

Different from `queue/`: this is the schedule, that is the job and what happens when a job
fails.
"""
