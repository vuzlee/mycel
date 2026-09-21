"""The data transformation steps: bronze -> silver -> gold.

This is scheduled background ETL, not a request-handling chain. A request's business chain
lives in domains/<name>.py.

Each step is a pure function: read the layer below, write the layer above, idempotent —
running it twice gives the same result. checks/ verifies after each step.

    normalise.py  bronze -> silver   unwrap one provider's envelope
    promote.py    silver -> gold     reconcile sources into what the product reads
    checks/       run between the two, so a bad row never reaches the layer above
"""
