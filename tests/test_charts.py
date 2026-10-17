"""Charts in an answer: kept only when every value came back from a tool."""

import json

from mycel.agents.core import charts

SEEN = charts.numbers("author_name | total_hours\nann | 85.50\nbob | 42.00\ncy | 12.25")


def _answer(values: list[float]) -> str:
    block = {
        "type": "bar",
        "title": "Hours",
        "unit": "h",
        "labels": ["ann", "bob", "cy"],
        "values": values,
    }
    return f"Ann logged the most.\n\n```chart\n{json.dumps(block)}\n```\n"


def test_a_chart_of_numbers_a_tool_returned_is_kept() -> None:
    assert "```chart" in charts.settle(_answer([85.5, 42, 12.25]), SEEN, drawn=False)


def test_a_chart_with_a_number_no_tool_returned_is_dropped() -> None:
    out = charts.settle(_answer([85.5, 42, 99]), SEEN, drawn=False)
    assert "```chart" not in out and out == "Ann logged the most."


def test_rounding_the_model_did_is_not_invention() -> None:
    assert "```chart" in charts.settle(_answer([85.5, 42, 12.3]), SEEN, drawn=False)


def test_a_chart_that_is_not_valid_json_is_dropped() -> None:
    out = charts.settle("Text.\n```chart\n{not json\n```", SEEN, drawn=False)
    assert "```chart" not in out


def test_a_tool_chart_wins_over_a_written_one() -> None:
    assert "```chart" not in charts.settle(_answer([85.5, 42, 12.25]), SEEN, drawn=True)


def test_one_point_is_not_a_chart() -> None:
    assert charts.build("bar", "Hours", "h", [("ann", 1.0)]) is None


def test_a_built_chart_caps_its_points() -> None:
    chart = charts.build("bar", "Hours", "h", [(str(i), float(i)) for i in range(40)])
    assert chart is not None and len(chart["values"]) == charts.MAX_POINTS
