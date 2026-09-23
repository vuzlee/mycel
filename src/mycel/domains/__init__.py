"""Business logic, one module per domain. Nothing here knows about HTTP.

A domain module chains services into the operations the product offers:

    domains/chat.py     ask a question, read what became of it
    domains/sync.py     pull a source and push it up to gold

Three layers, each only knowing the one below:

    api/routes/     HTTP — validate, call a domain, shape the response
    domains/        the order of steps, the rules between them
    services/       one job per file, reusable across domains

A domain is called by anything: an endpoint, the scheduler, a script. That is why the
FastAPI types stop at `api/routes/` — a domain that imports `Request` can only ever be
called by a request.

Adding a domain = one module here plus one route module. Existing domains stay untouched.
"""
