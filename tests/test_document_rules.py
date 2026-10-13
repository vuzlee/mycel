"""Rules that need no database: file type by content, queue routing by kind."""

import pytest

from mycel.queue import topology
from mycel.queue.job import Job, JobKind
from mycel.queue.producer import queue_for
from mycel.services.documents import DOCX, MARKDOWN, PDF, DocumentError, UnsupportedType, sniff
from mycel.services.enqueue import delete_job, ingest_job


class TestSniff:
    def test_a_pdf_is_a_pdf(self) -> None:
        assert sniff("a.pdf", b"%PDF-1.7\n...") == PDF

    def test_an_executable_named_pdf_is_refused(self) -> None:
        with pytest.raises(DocumentError) as caught:
            sniff("a.pdf", b"\x7fELF\x02\x01\x01" + b"\x00" * 64)
        assert isinstance(caught.value, UnsupportedType)

    def test_markdown_is_text_with_a_markdown_name(self) -> None:
        assert sniff("notes.md", b"# Title\n\nbody") == MARKDOWN

    def test_text_with_another_name_is_refused(self) -> None:
        with pytest.raises(DocumentError):
            sniff("notes.txt", b"# Title")

    def test_a_docx_is_recognized(self) -> None:
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", "<w:document/>")
        assert sniff("a.docx", buffer.getvalue()) == DOCX


class TestRouting:
    def test_ingest_and_delete_go_to_the_ingest_queue(self) -> None:
        assert queue_for(ingest_job(1)) == topology.INGEST_QUEUE
        assert queue_for(delete_job(1)) == topology.INGEST_QUEUE

    def test_chat_stays_on_jobs(self) -> None:
        assert queue_for(Job(kind=JobKind.CHAT, payload={})) == topology.QUEUE

    def test_each_queue_retries_into_its_own_family(self) -> None:
        assert topology.retry_queue_for(topology.INGEST_QUEUE) == "ingest.retry.5s"
        assert topology.dead_queue_for(topology.INGEST_QUEUE) == topology.INGEST_DEAD_QUEUE
        assert topology.retry_queue_for(topology.QUEUE) == "jobs.retry.5s"


class TestTheStatusEachRefusalGets:
    """The service names the refusal; only the api knows it as a number."""

    def test_every_refusal_keeps_its_status(self) -> None:
        from mycel.api.app import DOCUMENT_STATUS
        from mycel.services import documents as d

        assert DOCUMENT_STATUS == {
            d.DocumentNotFound: 404,
            d.UnsupportedType: 415,
            d.TooLarge: 413,
            d.Unusable: 422,
            d.Conflict: 409,
            d.Busy: 429,
        }

    def test_every_refusal_has_a_status(self) -> None:
        from mycel.api.app import DOCUMENT_STATUS
        from mycel.services import documents as d

        kinds = {
            c for c in vars(d).values() if isinstance(c, type) and issubclass(c, d.DocumentError)
        }
        assert kinds - {d.DocumentError} == set(DOCUMENT_STATUS)


def test_no_http_number_lives_in_services() -> None:
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "mycel"
    for path in [*(src / "services").rglob("*.py"), *(src / "domains").rglob("*.py")]:
        text = path.read_text()
        assert not re.search(r"Error\((4|5)\d\d\b", text), path
        assert "fastapi" not in text, path
