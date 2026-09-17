"""HTTP endpoints for the sync domain.

  POST /sync/{source}   pull one source now, without waiting for the schedule
  GET  /sync/status     the most recent sync per source

Mostly used when debugging or when fresh data is needed urgently. The main path is
scheduler/ calling the pipeline on a timer, with no HTTP involved.
"""
