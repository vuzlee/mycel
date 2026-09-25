"""Several API keys for one provider, used in turn and benched when they run out.

Three Gemini keys in `.env` are three Google accounts, which is three free-tier quotas —
20 requests a day each. Held as one key, two of them are unreachable and the twenty-first
request of the day stops the system with forty requests still unspent.

**Round robin, not random and not first-until-broken.** The keys are not a primary and two
spares; they are equal parts of one quota, and preferring any of them throws away two
thirds. Turn-taking is also the version whose log can be read.

**Two kinds of 429 that must not be treated alike.** A rate limit means fifteen a minute was
too fast and the key is back in a minute. A daily quota means the key is gone until midnight
UTC. Bench an exhausted key for a minute and it returns, earns another 429, and the ring
becomes a spin that burns requests without one succeeding.

**The ring lives in the process.** Worker and API each keep their own, so the worst case is
each of them hitting a spent key once and remembering. Shared state would be new
infrastructure for something that heals within the day. It does not count requests to
predict exhaustion either: a counter we keep is a number that drifts from Google's.

Nothing here calls out. Choosing a key reads a list in memory, so `build_model` keeps its
promise that constructing an agent makes no network call.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from mycel.core.exceptions import ConfigError
from mycel.core.logging import get_logger

log = get_logger(__name__)

#: A rate limit is over in a minute. Long enough that the ring has moved on, short enough
#: that a key is not lost for the rest of an hour over one burst.
RATE_LIMIT_REST_S = 60


def _midnight_utc(now: datetime) -> datetime:
    """When a daily quota comes back.

    UTC, and this is the one place in the system that does not use the team's timezone: the
    quota belongs to Google and Google counts its day in UTC.
    """
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(slots=True)
class _Key:
    """One credential, and when it is allowed to be tried again."""

    value: str
    position: int
    rested_until: datetime | None = None

    def available(self, now: datetime) -> bool:
        return self.rested_until is None or self.rested_until <= now

    def label(self, total: int) -> str:
        """How this key is named in a log. Never the value."""
        return f"key #{self.position} of {total}"


class NoKeyAvailable(ConfigError):
    """Every key for this provider is spent, rate limited or dead.

    A `ConfigError` because that is what the caller already handles, and says how many keys
    were tried rather than which — a traceback goes into the logs.
    """


@dataclass(slots=True)
class KeyRing:
    """The keys for one provider, handed out in turn.

    Built once per provider per process and kept on `Settings`-derived state, not rebuilt
    per call: a ring that forgets which key was spent is not a ring.
    """

    provider: str
    env_var: str
    _keys: list[_Key] = field(default_factory=list)
    _next: int = 0

    @classmethod
    def of(cls, provider: str, env_var: str, values: list[str]) -> "KeyRing":
        """A ring over these key values, with duplicates dropped.

        Copying a key twice into the list is an ordinary mistake, and the result is two
        turns aimed at the same quota — so it is collapsed rather than honoured.
        """
        seen: set[str] = set()
        keys: list[_Key] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            keys.append(_Key(value=value, position=len(keys) + 1))
        return cls(provider=provider, env_var=env_var, _keys=keys)

    def __len__(self) -> int:
        return len(self._keys)

    def take(self, now: datetime | None = None) -> str:
        """The next usable key, or raise.

        Walks from wherever the last call left off, so the quotas are spent evenly rather
        than the first key being burned down before the second is touched.
        """
        if not self._keys:
            raise NoKeyAvailable(f"{self.env_var} is not set, but a {self.provider} model needs it")

        moment = now or datetime.now(UTC)
        total = len(self._keys)
        for offset in range(total):
            key = self._keys[(self._next + offset) % total]
            if key.available(moment):
                self._next = (self._next + offset + 1) % total
                return key.value

        raise NoKeyAvailable(
            f"all {total} {self.env_var} keys are rate limited or out of quota; "
            f"the earliest returns at {self._earliest().isoformat()}"
        )

    def bench(self, value: str, until: datetime) -> None:
        """Stop handing out this key until the given moment.

        Takes a moment rather than a duration so the caller — which is the only thing that
        read the provider's error — decides whether this was a minute or a day.
        """
        for key in self._keys:
            if key.value != value:
                continue
            key.rested_until = until
            log.warning(
                "api key benched",
                extra={
                    "provider": self.provider,
                    "key": key.label(len(self._keys)),
                    "until": until.isoformat(),
                },
            )
            return

    def bench_rate_limited(self, value: str, now: datetime | None = None) -> None:
        """Fifteen a minute was too fast. Back shortly."""
        moment = now or datetime.now(UTC)
        self.bench(value, moment + timedelta(seconds=RATE_LIMIT_REST_S))

    def bench_exhausted(self, value: str, now: datetime | None = None) -> None:
        """The day's quota is gone. Back at midnight UTC and not before."""
        moment = now or datetime.now(UTC)
        self.bench(value, _midnight_utc(moment))

    def bench_rejected(self, value: str, now: datetime | None = None) -> None:
        """The key itself is refused — revoked, or mistyped.

        Benched for a century rather than removed, so the position numbers in the log keep
        meaning the same thing for the life of the process. Retrying a dead key is waste on
        every pass.
        """
        moment = now or datetime.now(UTC)
        self.bench(value, moment + timedelta(days=36500))

    def _earliest(self) -> datetime:
        """When the ring next has something to hand out. Only read when nothing does."""
        return min(key.rested_until for key in self._keys if key.rested_until is not None)
