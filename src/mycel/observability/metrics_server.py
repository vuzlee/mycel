"""Minimal asyncio `/metrics` server, one per process, off the public app port."""

import asyncio
from contextlib import suppress

from mycel.core.logging import get_logger
from mycel.observability.metrics import render

log = get_logger(__name__)

READ_TIMEOUT_SECONDS = 5.0

_NOT_FOUND = b"HTTP/1.1 404 Not Found\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """One request, one response, close. Keep-alive would need a parser."""
    try:
        parts = (await asyncio.wait_for(reader.readline(), timeout=READ_TIMEOUT_SECONDS)).split(
            b" "
        )
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
    """Start listening. `host` has no default: the bound interface is the only access control."""
    server = await asyncio.start_server(_handle, host, port)
    log.info("metrics endpoint listening", extra={"port": port, "host": host})
    return server
