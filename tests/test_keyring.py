"""Several keys for one provider, and the benching rules that make them worth having.

The reason this exists is arithmetic: three Gemini keys in `.env` are three Google accounts
and so three free-tier quotas, twenty requests a day each. Held as one key, two of them are
unreachable.

The rule worth guarding hardest is that **the two kinds of 429 are not alike**. A rate limit
is over in a minute; a daily quota is not. Treat them alike and the ring spins through three
keys all day without one request succeeding — which looks, from outside, exactly like having
no keys at all.
"""

from datetime import UTC, datetime, timedelta

import pytest

from mycel.agents.core import model_builder
from mycel.core.config import Settings
from mycel.llm.keyring import KeyRing, NoKeyAvailable

NOON = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def ring(*values: str) -> KeyRing:
    return KeyRing.of("google", "GEMINI_API_KEYS", list(values))


class TestTakingKeysInTurn:
    def test_three_keys_are_spent_evenly(self) -> None:
        """Round robin, not first-until-broken: the keys are three equal parts of one
        quota, and preferring any of them throws away two thirds."""
        keys = ring("a", "b", "c")
        assert [keys.take(NOON) for _ in range(4)] == ["a", "b", "c", "a"]

    def test_duplicates_are_collapsed(self) -> None:
        """The same key twice is two turns aimed at the same quota."""
        keys = ring("a", "a", "b")
        assert len(keys) == 2

    def test_no_keys_says_which_variable_is_missing(self) -> None:
        with pytest.raises(NoKeyAvailable, match="GEMINI_API_KEYS"):
            ring().take(NOON)


class TestTheTwoKindsOf429:
    def test_a_rate_limited_key_comes_back_within_the_minute(self) -> None:
        keys = ring("a", "b")
        keys.bench_rate_limited("a", NOON)

        assert keys.take(NOON) == "b"
        assert keys.take(NOON + timedelta(seconds=90)) in {"a", "b"}
        assert "a" in {keys.take(NOON + timedelta(seconds=90)) for _ in range(3)}

    def test_an_exhausted_key_is_not_tried_again_that_day(self) -> None:
        """The whole point. A daily quota benched for a minute returns, earns another 429,
        and three keys become a spin that burns requests without one succeeding."""
        keys = ring("a", "b")
        keys.bench_exhausted("a", NOON)

        later = NOON + timedelta(hours=11)
        assert {keys.take(later) for _ in range(5)} == {"b"}

    def test_an_exhausted_key_returns_at_midnight_utc(self) -> None:
        """UTC, because the quota belongs to Google and Google counts its day in UTC."""
        keys = ring("a")
        keys.bench_exhausted("a", NOON)

        with pytest.raises(NoKeyAvailable):
            keys.take(NOON + timedelta(hours=11, minutes=59))
        assert keys.take(datetime(2026, 9, 26, 0, 0, tzinfo=UTC)) == "a"

    def test_a_rejected_key_is_gone_for_the_process(self) -> None:
        """Revoked or mistyped: no amount of waiting helps, and retrying it is waste on
        every pass."""
        keys = ring("a", "b")
        keys.bench_rejected("a", NOON)

        assert {keys.take(NOON + timedelta(days=30)) for _ in range(4)} == {"b"}

    def test_every_key_spent_says_how_many_and_when_one_returns(self) -> None:
        keys = ring("a", "b", "c")
        for value in ("a", "b", "c"):
            keys.bench_exhausted(value, NOON)

        with pytest.raises(NoKeyAvailable, match="all 3"):
            keys.take(NOON)


class TestKeysStayOutOfTheLogs:
    def test_a_benched_key_is_logged_by_position(self, caplog: pytest.LogCaptureFixture) -> None:
        """Grepping a failed run's logs must find no character of any key."""
        secret = "AQ.Ab8_this_would_be_a_real_credential"
        keys = ring(secret, "b")

        with caplog.at_level("WARNING"):
            keys.bench_exhausted(secret, NOON)

        assert caplog.records, "benching a key is worth a line"
        record = caplog.records[0]
        assert secret not in caplog.text
        assert secret not in str(record.__dict__), "not in a structured field either"
        assert record.key == "key #1 of 2", "the position is what identifies it"


class TestTheRingReachesTheModelBuilder:
    @pytest.fixture(autouse=True)
    def _fresh_rings(self) -> None:
        model_builder.reset_key_rings()

    def test_consecutive_builds_use_consecutive_keys(self) -> None:
        env = Settings(gemini_api_keys="one,two,three")
        keys = model_builder.key_ring("google", env)
        assert [keys.take() for _ in range(3)] == ["one", "two", "three"]

    def test_the_singular_name_still_works(self) -> None:
        """No deployment has to change to keep running."""
        env = Settings(gemini_api_key="only-one")
        assert model_builder.key_ring("google", env).take() == "only-one"


class TestWhichFailuresBenchAKey:
    @pytest.fixture(autouse=True)
    def _fresh_rings(self) -> None:
        model_builder.reset_key_rings()

    def _model(self) -> object:
        env = Settings(gemini_api_keys="one,two")
        return model_builder.build_model("cloud:gemini-3.5-flash-lite", settings=env)

    def test_a_daily_quota_429_benches_until_midnight(self) -> None:
        from pydantic_ai.exceptions import ModelHTTPError

        model = self._model()
        model_builder.note_failure(
            model,
            ModelHTTPError(429, "gemini-3.5-flash-lite", body="Quota exceeded for quota metric"),
        )

        keys = model_builder.key_ring("google", Settings(gemini_api_keys="one,two"))
        assert {keys.take() for _ in range(4)} == {"two"}

    def test_a_500_leaves_the_ring_alone(self) -> None:
        """Somebody else's outage is not this key's fault, and benching a healthy key over
        it throws quota away for nothing."""
        from pydantic_ai.exceptions import ModelHTTPError

        model = self._model()
        model_builder.note_failure(model, ModelHTTPError(503, "gemini-3.5-flash-lite", body="busy"))

        keys = model_builder.key_ring("google", Settings(gemini_api_keys="one,two"))
        assert {keys.take() for _ in range(4)} == {"one", "two"}
