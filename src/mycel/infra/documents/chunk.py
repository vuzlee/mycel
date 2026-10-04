"""DoclingDocument to passages of ~N tokens, cut along the document's structure.

Prose goes through docling's `HybridChunker`. Tables do not: it flattens them into
"key = value" sentences and never repeats the header. A table is rendered as Markdown;
one that fits stays whole, a longer one is split by rows with the header on every piece.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from mycel.core.config import get_settings
from mycel.infra.documents import tokens


@dataclass(frozen=True, slots=True)
class Passage:
    text: str
    section_path: str
    page_start: int | None
    page_end: int | None
    tokens: int


def passages(doc: Any, count: Callable[[str], int] = tokens.count) -> list[Passage]:
    settings = get_settings()
    out = list(_prose(doc, settings.document_chunk_tokens, count))
    for table, heading in _tables(doc):
        out.extend(
            table_passages(
                table.export_to_markdown(doc),
                heading,
                table.caption_text(doc),
                _page(table),
                settings.document_table_max_tokens,
                settings.document_chunk_tokens,
                count,
            )
        )
    out.sort(key=lambda p: p.page_start or 0)
    return out


def table_passages(
    markdown: str,
    heading: str,
    caption: str,
    page: int | None,
    whole_max: int,
    piece_max: int,
    count: Callable[[str], int],
) -> list[Passage]:
    """One passage if the table fits in `whole_max`, else row groups of `piece_max`."""
    head = "\n".join(x for x in (heading, caption) if x)
    whole = f"{head}\n\n{markdown}".strip()
    if count(whole) <= whole_max:
        return [Passage(whole, heading, page, page, count(whole))]
    return [
        Passage(t, heading, page, page, count(t))
        for t in split_rows(markdown, head, piece_max, count)
    ]


def split_rows(markdown: str, head: str, limit: int, count: Callable[[str], int]) -> list[str]:
    """Markdown table rows into pieces of at most `limit` tokens, header on every piece."""
    lines = [line for line in markdown.splitlines() if line.strip()]
    header, body = lines[:2], lines[2:]
    prefix = "\n".join([head, "", *header]) if head else "\n".join(header)
    pieces: list[str] = []
    rows: list[str] = []
    for row in body:
        candidate = "\n".join([prefix, *rows, row])
        if rows and count(candidate) > limit:
            pieces.append("\n".join([prefix, *rows]))
            rows = []
        rows.append(row)
    if rows:
        pieces.append("\n".join([prefix, *rows]))
    return pieces


def _prose(doc: Any, limit: int, count: Callable[[str], int]) -> Iterator[Passage]:
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from transformers import AutoTokenizer

    tokenizer = HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained(get_settings().document_embedding_model),
        max_tokens=limit,
    )
    chunker = HybridChunker(tokenizer=tokenizer, merge_peers=True)
    for chunk in chunker.chunk(doc):
        items = [i for i in chunk.meta.doc_items if i.label.value != "table"]
        if not items:
            continue
        text = chunker.contextualize(chunk)
        pages = [p.page_no for i in items for p in (i.prov or [])]
        yield Passage(
            text=text,
            section_path=" > ".join(chunk.meta.headings or []),
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            tokens=count(text),
        )


def _tables(doc: Any) -> Iterator[tuple[Any, str]]:
    """Every table, with the nearest heading above it."""
    from docling_core.types.doc import SectionHeaderItem, TableItem, TitleItem

    heading = ""
    for item, _ in doc.iterate_items():
        if isinstance(item, SectionHeaderItem | TitleItem):
            heading = item.text
        elif isinstance(item, TableItem):
            yield item, heading


def _page(item: Any) -> int | None:
    prov = getattr(item, "prov", None) or []
    return prov[0].page_no if prov else None
