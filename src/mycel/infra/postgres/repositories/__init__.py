"""One repository per schema: `bronze.py`, `silver.py`, `gold.py`, `app.py`.

Split by schema rather than by table, because access rules attach to the schema: `sources/`
may only write bronze, `etl/` reads below and writes above, agents read gold only, and
nothing outside `services/auth.py` has any business in `app`. Splitting the files this way
makes a violation visible on the import line.
"""
