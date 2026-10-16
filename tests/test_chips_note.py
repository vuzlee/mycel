"""The orchestrator is told which sources are on and off, so an old turn cannot overrule them."""

from mycel.agents.core.chips import missing_sources_note
from mycel.core.chips import Chip


def test_no_chips_means_no_note() -> None:
    assert missing_sources_note(None) == ""


def test_a_source_on_now_overrules_an_earlier_off() -> None:
    note = missing_sources_note(frozenset({Chip.JIRA}))
    assert note.startswith("Switched on for this turn: your team's Jira.")
    assert "even if an earlier answer" in note
    assert "Switched off for this turn: your mail, your calendar, the web." in note


def test_nothing_on_names_only_what_is_off() -> None:
    note = missing_sources_note(frozenset())
    assert "Switched on" not in note
    assert note.startswith("Switched off for this turn:")


def test_everything_on_has_no_off_part() -> None:
    note = missing_sources_note(frozenset({Chip.JIRA, Chip.MAIL, Chip.CALENDAR, Chip.WEB}))
    assert "Switched off" not in note
