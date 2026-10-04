"""Phase B of batch 063: does the answer cite the right passage, and decline when it should?

    uv run python -m evals.rag.answers [--limit N]

Runs the real 062 path (search, layer-two filter skipped, one Gemini call, citation
check) for every question. Each result is saved as it lands, so a run stopped by the
daily quota resumes the next day without repeating a call. Bypasses the app's quota:
this is a person spending their own calls on purpose.
"""

import argparse
import asyncio
import json
import sys
from typing import Any

from evals.rag import retrieval
from evals.rag.metrics import normalise
from mycel.agents.agent.answerer import Answerer
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps
from mycel.core.config import get_settings
from mycel.domains.ask import render
from mycel.infra.postgres.repositories.notebooks import ChunkRow
from mycel.infra.vectors import documents as vectors
from mycel.services.citations import check

STATE = retrieval.RESULTS / "answers.jsonl"


def done_ids() -> set[str]:
    if not STATE.exists():
        return set()
    return {json.loads(line)["id"] for line in STATE.read_text().splitlines() if line.strip()}


async def answer_one(
    q: dict[str, Any], lookup: dict[int, tuple[str, str]]
) -> dict[str, Any]:
    settings = get_settings()
    hits = await vectors.search(retrieval.NOTEBOOK_ID, str(q["question"]), settings.ask_top_k)
    base = {"id": q["id"], "answerable": q.get("answerable") is not False}
    if not hits or hits[0].score < settings.document_min_score:
        return {**base, "gemini": False, "answered": False, "cited": [], "grounded": False}

    labelled = {
        f"c{i}": ChunkRow(h.chunk_id, h.document_id, 0, lookup[h.chunk_id][0], "", 0,
                          lookup[h.chunk_id][1], "", None)
        for i, h in enumerate(hits, start=1)
    }
    cfg = AgentSettings.from_config(Answerer.name)
    deps = build_deps(f"eval-{q['id']}", ceiling_usd="1.00", settings=cfg)
    answer = await runner.run(Answerer.build(cfg), render(str(q["question"]), labelled), deps)
    checked = check(answer, {label: c.text for label, c in labelled.items()})

    evidence = q.get("evidence")
    hit_labels = [
        label for label, c in labelled.items()
        if evidence and c.filename == q["doc"] and normalise(str(evidence)) in normalise(c.text)
    ]
    return {
        **base,
        "gemini": True,
        "answered": answer.answered,
        "cited": checked.cited,
        "dropped": checked.dropped,
        "grounded": bool(set(checked.cited) & set(hit_labels)),
        "answer": checked.answer,
        "quotes": {c.id: c.quote for c in answer.citations},
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    correct = [r for r in answerable if r["answered"] and r["grounded"] and not r.get("dropped")]
    declined = [r for r in unanswerable if not r["answered"]]
    return {
        "answered_so_far": len(rows),
        "citation_correctness": round(len(correct) / len(answerable), 3) if answerable else None,
        "answerable": len(answerable),
        "correct": len(correct),
        "invented_citations": sum(len(r.get("dropped", [])) for r in rows),
        "unanswerable_declined": f"{len(declined)}/{len(unanswerable)}",
        "gemini_calls": sum(1 for r in rows if r["gemini"]),
        "wrong": [r["id"] for r in answerable if r not in correct],
    }


async def main_async(limit: int) -> int:
    questions = retrieval.load_questions()
    names = sorted({str(q["doc"]) for q in questions if q.get("answerable") is not False})
    lookup, _ = await retrieval.ingest(names)
    retrieval.RESULTS.mkdir(exist_ok=True)
    seen = done_ids()
    todo = [q for q in questions if q["id"] not in seen][:limit]
    try:
        for q in todo:
            try:
                row = await answer_one(q, lookup)
            except Exception as exc:
                print(f"stopped at {q['id']}: {exc}"[:300])
                break
            with STATE.open("a") as out:
                out.write(json.dumps(row) + "\n")
            print(f"  {row['id']}: answered={row['answered']} cited={row['cited']} "
                  f"grounded={row['grounded']}")
    finally:
        await retrieval.cleanup(len(names))

    rows = [json.loads(line) for line in STATE.read_text().splitlines() if line.strip()]
    print(json.dumps(summarise(rows), indent=2))
    return 0 if len(rows) == len(questions) else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    return asyncio.run(main_async(parser.parse_args().limit))


if __name__ == "__main__":
    sys.exit(main())
