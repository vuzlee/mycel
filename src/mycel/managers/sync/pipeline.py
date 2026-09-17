"""The sync domain's business chain.

  sync_source(name, time_window)
    1. fetch service      call sources/, write the raw payload down to raw
    2. transform service  run etl/ raw -> silver -> gold
    3. check service      run etl/checks/; on failure stop, do not write the layer above

Every step is idempotent — re-running the same time window gives the same result.
"""
