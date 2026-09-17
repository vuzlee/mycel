"""Tiered retry and dead-letter — on Kafka these must be built by hand.

Do not seek back to an old offset: one bad job would block every job behind it in the same
partition. Instead move the job to another topic and commit onward, so the partition keeps
flowing:

    jobs            first attempt
    jobs.retry.1m   wait ~1 minute, then retry
    jobs.retry.10m  longer
    jobs.dlq        out of attempts — kept for inspection, not silently dropped

The retry count is tracked in the message headers, since Kafka does not count for us.

The wait is implemented by the retry topic's consumer sleeping until the message is old
enough — Kafka has no delayed messages like RabbitMQ.

Trace context travels in the headers across all four topics, so a job that lands in
`jobs.dlq` can still have its trace reopened from the moment the user pressed the button.
"""
