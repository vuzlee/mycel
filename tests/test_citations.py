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


class TestARefusalCitesNothing:
    """A refusal listed under sources reads as an answer with evidence."""

    def test_markers_on_a_refusal_are_dropped(self) -> None:
        out = check(
            "The documents do not cover this — they describe BackgroundTasks [c1][c2], "
            "but say nothing about retries.",
            LABELS,
        )

        assert out.cited == []
        assert "[c1]" not in out.answer
        assert out.dropped == ["c1", "c2"]

    def test_the_usual_wordings_count_as_a_refusal(self) -> None:
        for text in (
            "The documents don't cover pricing [c1].",
            "The provided documents do not contain that [c1].",
            "The documents cover Qdrant, not Milvus, so they don't cover this [c1].",
        ):
            assert check(text, LABELS).cited == [], text

    def test_an_answer_that_mentions_a_gap_later_keeps_its_markers(self) -> None:
        out = check("BERT masks 15% of tokens [c1]. The documents don't cover ALBERT.", LABELS)

        assert out.cited == ["c1"]
