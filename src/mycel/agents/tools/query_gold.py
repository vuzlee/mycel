"""Tool that queries the gold layer.

Goes through `storage/` rather than writing SQL itself, and reads gold only — agents never
touch raw/silver. There is a cap on rows returned: one table-scanning question would blow
up the context and burn money for nothing.
"""
