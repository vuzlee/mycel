#!/usr/bin/env bash
#
# The ingest worker, restarted each time it exits. It exits on purpose after
# ingest_worker_max_jobs documents, because docling keeps native memory it never frees.

while true; do
  uv run python -m mycel.queue.consumer --queue ingest
  sleep 1
done
