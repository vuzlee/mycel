#!/usr/bin/env bash
#
# The ingest worker, restarted each time it exits. It exits on purpose after
# ingest_worker_max_jobs documents, because docling keeps native memory it never frees.
#
# Capped so a PDF cannot take the machine: INGEST_CPUS cores, INGEST_MEM of RAM, low
# priority. Over the memory cap the worker is killed, restarted here, and the job retried.

set -uo pipefail

INGEST_CPUS=${INGEST_CPUS:-2}
INGEST_MEM=${INGEST_MEM:-4G}
export OMP_NUM_THREADS=$INGEST_CPUS MKL_NUM_THREADS=$INGEST_CPUS TORCH_NUM_THREADS=$INGEST_CPUS

cap=()
if systemd-run --user --scope --quiet true 2>/dev/null; then
  cap=(systemd-run --user --scope --quiet -p "MemoryMax=$INGEST_MEM" -p "CPUQuota=${INGEST_CPUS}00%")
else
  echo "!! systemd-run unavailable: ingest runs without CPU/RAM caps" >&2
fi

while true; do
  "${cap[@]}" nice -n 10 uv run python -m mycel.queue.consumer --queue ingest
  sleep 1
done
