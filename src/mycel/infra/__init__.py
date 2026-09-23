"""Everything that holds bytes on our behalf. Four backends, two lifetimes.

Durable — a record, survives a restart:

  postgres/    transactional state: the bronze/silver/gold layers, jobs, permissions
  vectors/     embeddings for knowledge base search (Qdrant)
  objects/     large files: source PDFs, rendered reports (MinIO, S3 API)

Ephemeral — in flight between processes, every key carries a TTL:

  redis/       a finished job's answer, a job's budget, a run's event stream

The line this package draws is not "kept forever" but "not our logic": a backend holds
bytes, it decides nothing. That is why `queue/` is not here — AMQP is a message sent to
someone, not a byte written down — and why Redis is, including its event streams: the
worker writes them and the API reads them back, with neither one calling the other.

Why four backends rather than putting everything in Postgres:

- **Vectors.** `pgvector` works, but at a few million vectors the HNSW index competes for
  RAM with the transactional workload on the same instance. Separated, the two scale
  independently.
- **Files.** Blobs in Postgres bloat the database, slow down backups, and every read pulls
  the whole file through a pooled connection. Object stores exist for this.
- **In-flight state.** An answer waiting to be collected is not a record; writing it to
  Postgres means a row whose only job is to be deleted.

Every SQL query, every vector query, every file operation lives here — not scattered through
domains or agents. Changing schema or changing backend means editing one place.
"""
