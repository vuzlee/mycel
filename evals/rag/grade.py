"""Batch 067: does the answer say the right thing, judged against a reference answer.

    uv run python -m evals.rag.grade [--limit N] [--fresh]

`answers.py` checks that an answer cites the right passage; it cannot tell a cited answer
that misreads the passage from one that reads it right. This asks a model to compare each
saved answer with the reference in `questions.yaml`. Answers are re-asked only with
`--fresh`; otherwise the saved `answers.jsonl` is graded as it stands. Each verdict is saved
as it lands, so a stopped run resumes without repeating a call.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from evals.rag import answers, retrieval
from mycel.agents.core import runner
from mycel.agents.core.base import BaseAgent
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps

STATE = retrieval.RESULTS / "grades.jsonl"

INSTRUCTIONS = """\
You grade an answer to a question about a document against a reference answer written
from that document.

- correct: it states what the reference states. Extra true detail is fine; wording and
  order do not matter.
- partly: it gets the main point but misses or blurs part of what the reference requires,
  or hedges where the reference is definite.
- wrong: it contradicts the reference, states a different fact, or declines to answer.

Judge the content only, not the citation labels like [c2]. Give one short sentence of
reason that names what is missing or wrong.
"""


class Verdict(BaseModel):
    grade: Literal["correct", "partly", "wrong"]
    reason: str = Field(description="One sentence: what matches, or what is missing or wrong.")


class Grader(BaseAgent[Verdict]):
    """Compares one answer with one reference. Eval only; not in the app's registry."""

    name = "grader"
    instructions = INSTRUCTIONS
    output_type = Verdict


def graded_ids() -> set[str]:
    if not STATE.exists():
        return set()
    return {json.loads(line)["id"] for line in STATE.read_text().splitlines() if line.strip()}


async def grade_one(q: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    base = {"id": q["id"], "answered": bool(answer.get("answered"))}
    if q.get("answerable") is False:
        # Nothing to compare with: declining is the right answer, and code can see it.
        grade = "wrong" if answer.get("answered") else "correct"
        return {
            **base,
            "grade": grade,
            "reason": "should decline; " + ("answered" if grade == "wrong" else "declined"),
            "model": False,
        }
    if not answer.get("answered") or not answer.get("answer"):
        return {**base, "grade": "wrong", "reason": "declined to answer", "model": False}

    # The answerer's model and fallbacks: a grade is one more call on the same gateway.
    cfg = AgentSettings.from_config("answerer")
    deps = build_deps(f"grade-{q['id']}", ceiling_usd="1.00", settings=cfg)
    prompt = (
        f"Question: {q['question']}\n\nReference answer: {q['reference']}\n\n"
        f"Answer to grade:\n{answer['answer']}"
    )
    verdict = await runner.run(Grader.build(cfg), prompt, deps, cfg)
    return {**base, "grade": verdict.grade, "reason": verdict.reason, "model": True}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = Counter(r["grade"] for r in rows)
    total = len(rows)
    return {
        "graded": total,
        **{g: count[g] for g in ("correct", "partly", "wrong")},
        "correct_share": round(count["correct"] / total, 3) if total else None,
        "grader_calls": sum(1 for r in rows if r["model"]),
        "not_correct": [
            f"{r['id']} {r['grade']}: {r['reason']}" for r in rows if r["grade"] != "correct"
        ],
    }


async def main_async(limit: int, fresh: bool) -> int:
    if fresh:
        answers.STATE.unlink(missing_ok=True)
        STATE.unlink(missing_ok=True)
        if await answers.main_async(100) != 0:
            return 2

    saved = {row["id"]: row for row in map(json.loads, answers.STATE.read_text().splitlines())}
    questions = [
        q for q in retrieval.load_questions() if q.get("reference") or q.get("answerable") is False
    ]
    seen = graded_ids()
    todo = [q for q in questions if q["id"] not in seen and q["id"] in saved][:limit]
    for q in todo:
        try:
            row = await grade_one(q, saved[str(q["id"])])
        except Exception as exc:
            print(f"stopped at {q['id']}: {exc}"[:300])
            break
        with STATE.open("a") as out:
            out.write(json.dumps(row) + "\n")
        print(f"  {row['id']}: {row['grade']} — {row['reason']}")

    rows = [json.loads(line) for line in STATE.read_text().splitlines() if line.strip()]
    print(json.dumps(summarise(rows), indent=2))
    return 0 if len(rows) == len(questions) else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--fresh", action="store_true", help="re-ask every question first")
    args = parser.parse_args()
    return asyncio.run(main_async(args.limit, args.fresh))


if __name__ == "__main__":
    sys.exit(main())
