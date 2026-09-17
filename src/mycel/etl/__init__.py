"""The data transformation steps: raw -> silver -> gold.

This is scheduled background ETL, not a request-handling chain. A request's business chain
lives in managers/<domain>/pipeline.py.

Each step is a pure function: read the layer below, write the layer above, idempotent —
running it twice gives the same result. checks/ verifies after each step.
"""
