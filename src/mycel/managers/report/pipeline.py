"""The report domain's business chain.

A pipeline defines the *order* of steps; each step is a service doing one thing:

  request_report()
    1. permission service    may this person see this source
    2. enqueue service       push the job, return a job_id
                             --- a worker picks the job up and continues ---
    3. gather service        query gold for the data needed
    4. analyze service       hand it to agents/ for analysis
    5. render service        build the artifact via reports/

The pipeline does no work itself, it only chains services together. Services are reusable
across pipelines — the gather service also serves the sync domain.
"""
