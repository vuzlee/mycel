"""Citations are checked in code: a `[cN]` marker survives only when its passage was sent."""

from mycel.services.citations import check

LABELS = ["c1", "c2"]


class TestCheck:
    def test_a_sent_label_survives(self) -> None:
        out = check("It masks 15% [c1].", LABELS)

        assert out.answer == "It masks 15% [c1]."
        assert out.cited == ["c1"]
        assert out.dropped == []

    def test_an_invented_label_is_removed(self) -> None:
        out = check("Something [c9].", LABELS)

        assert out.answer == "Something."
        assert out.cited == []
        assert out.dropped == ["c9"]

    def test_cited_follows_passage_order(self) -> None:
        out = check("FAISS [c2] and BERT [c1].", LABELS)

        assert out.cited == ["c1", "c2"]

    def test_upper_case_markers_are_kept_lower_cased(self) -> None:
        out = check("FAISS [C2].", LABELS)

        assert out.answer == "FAISS [c2]."
        assert out.cited == ["c2"]

    def test_no_passages_strips_every_marker(self) -> None:
        out = check("A claim [c1].", [])

        assert out.answer == "A claim."
        assert out.dropped == ["c1"]
