"""HTTP endpoints for the report domain.

  POST /reports        request a report  -> returns a job_id immediately
  GET  /reports/{id}   read a generated report
  GET  /jobs/{id}      ask how far a job has got

A controller does exactly four things: receive, validate, call the pipeline, return a
response. No SQL, no LLM calls, no business branching.

It does not run the pipeline to completion: generating a report takes minutes, so the
pipeline enqueues the work and returns a job_id. The client asks again later.
"""
