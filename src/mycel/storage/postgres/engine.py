"""Create the engine and connection pool, once at startup.

Pool size must be sized against the total process count, not per process: `api` runs N
uvicorn workers and `worker` scales with Kafka partitions — each holds its own pool. Summed
past Postgres's `max_connections`, the error only shows up under load.
"""
