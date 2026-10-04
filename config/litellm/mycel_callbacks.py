"""Bench a key that spent its daily quota until the quota resets, not for one minute.

LiteLLM cools a deployment down for `cooldown_time` whatever the 429 said. Gemini's
per-day quota answers 429 with a short `retryDelay` too, so a spent key would be retried
every minute until midnight. The body names the window in `quotaId`
(`...PerDay...` vs `...PerMinute...`); this reads it and extends the cooldown.

Loaded by the gateway through `litellm_settings.callbacks` in config.yaml.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # imported by the repo's tests, where litellm is not installed
    CustomLogger = object  # type: ignore[misc,assignment]

#: Gemini names the quota window in `quotaId`: `GenerateRequestsPerDayPerProjectPerModel`.
DAILY_MARKERS = ("perday", "requestsperday", "per_day")
PACIFIC = ZoneInfo("America/Los_Angeles")


def is_daily_quota(error: str) -> bool:
    """Whether a 429 is the day's quota rather than a burst."""
    text = error.lower().replace(" ", "")
    return any(marker in text for marker in DAILY_MARKERS)


def seconds_until_reset(now: datetime | None = None) -> float:
    """Gemini's daily quota resets at midnight Pacific time."""
    moment = (now or datetime.now(UTC)).astimezone(PACIFIC)
    midnight = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60.0, (midnight - moment).total_seconds())


class DailyQuotaCooldown(CustomLogger):  # type: ignore[misc,valid-type]
    async def async_log_failure_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        error = str(kwargs.get("exception") or kwargs.get("traceback_exception") or "")
        if not is_daily_quota(error):
            return
        deployment = (kwargs.get("litellm_params") or {}).get("model_info", {}).get("id")
        if not deployment:
            return
        from litellm.proxy.proxy_server import llm_router

        if llm_router is None:
            return
        llm_router.cooldown_cache.add_deployment_to_cooldown(
            model_id=deployment,
            original_exception=kwargs.get("exception"),
            exception_status=429,
            cooldown_time=seconds_until_reset(),
        )


daily_quota_cooldown = DailyQuotaCooldown()
