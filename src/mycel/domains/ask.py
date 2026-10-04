"""Ask one notebook: search, read through layer two, one Gemini call, check citations.

The request side (`request_ask`) runs every gate that costs nothing. The worker side
(`run`) is the only place a Gemini call is made, and it gives the quota back on failure.
"""

from decimal import Decimal
from typing import Any

from mycel.agents.agent.answerer import Answerer
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps
from mycel.agents.schemas import NotebookAnswer
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.events.channel import RecordingChannel
from mycel.infra.postgres.repositories.notebooks import ChunkRow, NotebookRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import answers, budgets, quota, results
from mycel.infra.redis import citations as stored_citations
from mycel.infra.redis.streams import RedisEventChannel
from mycel.infra.vectors import documents as vectors
from mycel.queue.job import Job, JobKind
from mycel.queue.producer import publish
from mycel.services.auth import Principal
from mycel.services.citations import check
from mycel.services.notebooks import NotebookError

log = get_logger(__name__)

NOT_FOUND = "No relevant passages were found in this notebook."
NOT_GROUNDED = "Could not ground an answer in the documents."
OUT_OF_QUOTA = "Daily question limit reached. Try again tomorrow."
BUSY = "Notebook is still processing documents."


async def request_ask(owner_id: int, notebook_id: int, question: str) -> dict[str, Any]:
    """Gates in order of cost. Returns a cached answer, or the queued job id."""
    settings = get_settings()
    question = question.strip()
    if not question:
        raise NotebookError(422, "Ask a question.")
    if len(question) > settings.ask_max_chars:
        raise NotebookError(422, f"Questions are limited to {settings.ask_max_chars} characters.")

    async with session_scope() as session:
        repo = NotebookRepository(session)
        if await repo.notebook(notebook_id, owner_id) is None:
            raise NotebookError(404, "Not found.")
        if await repo.busy(notebook_id):
            raise NotebookError(409, BUSY)
        version = await repo.version(notebook_id)

    cached = await answers.get(notebook_id, version, question)
    if cached is not None:
        return {"cached": True, **cached}

    left = await quota.remaining(owner_id, settings.ask_per_user_daily, settings.ask_system_daily)
    if left <= 0:
        raise NotebookError(429, OUT_OF_QUOTA)

    job = Job(
        kind=JobKind.ASK,
        payload={
            "notebook_id": notebook_id,
            "question": question,
            "user_id": owner_id,
            "version": version,
        },
    )
    await publish(job)
    return {"cached": False, "job_id": job.job_id}


async def remaining(owner_id: int) -> int:
    settings = get_settings()
    return await quota.remaining(owner_id, settings.ask_per_user_daily, settings.ask_system_daily)


async def run(job: Job) -> None:
    settings = get_settings()
    notebook_id = int(str(job.payload["notebook_id"]))
    owner_id = int(str(job.payload["user_id"]))
    question = str(job.payload["question"])
    version = str(job.payload["version"])

    hits = await vectors.search(notebook_id, question, settings.ask_top_k)
    if not hits or hits[0].score < settings.document_min_score:
        await _finish(job, notebook_id, version, question, NOT_FOUND, [], cache=True)
        return

    async with session_scope() as session:
        chunks = await NotebookRepository(session).readable_chunks(
            [h.chunk_id for h in hits], owner_id
        )
    if not chunks:
        await _finish(job, notebook_id, version, question, NOT_FOUND, [], cache=True)
        return

    labelled = {f"c{i}": c for i, c in enumerate(chunks, start=1)}
    if not await quota.reserve(owner_id, settings.ask_per_user_daily, settings.ask_system_daily):
        await _finish(job, notebook_id, version, question, OUT_OF_QUOTA, [], cache=False)
        return
    try:
        answer = await _ask_model(job, owner_id, question, labelled)
    except Exception:
        await quota.release(owner_id)
        raise

    checked = check(answer, {label: c.text for label, c in labelled.items()})
    if answer.answered and not checked.cited:
        text, sources = NOT_GROUNDED, []
    else:
        text, sources = checked.answer, [_source(label, labelled[label]) for label in checked.cited]
    if checked.dropped:
        log.warning("citations dropped", extra={"job_id": job.job_id, "dropped": checked.dropped})
    await _finish(job, notebook_id, version, question, text, sources, cache=True)


async def record_failure(job: Job, error: str) -> None:
    await stored_citations.store(job.job_id, int(str(job.payload["user_id"])), [])
    await results.store_failure(job.job_id, error)


async def read(owner_id: int, job_id: str) -> dict[str, Any]:
    """The state of an ask job, for its owner only. Running until the worker writes it."""
    meta = await stored_citations.fetch(job_id)
    if meta is not None and meta["owner_id"] != owner_id:
        raise NotebookError(404, "Not found.")
    result = await results.fetch(job_id)
    if meta is None or result is None or result.status == "running":
        return {"status": "running", "answer": None, "sources": [], "error": None}
    return {
        "status": result.status,
        "answer": result.answer,
        "sources": meta["sources"],
        "error": OUT_OF_QUOTA if result.error and "quota" in result.error.lower() else result.error,
    }


def render(question: str, labelled: dict[str, ChunkRow]) -> str:
    blocks = []
    for label, chunk in labelled.items():
        where = chunk.filename + (f", page {chunk.page_start}" if chunk.page_start else "")
        if chunk.section_path:
            where += f", {chunk.section_path}"
        blocks.append(f"[{label}] ({where})\n{chunk.text}")
    return "Passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"


async def _ask_model(
    job: Job, owner_id: int, question: str, labelled: dict[str, ChunkRow]
) -> NotebookAnswer:
    settings = AgentSettings.from_config(Answerer.name)
    ceiling = get_settings().job_ceiling_usd
    deps = build_deps(
        job.job_id,
        ceiling_usd=ceiling,
        settings=settings,
        budget=await budgets.load(job.job_id, ceiling),
        events=RecordingChannel(RedisEventChannel(job.job_id)),
        principal=Principal(id=owner_id, email=""),
    )
    try:
        result = await runner.run(Answerer.build(settings), render(question, labelled), deps)
    finally:
        await budgets.save(deps.budget)
    return result


def _source(label: str, chunk: ChunkRow) -> dict[str, Any]:
    return {
        "label": label,
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "filename": chunk.filename,
        "mime": chunk.mime,
        "page": chunk.page_start,
        "section": chunk.section_path,
    }


async def _finish(
    job: Job,
    notebook_id: int,
    version: str,
    question: str,
    text: str,
    sources: list[dict[str, Any]],
    *,
    cache: bool,
) -> None:
    await stored_citations.store(job.job_id, int(str(job.payload["user_id"])), sources)
    await results.store(job.job_id, text, str(Decimal("0")))
    if cache:
        await answers.put(notebook_id, version, question, {"answer": text, "sources": sources})
    log.info("notebook answered", extra={"job_id": job.job_id, "sources": len(sources)})
