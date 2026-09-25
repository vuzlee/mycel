"""A port to scrape, for the two processes that have none.

The api already serves HTTP, so it exposes `/metrics` as a route. The worker and the
scheduler are plain asyncio processes with nothing listening — and they are where the work
actually happens: jobs run in the worker, syncs run in the scheduler.

**Measuring only the api is measuring half the system.** Requests come and go looking
healthy while every job dies, because the dying part is in a process nobody asked.

So: the smallest possible HTTP server, one route, no framework. `prometheus_client` ships
one, but it starts a thread with its own WSGI server; an asyncio process already has a
loop, and `asyncio.start_server` costs less than a second runtime.

**Loopback by default, and the interface is a setting.** A metrics endpoint has no
authentication — Prometheus carries no session token — so the only thing keeping it
private is what it is bound to. A dev machine gets loopback and nothing else can reach it;
compose sets `METRICS_HOST` to the container's own address, which is reachable from the
scraper and from nothing outside the network. Neither case wants the port published to the
internet.
"""

import asyncio
from contextlib import suppress

from mycel.core.logging import get_logger
from mycel.observability.metrics import render

log = get_logger(__name__)

_NOT_FOUND = b"HTTP/1.1 404 Not Found\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """One request, one response, close. Keep-alive would need a parser."""
    try:
        parts = (await asyncio.wait_for(reader.readline(), timeout=5.0)).split(b" ")
        target = parts[1].split(b"?")[0] if len(parts) > 1 else b""
        if target != b"/metrics":
            writer.write(_NOT_FOUND)
        else:
            body, content_type = render()
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                + f"content-type: {content_type}\r\n".encode()
                + f"content-length: {len(body)}\r\n".encode()
                + b"connection: close\r\n\r\n"
                + body
            )
        await writer.drain()
    except (TimeoutError, ConnectionError):
        pass  # A scraper that hung up mid-request is not an event worth a log line.
    finally:
        writer.close()
        with suppress(ConnectionError):
            await writer.wait_closed()


async def serve_metrics(port: int, host: str) -> asyncio.Server:
    """Start listening, and hand back the server so the caller can close it.

    `host` has no default on purpose: which interface this is reachable on is the whole of
    its security, so every caller states it and reads it from settings.
    """
    server = await asyncio.start_server(_handle, host, port)
    log.info("metrics endpoint listening", extra={"port": port, "host": host})
    return server
