"""Where a finished thing goes out. One direction only.

    calendar.py   due dates, as all-day events somebody can glance at on a phone

Nothing here is ever read back. An event has a start and an end and nothing else — no
status, no parent, no estimate — so anything read out of it would be a worse copy of
`gold.work_item`.

`telegram.py` was the other half until batch 033. Its only caller was the summary endpoint
that batch deleted, and there is no plan for a chat notification, so it went with it.
`publish_due_dates` has no caller either, and is kept on purpose: the next batch reaches it
as a tool, so the chatbot can be asked to put a deadline on the calendar.

Optional, and it fails quietly: a deployment with nothing configured runs exactly as
before, and every failure in here is logged rather than raised.

`calendar.py` sits here rather than in a package of its own because `mycel.calendar` would
be one careless relative import away from shadowing the standard library's.
"""
