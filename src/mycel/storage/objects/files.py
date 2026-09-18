"""put/get/delete, streaming reads and writes.

Always stream, never `read()` a whole file into RAM: one 200MB PDF times a few concurrent
jobs is enough to kill a worker with OOM — and the job, never acked, is redelivered to the
next worker to kill that one too.
"""
