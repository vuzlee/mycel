"""Citations are checked in code: the label must be a passage sent, the quote must be in it."""

from mycel.agents.schemas import Citation, NotebookAnswer
from mycel.services.citations import check

PASSAGES = {
    "c1": "BERT masks 15% of all WordPiece tokens at random.",
    "c2": "Retrieval uses a single MIPS index using FAISS.",
}


def answer(text: str, *cites: tuple[str, str]) -> NotebookAnswer:
    return NotebookAnswer(
        answer=text,
        citations=[Citation(id=i, quote=q) for i, q in cites],
        answered=True,
    )


class TestCheck:
    def test_a_real_label_with_a_real_quote_survives(self) -> None:
        out = check(answer("It masks 15% [c1].", ("c1", "masks 15% of all")), PASSAGES)

        assert out.answer == "It masks 15% [c1]."
        assert out.cited == ["c1"]
        assert out.dropped == []

    def test_an_invented_label_is_removed(self) -> None:
        out = check(answer("Something [c9].", ("c9", "anything")), PASSAGES)

        assert out.answer == "Something."
        assert out.cited == []
        assert out.dropped == ["c9"]

    def test_an_invented_quote_is_removed(self) -> None:
        out = check(answer("It masks half [c1].", ("c1", "masks 50% of tokens")), PASSAGES)

        assert "[c1]" not in out.answer
        assert out.dropped == ["c1"]

    def test_a_marker_without_a_citation_entry_is_removed(self) -> None:
        out = check(answer("FAISS [c2] and BERT [c1].", ("c2", "using FAISS")), PASSAGES)

        assert out.answer == "FAISS [c2] and BERT."
        assert out.cited == ["c2"]

    def test_quotes_match_ignoring_case_whitespace_and_markdown(self) -> None:
        passages = {"c1": "Use **BackgroundTasks**\nfor slow   work."}
        out = check(answer("Yes [c1].", ("c1", "use backgroundtasks for slow work")), passages)

        assert out.cited == ["c1"]

    def test_labels_are_accepted_with_brackets_or_upper_case(self) -> None:
        out = check(answer("FAISS [c2].", ("[C2]", "using FAISS")), PASSAGES)

        assert out.cited == ["c2"]
