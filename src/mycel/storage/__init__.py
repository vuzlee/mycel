"""Three stores, three kinds of data. All access goes through here.

  postgres/    transactional state: the raw/silver/gold layers, jobs, permissions
  vectors/     embeddings for knowledge base search (Qdrant)
  objects/     large files: source PDFs, rendered reports (MinIO, S3 API)
  redis/       not a record: short-lived things crossing a process boundary, all with a TTL

Why three stores rather than putting everything in Postgres:

- **Vectors.** `pgvector` works, but at a few million vectors the HNSW index competes for
  RAM with the transactional workload on the same instance. Separated, the two scale
  independently.
- **Files.** Blobs in Postgres bloat the database, slow down backups, and every read pulls
  the whole file through a pooled connection. Object stores exist for this.

Every SQL query, every vector query, every file operation lives here — not scattered through
pipelines or agents. Changing schema or changing store means editing one place.
"""
