"""Rules that need no database: file type by content, queue routing by kind."""

import pytest

from mycel.domains.ingest import delete_job, ingest_job
from mycel.queue import topology
from mycel.queue.job import Job, JobKind
from mycel.queue.producer import queue_for
from mycel.services.notebooks import DOCX, MARKDOWN, PDF, NotebookError, sniff


class TestSniff:
    def test_a_pdf_is_a_pdf(self) -> None:
        assert sniff("a.pdf", b"%PDF-1.7\n...") == PDF

    def test_an_executable_named_pdf_is_refused(self) -> None:
        with pytest.raises(NotebookError) as caught:
            sniff("a.pdf", b"\x7fELF\x02\x01\x01" + b"\x00" * 64)
        assert caught.value.status == 415

    def test_markdown_is_text_with_a_markdown_name(self) -> None:
        assert sniff("notes.md", b"# Title\n\nbody") == MARKDOWN

    def test_text_with_another_name_is_refused(self) -> None:
        with pytest.raises(NotebookError):
            sniff("notes.txt", b"# Title")

    def test_a_docx_is_recognised(self) -> None:
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
        assert topology.retry_queue_for(topology.INGEST_QUEUE) == topology.INGEST_RETRY_QUEUE
        assert topology.dead_queue_for(topology.INGEST_QUEUE) == topology.INGEST_DEAD_QUEUE
        assert topology.retry_queue_for(topology.QUEUE) == topology.RETRY_QUEUE
