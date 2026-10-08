"""Does a Knowledge answer cite the right passage, and decline when it should?"""

import argparse
import asyncio
import json
import sys
from typing import Any

from evals.common import CEILING_USD, ids, read_jsonl
from evals.rag import retrieval
from evals.rag.metrics import normalize
from mycel.agents.core import runner
from mycel.agents.core.chips import Chip
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps
from mycel.agents.specialists.orchestrator import Orchestrator
from mycel.core.config import get_settings
from mycel.infra.postgres.repositories.documents import ChunkRow
from mycel.infra.vectors import documents as vectors
from mycel.services.citations import check
from mycel.services.knowledge import render

STATE = retrieval.RESULTS / "answers.jsonl"


async def answer_one(q: dict[str, Any], lookup: dict[int, tuple[str, str]]) -> dict[str, Any]:
    settings = get_settings()
    hits = await vectors.search(retrieval.EVAL_OWNER_ID, str(q["question"]), settings.ask_top_k)
    base = {"id": q["id"], "answerable": q.get("answerable") is not False}
    if not hits or hits[0].score < settings.document_min_score:
        return {
            **base,
            "model": False,
            "answered": False,
            "cited": [],
            "dropped": [],
            "grounded": False,
            "answer": "",
        }

    labelled = {
        f"c{i}": ChunkRow(
            h.chunk_id,
            h.document_id,
            0,
            lookup[h.chunk_id][0],
            "",
            0,
            lookup[h.chunk_id][1],
            "",
            None,
        )
        for i, h in enumerate(hits, start=1)
    }
    cfg = AgentSettings.from_config(Orchestrator.name)
    deps = build_deps(
        f"eval-{q['id']}", ceiling_usd=CEILING_USD, settings=cfg, chips=frozenset({Chip.KNOWLEDGE})
    )
    prompt = f"{render(labelled)}\n\n{q['question']}"
    answer = await runner.run(Orchestrator.build(cfg), prompt, deps)
    checked = check(answer, list(labelled))

    evidence = q.get("evidence")
    hit_labels = [
        label
        for label, c in labelled.items()
        if evidence and c.filename == q["doc"] and normalize(str(evidence)) in normalize(c.text)
    ]
    return {
        **base,
        "model": True,
        "answered": bool(checked.cited),
        "cited": checked.cited,
        "dropped": checked.dropped,
        "grounded": bool(set(checked.cited) & set(hit_labels)),
        "answer": checked.answer,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
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
        "model_calls": sum(1 for r in rows if r["model"]),
        "wrong": [r["id"] for r in answerable if r not in correct],
    }


async def main_async(limit: int | None = None) -> int:
    questions = retrieval.load_questions()
    names = sorted({str(q["doc"]) for q in questions if q.get("answerable") is not False})
    lookup, _ = await retrieval.ingest(names)
    retrieval.RESULTS.mkdir(exist_ok=True)
    seen = ids(STATE)
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
            print(
                f"  {row['id']}: answered={row['answered']} cited={row['cited']} "
                f"grounded={row['grounded']}"
            )
    finally:
        await retrieval.cleanup(len(names))

    rows = read_jsonl(STATE)
    print(json.dumps(summarize(rows), indent=2))
    return 0 if len(rows) == len(questions) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="at most N questions (default all)")
    return asyncio.run(main_async(parser.parse_args(argv).limit))


if __name__ == "__main__":
    sys.exit(main())
