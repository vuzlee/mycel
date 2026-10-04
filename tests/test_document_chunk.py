"""Tables: kept whole when they fit, split by rows with the header on every piece."""

from mycel.infra.documents.chunk import split_rows, table_passages


def words(text: str) -> int:
    return len(text.split())


HEADER = "| Model | RAM | Speed |\n|---|---|---|"
ROWS = [f"| m{i} | {i}GB | fast |" for i in range(40)]
TABLE = "\n".join([HEADER, *ROWS])


class TestSplitRows:
    def test_every_piece_starts_with_heading_and_header(self) -> None:
        pieces = split_rows(TABLE, "Embedding models", limit=60, count=words)

        assert len(pieces) > 1
        for piece in pieces:
            lines = piece.splitlines()
            assert lines[0] == "Embedding models"
            assert lines[2:4] == HEADER.splitlines()

    def test_no_row_is_lost_or_repeated(self) -> None:
        pieces = split_rows(TABLE, "", limit=60, count=words)

        body = [line for p in pieces for line in p.splitlines()[2:]]  # no head: header only
        assert body == ROWS

    def test_no_piece_is_over_the_limit_unless_one_row_is(self) -> None:
        pieces = split_rows(TABLE, "h", limit=60, count=words)

        assert all(words(p) <= 60 for p in pieces)

    def test_a_row_larger_than_the_limit_still_gets_its_own_piece(self) -> None:
        pieces = split_rows(f"{HEADER}\n| {'x ' * 100}|", "", limit=10, count=words)

        assert len(pieces) == 1


class TestTablePassages:
    def test_a_table_that_fits_stays_one_passage(self) -> None:
        out = table_passages(TABLE, "Models", "Table 1: sizes", 3, 10_000, 60, words)

        assert len(out) == 1
        assert out[0].text.startswith("Models\nTable 1: sizes")
        assert (out[0].page_start, out[0].section_path) == (3, "Models")

    def test_a_long_table_is_split_and_keeps_its_page(self) -> None:
        out = table_passages(TABLE, "Models", "", 7, 100, 60, words)

        assert len(out) > 1
        assert {p.page_start for p in out} == {7}
