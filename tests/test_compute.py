"""The arithmetic the model is not allowed to do in its head.

These are the numbers that end up in a report, so the edge cases matter more than the
happy path: a wrong number reads exactly like a right one.
"""

import math

import pytest

from mycel.agents.tools import compute


class TestPercentage:
    def test_basic(self) -> None:
        assert compute.percentage(25, 200) == 12.5

    def test_zero_whole_raises(self) -> None:
        with pytest.raises(ValueError, match="raw part"):
            compute.percentage(5, 0)


class TestPercentChange:
    def test_increase(self) -> None:
        assert compute.percent_change(100, 130) == pytest.approx(30.0)

    def test_decrease(self) -> None:
        assert compute.percent_change(100, 70) == pytest.approx(-30.0)

    def test_from_negative_uses_magnitude(self) -> None:
        """-100 -> -50 is an improvement of 50%, not -50%."""
        assert compute.percent_change(-100, -50) == pytest.approx(50.0)

    def test_zero_previous_raises(self) -> None:
        """The classic divide-by-zero a model would paper over with "infinite growth"."""
        with pytest.raises(ValueError, match="absolute change"):
            compute.percent_change(0, 50)


class TestAbsoluteChange:
    def test_is_the_fallback_when_percent_is_undefined(self) -> None:
        assert compute.absolute_change(0, 50) == 50.0


class TestCagr:
    def test_doubling_over_one_period(self) -> None:
        assert compute.cagr(100, 200, 1) == pytest.approx(100.0)

    def test_compounds(self) -> None:
        assert compute.cagr(100, 121, 2) == pytest.approx(10.0)

    @pytest.mark.parametrize(
        ("begin", "end", "periods"),
        [(0, 100, 2), (-100, 100, 2), (100, -50, 2), (100, 200, 0), (100, 200, -1)],
    )
    def test_undefined_cases_raise(self, begin: float, end: float, periods: float) -> None:
        """A sign change has no real growth rate; a model would invent one."""
        with pytest.raises(ValueError):
            compute.cagr(begin, end, periods)


class TestShareOfTotal:
    def test_shares_sum_to_100(self) -> None:
        shares = compute.share_of_total({"a": 1, "b": 3})
        assert shares == {"a": pytest.approx(25.0), "b": pytest.approx(75.0)}
        assert sum(shares.values()) == pytest.approx(100.0)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            compute.share_of_total({})

    def test_zero_total_raises(self) -> None:
        with pytest.raises(ValueError, match="raw values"):
            compute.share_of_total({"a": 5, "b": -5})


class TestSummaryStats:
    def test_describes_a_series(self) -> None:
        s = compute.summary_stats([2, 4, 4, 4, 5, 5, 7, 9])
        assert s.n == 8
        assert s.total == 40.0
        assert s.mean == pytest.approx(5.0)
        assert s.median == pytest.approx(4.5)
        assert s.stdev == pytest.approx(2.13809, rel=1e-4)
        assert (s.minimum, s.maximum) == (2.0, 9.0)

    def test_single_value_has_no_stdev(self) -> None:
        """Null, not 0.0 — "not enough data" must not read as "no variance"."""
        assert compute.summary_stats([42]).stdev is None

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            compute.summary_stats([])


def test_error_messages_tell_the_model_what_to_do_instead() -> None:
    """These strings become ModelRetry prompts, so they must be instructions."""
    for call in (
        lambda: compute.percent_change(0, 5),
        lambda: compute.percentage(1, 0),
        lambda: compute.share_of_total({}),
    ):
        with pytest.raises(ValueError) as exc:
            call()
        assert "instead" in str(exc.value) or "at least" in str(exc.value)


def test_results_are_finite() -> None:
    """No NaN or inf may reach a report."""
    assert math.isfinite(compute.percent_change(1e-9, 1e9))
    assert math.isfinite(compute.cagr(1, 1e6, 10))
