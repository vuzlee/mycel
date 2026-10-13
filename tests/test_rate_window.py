"""The window slides: a burst split across a minute's edge still counts as one burst."""

from typing import Any

import pytest

from mycel.infra.redis import rate

pytestmark = pytest.mark.anyio

#: A minute boundary, so `EDGE - 1` is the old minute's last second.
EDGE = 1_800_000_000 // rate.WINDOW_SECONDS * rate.WINDOW_SECONDS + rate.WINDOW_SECONDS


class Store:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def pipeline(self, transaction: bool) -> "Pipe":
        return Pipe(self)


class Pipe:
    def __init__(self, store: Store) -> None:
        self.store, self.ops = store, list[Any]()

    async def __aenter__(self) -> "Pipe":
        return self

    async def __aexit__(self, *_: Any) -> None: ...

    def incr(self, name: str) -> None:
        self.ops.append(("incr", name))

    def expire(self, name: str, seconds: int, nx: bool) -> None:
        self.ops.append(("expire", name))

    def get(self, name: str) -> None:
        self.ops.append(("get", name))

    async def execute(self) -> list[Any]:
        out: list[Any] = []
        for op, name in self.ops:
            if op == "incr":
                self.store.values[name] = self.store.values.get(name, 0) + 1
                out.append(self.store.values[name])
            elif op == "get":
                found = self.store.values.get(name)
                out.append(None if found is None else str(found))
            else:
                out.append(True)
        return out


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    fake = Store()

    async def client() -> Store:
        return fake

    monkeypatch.setattr(rate, "get_client", client)
    return fake


async def _burst(n: int, at: float) -> list[rate.Verdict]:
    return [await rate.hit("login", "1.2.3.4", 10, now=at) for _ in range(n)]


async def test_ten_before_the_edge_and_one_after_is_refused(store: Store) -> None:
    """A fixed window let 10 at :59 and 10 more at :00 through."""
    assert all(v.allowed for v in await _burst(10, EDGE - 1))
    after = await _burst(1, EDGE + 1)
    assert after[0].allowed is False
    assert 1 <= after[0].retry_after <= rate.WINDOW_SECONDS


async def test_the_old_minute_fades_as_the_window_moves(store: Store) -> None:
    await _burst(10, EDGE - 1)
    # Half way into the new minute, half the old one still counts: room for 5.
    later = await _burst(6, EDGE + rate.WINDOW_SECONDS / 2)
    assert [v.allowed for v in later] == [True] * 5 + [False]


async def test_a_quiet_minute_before_means_the_full_limit(store: Store) -> None:
    verdicts = await _burst(11, EDGE + 5)
    assert [v.allowed for v in verdicts] == [True] * 10 + [False]
    assert verdicts[-1].retry_after == rate.WINDOW_SECONDS - 5


async def test_retry_after_is_when_the_weighted_count_drops_under(store: Store) -> None:
    await _burst(10, EDGE - 1)
    refused = (await _burst(1, EDGE + 1))[0]
    # The new-minute hit counts 1; the old ten must fade to 9: 10 × (1 − t) ≤ 9 → t ≥ 0.1.
    assert refused.retry_after == 6 - 1
