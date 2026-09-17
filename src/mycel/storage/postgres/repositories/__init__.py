"""One repository per data layer: `raw.py`, `silver.py`, `gold.py`.

Split by layer rather than by table, because access rules attach to the layer: `sources/`
may only write raw, `etl/` reads below and writes above, agents read gold only. Splitting
the files this way makes a violation visible on the import line.
"""
