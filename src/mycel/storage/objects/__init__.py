"""Large files: source PDFs, attachments, rendered reports. Backend: MinIO (S3 API).

  client.py    connection, URL signing
  buckets.py   bucket declarations and storage lifecycle
  files.py     put/get/delete, streaming reads and writes

Using the S3 API means moving to real S3 (or R2, or a GCS-compatible store) is an endpoint
and credential change — no code change.

Postgres holds a file's **metadata** (who owns it, which report it belongs to, its key in
the bucket); the bucket holds the **content**. Never the other way round.
"""
