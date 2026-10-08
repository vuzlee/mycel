"""The gateway's daily-quota rule, loaded from config/litellm/ without litellm installed."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "mycel_callbacks", ROOT / "config" / "litellm" / "mycel_callbacks.py"
)
assert spec and spec.loader
callbacks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(callbacks)


class TestWhichQuota:
    def test_the_daily_quota_is_recognized(self) -> None:
        body = '{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}'
        assert callbacks.is_daily_quota(body)

    def test_the_per_minute_quota_is_not(self) -> None:
        body = '{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}'
        assert not callbacks.is_daily_quota(body)

    def test_a_plain_rate_limit_is_not(self) -> None:
        assert not callbacks.is_daily_quota("429 Too Many Requests")


class TestUntilReset:
    def test_waits_until_midnight_pacific(self) -> None:
        # 07:00 UTC is 00:00 PDT, so the next reset is a full day away.
        assert callbacks.seconds_until_reset(datetime(2026, 10, 5, 7, 0, tzinfo=UTC)) == 86400

    def test_one_hour_before_reset(self) -> None:
        assert callbacks.seconds_until_reset(datetime(2026, 10, 5, 6, 0, tzinfo=UTC)) == 3600

    def test_never_less_than_a_minute(self) -> None:
        moment = datetime(2026, 10, 5, 6, 59, 59, tzinfo=UTC)
        assert callbacks.seconds_until_reset(moment) == 60.0
