"""Where a finished thing goes out. One direction only.

    telegram.py   a finished summary's headline, and a link back to the full one
    calendar.py   due dates, as all-day events somebody can glance at on a phone

Nothing here is ever read back. Telegram stopped being a source in batch 016 and Calendar
was never one: an event has a start and an end and nothing else — no status, no parent, no
estimate — so anything read out of it would be a worse copy of `gold.work_item`.

Both are optional. A deployment with neither configured runs exactly as before, which is
why every failure in here is logged and none is raised: a notification that fails must not
fail the job that produced it.

`calendar.py` sits here rather than in a package of its own because `mycel.calendar` would
be one careless relative import away from shadowing the standard library's.
"""
