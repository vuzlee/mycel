"""put/get/delete, streaming reads and writes.

Always stream, never `read()` a whole file into RAM: one 200MB PDF times a few concurrent
jobs is enough to kill a worker with OOM — and Kafka will read that as a dead worker and
re-run the very same job, looping forever.
"""
