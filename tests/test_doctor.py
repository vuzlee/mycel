"""`doctor`, and the distinction that justifies it.

The report has three states and only two of them are obvious. **BROKEN and OFF both mean a
feature is unavailable**, and from outside they look identical — an absent `rag_search`
behaves exactly like a broken one. Somebody who has just cloned the repo cannot tell whether
to go fixing or to relax, and that is the question this command exists to answer.

So the tests here are mostly about which of the two a check lands on, and about the one
rule that follows from it: a probe is never attempted for something that is simply not
configured. Attempting it would turn every unconfigured feature into a connection error.

No network and no containers: every probe is replaced.
"""

import asyncio

import pytest

from mycel.core import doctor
from mycel.core.config import Settings
from mycel.core.doctor import Check, State

pytestmark = pytest.mark.anyio


def _settings(**kwargs: object) -> Settings:
    """Settings built from nothing but the arguments — no .env, no YAML overlay."""
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


class TestProbeIsNotRunWhenThereIsNothingToProbe:
    async def test_a_missing_reason_means_off_and_no_call(self) -> None:
        """OFF is decided before anything connects: an unconfigured feature must not be
        reported as a connection failure, because those read as something to fix."""
        called = False

        async def probe() -> str:
            nonlocal called
            called = True
            return "should not happen"

        check = await doctor._probe("x", "G", probe, missing="not configured")

        assert check.state is State.OFF
        assert not called, "a probe ran for something that is not configured"

    async def test_a_probe_that_answers_is_ok(self) -> None:
        async def probe() -> str:
            return "connected, 3 tables"

        check = await doctor._probe("x", "G", probe, missing=None)
        assert (check.state, check.detail) == (State.OK, "connected, 3 tables")

    async def test_a_probe_that_raises_is_broken_and_keeps_the_message(self) -> None:
        async def probe() -> str:
            raise ConnectionRefusedError("connection refused on port 5433")

        check = await doctor._probe("x", "G", probe, missing=None)
        assert check.state is State.BROKEN
        assert "5433" in check.detail

    async def test_an_empty_error_still_says_something(self) -> None:
        """`str(OSError())` is empty, and a report line with nothing on it is worse than
        a wrong one — the class name is usually enough to know what to do."""

        async def probe() -> str:
            raise OSError()

        check = await doctor._probe("x", "G", probe, missing=None)
        assert check.detail == "OSError"

    async def test_a_hang_is_broken_rather_than_a_hang(self) -> None:
        """A doctor that waits forever on a dead host is a doctor nobody runs twice."""

        async def probe() -> str:
            await asyncio.sleep(10)
            return "never"

        check = await doctor._probe("x", "G", probe, missing=None, timeout=0.05)
        assert check.state is State.BROKEN
        assert "no answer" in check.detail


class TestWhatCountsAsConfigured:
    def test_an_absent_tool_is_off_and_says_what_is_missing(self) -> None:
        """The detail names the tool, because 'not configured' alone leaves the reader to
        work out which capability they just lost."""
        checks = doctor._declared(_settings(tavily_api_key=None))
        search = next(c for c in checks if c.name == "web search")
        assert search.state is State.OFF
        assert "web_search" in search.detail

    def test_the_calendar_needs_all_three_keys(self) -> None:
        """Two of three is not partly working: the consent round fails at the end, after
        the person has already agreed to something."""
        partial = _settings(google_client_id="id", google_client_secret="secret")
        check = next(c for c in doctor._declared(partial) if c.name == "calendar & mail")
        assert check.state is State.OFF


class TestTheOpenFrontDoor:
    def test_open_registration_is_reported_broken(self) -> None:
        """The default is that anyone who can reach the URL gets an account. Right on a
        laptop, wrong on a company network — and nobody reads a setting they do not know
        exists, which is the whole reason this line is in the report."""
        checks = doctor._declared(_settings())
        who = next(c for c in checks if c.name == "who may sign up")
        assert who.state is State.BROKEN
        assert "ANYONE" in who.detail

    def test_an_invite_code_closes_it(self) -> None:
        checks = doctor._declared(_settings(registration_invite_code="s3cret"))
        who = next(c for c in checks if c.name == "who may sign up")
        assert who.state is State.OK
        assert "s3cret" not in who.detail, "the report must not print the code"

    def test_a_domain_allowlist_closes_it(self) -> None:
        checks = doctor._declared(_settings(registration_allowed_domains="acme.com"))
        who = next(c for c in checks if c.name == "who may sign up")
        assert (who.state, "acme.com" in who.detail) == (State.OK, True)


class TestTheReport:
    def test_off_alone_is_not_a_failure(self) -> None:
        """`doctor` exits non-zero on BROKEN so it can gate a deploy. If OFF counted, every
        deployment that skipped a feature would fail its own check."""
        checks = [
            Check("G", "a", State.OK, ""),
            Check("G", "b", State.OFF, ""),
        ]
        assert "Nothing broken" in doctor.render(checks)

    def test_broken_is_counted(self) -> None:
        checks = [Check("G", "a", State.BROKEN, "no"), Check("G", "b", State.OFF, "")]
        rendered = doctor.render(checks)
        assert "1 broken, 1 off" in rendered

    def test_groups_keep_their_order(self) -> None:
        """Stores first, then what depends on them. A report sorted alphabetically reads
        as a list rather than as a sequence of things to check."""
        checks = [
            Check("STORES", "a", State.OK, ""),
            Check("TOOLS", "b", State.OK, ""),
            Check("STORES", "c", State.OK, ""),
        ]
        rendered = doctor.render(checks)
        assert rendered.index("STORES") < rendered.index("TOOLS")
        assert rendered.count("STORES") == 1, "a group must appear once"


class TestTheGateway:
    """Every model is behind LiteLLM, so its model list is the one model check."""

    async def test_it_lists_what_the_gateway_serves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx2

        def handler(request: httpx2.Request) -> httpx2.Response:
            assert request.url.path == "/v1/models"
            return httpx2.Response(200, json={"data": [{"id": "b"}, {"id": "a"}, {"id": "a"}]})

        real = httpx2.AsyncClient
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            lambda **kw: real(transport=httpx2.MockTransport(handler), **kw),
        )
        detail = await doctor._gateway(_settings(litellm_base_url="http://gw:4000"))
        assert detail == "2 models: a, b"

    async def test_a_gateway_with_no_model_is_broken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx2

        real = httpx2.AsyncClient
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            lambda **kw: real(
                transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json={"data": []})),
                **kw,
            ),
        )
        with pytest.raises(RuntimeError, match="no model"):
            await doctor._gateway(_settings())


class TestTheUpstreams:
    """MYC-103: the gateway can be up while the LAN proxy behind it is down."""

    def _info(self, *pairs: tuple[str, str | None]) -> dict[str, object]:
        return {
            "data": [
                {"model_name": name, "litellm_params": {"api_base": base} if base else {}}
                for name, base in pairs
            ]
        }

    async def test_an_answering_upstream_is_ok_even_on_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx2

        async def info(settings: Settings, path: str) -> dict[str, object]:
            return self._info(("claude", "http://proxy/v1"), ("gemini", None))

        real = httpx2.AsyncClient
        monkeypatch.setattr(doctor, "_ask_gateway", info)
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            lambda **kw: real(transport=httpx2.MockTransport(lambda r: httpx2.Response(401)), **kw),
        )
        assert await doctor._upstreams(_settings()) == "1 answering: claude"

    async def test_a_silent_upstream_is_broken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def info(settings: Settings, path: str) -> dict[str, object]:
            return self._info(("claude", "http://127.0.0.1:9/v1"))

        monkeypatch.setattr(doctor, "_ask_gateway", info)
        with pytest.raises(RuntimeError, match="not answering: claude"):
            await doctor._upstreams(_settings())

    async def test_hosted_apis_are_not_probed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def info(settings: Settings, path: str) -> dict[str, object]:
            return self._info(("gemini", None))

        monkeypatch.setattr(doctor, "_ask_gateway", info)
        assert await doctor._upstreams(_settings()) == "no self-hosted upstream"
