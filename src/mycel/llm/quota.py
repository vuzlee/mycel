"""How long a key that failed should sit out before it is tried again."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

#: Google names the quota window in `quotaId`: `GenerateRequestsPerDayPerProjectPerModel`.
DAILY_MARKERS = ("perday", "requestsperday", "per_day")
PACIFIC = ZoneInfo("America/Los_Angeles")

#: A burst limit clears within a minute; a rejected key needs a person to fix it.
BURST_SECONDS = 60
REJECTED_SECONDS = 600


def is_daily_quota(error: str) -> bool:
    text = error.lower().replace(" ", "")
    return any(marker in text for marker in DAILY_MARKERS)


def seconds_until_reset(now: datetime | None = None) -> int:
    """Google's daily quota resets at midnight Pacific time."""
    moment = (now or datetime.now(UTC)).astimezone(PACIFIC)
    midnight = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((midnight - moment).total_seconds()))


def cooldown_seconds(status: int, error: str) -> int:
    if status in (401, 403):
        return REJECTED_SECONDS
    return seconds_until_reset() if is_daily_quota(error) else BURST_SECONDS
