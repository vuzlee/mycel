"""A base URL a person typed cannot reach inside the deployment."""

import pytest

from mycel.core.config import Settings
from mycel.services import url_guard
from mycel.services.url_guard import BlockedUrl

pytestmark = pytest.mark.anyio

LAN = Settings(model_http_hosts=("ollama", "10.1.10.35"))


def _resolves_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    async def fake(host: str) -> set[str]:
        return set(addresses)

    monkeypatch.setattr(url_guard, "_resolve", fake)


class TestShape:
    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com",
            "http://example.com/v1",
            "https://user:pw@example.com",
            "https:///v1",
            "https://redis.svc/v1",
            "https://metadata.google.internal/",
        ],
    )
    def test_refused(self, url: str) -> None:
        with pytest.raises(BlockedUrl):
            url_guard.check_shape(url, Settings())

    def test_http_to_a_listed_lan_host(self) -> None:
        assert url_guard.check_shape("http://ollama:11434/v1", LAN) == "ollama"


class TestResolution:
    @pytest.mark.parametrize(
        "address",
        ["127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.9", "169.254.169.254", "::1", "fd00::1"],
    )
    async def test_a_private_address_is_refused(
        self, address: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _resolves_to(monkeypatch, address)
        with pytest.raises(BlockedUrl, match="private"):
            await url_guard.check("https://looks-public.example/v1", Settings())

    async def test_one_private_answer_among_public_ones_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DNS rebinding answers with several addresses; any internal one is enough."""
        _resolves_to(monkeypatch, "142.250.1.1", "10.0.0.5")
        with pytest.raises(BlockedUrl):
            await url_guard.check("https://rebind.example/v1", Settings())

    async def test_a_public_address_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _resolves_to(monkeypatch, "142.250.1.1")
        await url_guard.check("https://generativelanguage.googleapis.com/v1beta/openai", Settings())

    async def test_a_listed_lan_host_is_trusted_as_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _resolves_to(monkeypatch, "10.1.10.35")
        await url_guard.check("http://10.1.10.35:20128/v1", LAN)

    async def test_an_ipv4_mapped_v6_loopback_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _resolves_to(monkeypatch, "::ffff:127.0.0.1")
        with pytest.raises(BlockedUrl):
            await url_guard.check("https://mapped.example/v1", Settings())
