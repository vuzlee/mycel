"""Whether a base URL a person typed may be called from inside this deployment.

The worker sits inside the cluster, next to Postgres, Redis and the cloud's metadata
endpoint. A base URL is checked on save and again before every run, because the name it
holds can resolve somewhere else tomorrow.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import MycelError

#: Names that reach this deployment's own services without any DNS lookup.
_INTERNAL_SUFFIXES = (".local", ".internal", ".svc", ".cluster.local", ".localhost")


class BlockedUrl(MycelError):
    """The URL points somewhere a model call must not go."""


def _allowed_http(host: str, settings: Settings) -> bool:
    return host.lower() in {h.lower() for h in settings.model_http_hosts}


def check_shape(url: str, settings: Settings | None = None) -> str:
    """Scheme and host, without touching the network; returns the host."""
    cfg = settings or get_settings()
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not host:
        raise BlockedUrl("the base URL has no host")
    if parts.username or parts.password:
        raise BlockedUrl("the base URL may not carry a user or password")
    if parts.scheme == "http" and not _allowed_http(host, cfg):
        raise BlockedUrl(f"plain http to {host} is not allowed; use https")
    if parts.scheme not in ("http", "https"):
        raise BlockedUrl("the base URL must start with https://")
    if host.endswith(_INTERNAL_SUFFIXES) and not _allowed_http(host, cfg):
        raise BlockedUrl(f"{host} is an internal name")
    return host


def _private(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


async def _resolve(host: str) -> set[str]:
    try:
        found = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedUrl(f"{host} does not resolve") from exc
    return {str(info[4][0]) for info in found}


async def check(url: str, settings: Settings | None = None) -> None:
    """Refuse a URL whose host resolves to a private, loopback, link-local or metadata address.

    A host in `model_http_hosts` is trusted as written: that list is how a LAN model is let in.
    """
    cfg = settings or get_settings()
    host = check_shape(url, cfg)
    if _allowed_http(host, cfg):
        return
    addresses = await _resolve(host)
    if not addresses or any(_private(a) for a in addresses):
        raise BlockedUrl(f"{host} resolves to a private or internal address")
