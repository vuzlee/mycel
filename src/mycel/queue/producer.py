"""Publish a job to an exchange. The entry point from business code is `services/enqueue.py`.

The routing key picks the queue, and therefore which pool of workers takes the job — keeping
long bulk syncs off the queue that interactive report jobs wait on.

Publish with `delivery_mode=PERSISTENT` to a durable queue, and with publisher confirms on:
losing a report job leaves the user waiting for something that never arrives, which costs far
more than a few tens of milliseconds on publish. Both are off by default; a message published
without them is dropped silently when the broker restarts.

Call `context.inject()` before publishing, otherwise the trace breaks right here.
"""
