"""The Knowledge chip."""

from dataclasses import dataclass, field
from typing import Any

from mycel.core.config import get_settings
from mycel.infra.postgres.repositories.documents import ChunkRow, DocumentRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.vectors import documents as vectors

NOT_FOUND = "No relevant passages were found in your documents."
BUSY = (
    "Note: documents are being processed — the knowledge base is unavailable until they are ready."
)


@dataclass(frozen=True, slots=True)
class Retrieved:
    version: str
    query: str
    labelled: dict[str, ChunkRow] = field(default_factory=dict)
    busy: bool = False


def search_text(question: str, previous: str) -> str:
    """What gets embedded: the previous question first, so a pronoun has something to point at."""
    return f"{previous}\n{question}" if previous else question


async def retrieve(user_id: int, query: str) -> Retrieved:
    settings = get_settings()
    async with session_scope() as session:
        repo = DocumentRepository(session)
        if await repo.busy(user_id):
            return Retrieved(version="", query=query, busy=True)
        version = await repo.version(user_id)

    hits = await vectors.search(user_id, query, settings.ask_top_k)
    if not hits or hits[0].score < settings.document_min_score:
        return Retrieved(version=version, query=query)
    async with session_scope() as session:
        chunks = await DocumentRepository(session).readable_chunks(
            [h.chunk_id for h in hits], user_id
        )
    labelled = {f"c{i}": c for i, c in enumerate(chunks, start=1)}
    return Retrieved(version=version, query=query, labelled=labelled)


def render(labelled: dict[str, ChunkRow]) -> str:
    """The passages as a `<documents>` block, each with where it came from."""
    blocks = []
    for label, chunk in labelled.items():
        where = chunk.filename + (f", page {chunk.page_start}" if chunk.page_start else "")
        if chunk.section_path:
            where += f", {chunk.section_path}"
        blocks.append(f"[{label}] ({where})\n{chunk.text}")
    return "<documents>\n" + "\n\n".join(blocks) + "\n</documents>"


def source(label: str, chunk: ChunkRow) -> dict[str, Any]:
    """One cited passage, as the page opens it. The quote is the passage itself."""
    return {
        "label": label,
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "filename": chunk.filename,
        "mime": chunk.mime,
        "page": chunk.page_start,
        "page_end": chunk.page_end,
        "section": chunk.section_path,
        "quote": chunk.text,
    }


def with_sources(text: str, sources: list[dict[str, Any]]) -> str:
    """The kept answer, with its sources listed, so a reopened conversation still shows them."""
    if not sources:
        return text
    lines = [
        f"- [{s['label']}] {s['filename']}" + (f", page {s['page']}" if s.get("page") else "")
        for s in sources
    ]
    return text + "\n\n**Sources**\n\n" + "\n".join(lines)
