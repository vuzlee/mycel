"""Large files in an S3-compatible store (MinIO in dev). Postgres keeps the metadata.

client.py    session, presigned URLs
buckets.py   bucket names, created on first use
files.py     streamed put / download / delete
"""
