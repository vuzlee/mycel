"""Push a job onto a topic. The entry point from business code is `services/enqueue.py`.

Picks the partition via the message key (usually a source name or domain id), so jobs for
the same object keep their order and do not overlap.

`acks=all` rather than the default: losing a report job leaves the user waiting for
something that never arrives, which costs far more than a few tens of milliseconds on send.

Call `context.inject()` before sending, otherwise the trace breaks right here.
"""
