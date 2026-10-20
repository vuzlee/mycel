"""The model gets today's date at the top of every prompt, in the asker's zone."""

from datetime import datetime
from zoneinfo import ZoneInfo

from mycel.agents.core.runner import dated
from mycel.agents.tools.web_search import stale_year

ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def test_the_date_comes_first_in_the_asker_s_zone() -> None:
    out = dated("3 AI news today", ZONE)
    assert out.startswith(f"[Today is {datetime.now(ZONE):%A %d %B %Y}")
    assert "Asia/Ho_Chi_Minh" in out
    assert out.endswith("3 AI news today")


class TestStaleYear:
    def test_a_recent_search_for_last_year_is_flagged(self) -> None:
        assert "2025" in (stale_year("AI news April 1 2025", "day", 2026) or "")

    def test_this_year_is_fine(self) -> None:
        assert stale_year("AI news October 2026", "day", 2026) is None

    def test_an_old_year_without_a_recent_filter_is_a_real_question(self) -> None:
        assert stale_year("AI news 2024", None, 2026) is None
        assert stale_year("AI news 2024", "year", 2026) is None
