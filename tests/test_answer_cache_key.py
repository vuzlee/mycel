"""A cached Knowledge answer is keyed by what wrote it, not only by the documents."""

from mycel.infra.redis.answers import _key, writer


class TestWriter:
    def test_a_prompt_edit_changes_the_key(self) -> None:
        assert writer("prompt a", ("m",)) != writer("prompt b", ("m",))

    def test_a_model_swap_changes_the_key(self) -> None:
        assert writer("p", ("cloud:a",)) != writer("p", ("cloud:b",))

    def test_a_fallback_change_changes_the_key(self) -> None:
        assert writer("p", ("m",)) != writer("p", ("m", "fallback"))

    def test_the_same_writer_is_stable(self) -> None:
        assert writer("p", ("m",)) == writer("p", ("m",))


class TestKey:
    def test_the_writer_is_part_of_the_key(self) -> None:
        assert _key(1, "v", "w1", "q?") != _key(1, "v", "w2", "q?")

    def test_the_question_is_normalized(self) -> None:
        assert _key(1, "v", "w", "What is BERT?") == _key(1, "v", "w", "what is bert")
