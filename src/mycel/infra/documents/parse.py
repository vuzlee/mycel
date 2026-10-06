"""File to `DoclingDocument`. OCR off, pictures skipped, table structure on.

docling is imported inside the function: only the ingest worker installs it.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from mycel.core.config import get_settings


class ParseError(ValueError):
    """The file cannot become a document. `reason` is stored on the row."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@lru_cache(maxsize=1)
def _converter() -> Any:
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        generate_picture_images=False,
        accelerator_options=AcceleratorOptions(
            num_threads=get_settings().ingest_threads, device="cpu"
        ),
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.MD],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
    )


def parse(path: Path) -> Any:
    """The parsed document. Raises `ParseError` for files that cannot be used."""
    max_pages = get_settings().document_max_pages
    try:
        result = _converter().convert(path, max_num_pages=max_pages, raises_on_error=True)
    except Exception as exc:
        if "page" in str(exc).lower() and "max" in str(exc).lower():
            raise ParseError("too_many_pages") from exc
        raise ParseError("unreadable") from exc
    doc = result.document
    if not doc.export_to_text().strip():
        raise ParseError("no_text")
    return doc
