"""Knowledge turns: the search query, the answers documents settle alone, and citations."""

from dataclasses import replace
from typing import Any

from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.specialists.orchestrator import Orchestrator
from mycel.agents.specialists.rewriter import Rewriter
from mycel.core.chips import Chip
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.events.channel import NullChannel
from mycel.infra.redis import answers
from mycel.queue.job import Job
from mycel.services import knowledge
from mycel.services.citations import check

log = get_logger(__name__)


async def search_query(job: Job, question: str, deps: MycelDeps) -> str:
    """The follow-up rewritten to stand alone; the stitched text if the rewrite fails."""
    previous = str(job.payload.get("previous", "")).strip()
    context = str(job.payload.get("context", "")).strip()
    stitched = knowledge.search_text(question, previous[: get_settings().ask_max_chars])
    if not context:
        return stitched
    settings = AgentSettings.from_config(Rewriter.name)
    rewrite_deps = replace(deps, settings=settings, events=NullChannel())
    prompt = f"{context}\n\nThe question now:\n{question}"
    try:
        rewritten = await runner.run(Rewriter.build(settings), prompt, rewrite_deps)
    except Exception as exc:
        log.warning("rewrite failed", extra={"job_id": job.job_id, "error": str(exc)})
        return stitched
    rewritten = rewritten.strip()[: get_settings().ask_max_chars]
    return rewritten or stitched


async def answer_without_model(
    user_id: int, chips: frozenset[Chip], found: knowledge.Retrieved, model_ref: str
) -> tuple[str, list[dict[str, Any]]] | None:
    """A Knowledge-only turn the documents settle alone: busy, nothing found, or cached."""
    if chips != frozenset({Chip.KNOWLEDGE}):
        return None
    if found.busy:
        return knowledge.BUSY, []
    if not found.labelled:
        return knowledge.NOT_FOUND, []
    cached = await answers.get(user_id, found.version, cache_writer(model_ref), found.query)
    if cached is None:
        return None
    return cached["answer"], cached["sources"]


def cache_writer(model_ref: str) -> str:
    """What a cached Knowledge answer depends on besides the documents: prompt and model."""
    return answers.writer(Orchestrator.instructions, (model_ref,))


def cite(job: Job, answer: str, found: knowledge.Retrieved) -> tuple[str, list[dict[str, Any]]]:
    """Strip markers for passages not sent; the rest become the turn's sources."""
    checked = check(answer, list(found.labelled))
    if checked.dropped:
        log.warning("citations dropped", extra={"job_id": job.job_id, "dropped": checked.dropped})
    sources = [knowledge.source(label, found.labelled[label]) for label in checked.cited]
    return checked.answer, sources
