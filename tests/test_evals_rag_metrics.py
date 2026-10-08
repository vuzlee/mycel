"""Recall@k, MRR and the threshold rule, on hand-built rankings."""

from evals.rag.metrics import Ranked, first_hit, mrr, normalize, recall_at, threshold


def ranked(qid: str, evidence: str | None, docs: list[str], scores: list[float]) -> Ranked:
    passages = [("a.pdf", text) for text in docs]
    return Ranked(qid, evidence, "a.pdf" if evidence else None, passages, scores)


class TestNormalize:
    def test_case_and_whitespace(self) -> None:
        assert normalize("Masked   Language\nModel") == "masked language model"

    def test_a_hyphen_across_a_line_break_is_joined(self) -> None:
        assert normalize("pre-\ntraining") == "pretraining"


class TestFirstHit:
    def test_rank_of_the_first_matching_passage(self) -> None:
        r = ranked("q", "needle", ["hay", "the needle here", "needle again"], [0.9, 0.8, 0.7])
        assert first_hit(r) == 2

    def test_the_right_text_in_the_wrong_document_is_a_miss(self) -> None:
        r = Ranked("q", "needle", "b.pdf", [("a.pdf", "needle")], [0.9])
        assert first_hit(r) is None


class TestRecall:
    def test_recall_counts_only_answerable_questions(self) -> None:
        results = [
            ranked("q1", "x", ["x"], [0.9]),
            ranked("q2", "y", ["a", "b", "y"], [0.9, 0.8, 0.7]),
            ranked("u1", None, ["z"], [0.5]),
        ]
        assert recall_at(results, 1) == 0.5
        assert recall_at(results, 3) == 1.0

    def test_mrr(self) -> None:
        results = [ranked("q1", "x", ["x"], [0.9]), ranked("q2", "y", ["a", "y"], [0.9, 0.8])]
        assert mrr(results) == (1 + 0.5) / 2


class TestThreshold:
    def test_keeps_answerable_and_reports_what_it_blocks(self) -> None:
        results = [ranked(f"q{i}", "x", ["x"], [0.80 + i / 100]) for i in range(20)]
        results += [ranked("u1", None, ["z"], [0.70]), ranked("u2", None, ["z"], [0.95])]

        cut, kept, blocked = threshold(results, keep=0.95)

        assert cut == 0.81
        assert kept == 19
        assert blocked == 1
