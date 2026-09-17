"""The shared S3 client, and presigned URL signing.

Presigned URLs are the main reason to separate the object store: the API hands the client a
time-limited URL instead of reading the file and streaming it back itself. A 200MB file
never passes through the API process.
"""
