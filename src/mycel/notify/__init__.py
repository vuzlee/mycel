"""Where a finished thing goes out, and — since batch 051 — one thing that comes back in.

    calendar.py   one person's own calendar: what is on it, and one more thing on it
    mail.py       one plain-text message over SMTP, which is how a password is recovered

`calendar.py` was one-way until batch 051, mirroring Jira due dates onto a calendar of the
deployment's own on a timer. Nothing ever called it, and the timer was the only reason it
authenticated as a service account; asking "what have I got this afternoon" has the person
right there to consent, so the sync went and per-user OAuth took its place. "What is due
this week" is answered by `summariser`, which has read Jira since batch 017.

`telegram.py` was the other half until batch 033. Its only caller was the summary endpoint
that batch deleted, and there is no plan for a chat notification, so it went with it.

`mail.py` still fails loudly and `calendar.py` now does too: both have somebody waiting, and
a reset link that never arrives or an empty afternoon that was really a disconnected account
is worse than an error saying so.

`calendar.py` sits here rather than in a package of its own because `mycel.calendar` would
be one careless relative import away from shadowing the standard library's.
"""
