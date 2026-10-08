"""Does the 074 rewrite find a follow-up's passage better than stitching?"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evals.common import CEILING_USD
from evals.rag.metrics import Ranked, first_hit
from evals.rag.retrieval import CORPUS_DIR, EVAL_OWNER_ID, RESULTS, TOP_K, cleanup, ingest
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps
from mycel.agents.specialists.rewriter import Rewriter
from mycel.infra.vectors import documents as vectors
from mycel.services.knowledge import search_text

HERE = Path(__file__).parent


async def rank(query: str, case: dict[str, str], lookup: dict[int, tuple[str, str]]) -> int | None:
    hits = await vectors.search(EVAL_OWNER_ID, query, TOP_K)
    return first_hit(
        Ranked(
            question_id=case["id"],
            evidence=case["evidence"],
            doc=case["doc"],
            passages=[lookup[h.chunk_id] for h in hits],
            scores=[h.score for h in hits],
        )
    )


async def rewrite(case: dict[str, str]) -> str:
    settings = AgentSettings.from_config(Rewriter.name)
    deps = build_deps(f"eval-{case['id']}", CEILING_USD, settings=settings)
    prompt = f"Earlier questions:\n- {case['previous']}\n\nThe question now:\n{case['question']}"
    answer: str = await runner.run(Rewriter.build(settings), prompt, deps)
    return answer.strip()


async def main_async() -> int:
    cases: list[dict[str, str]] = yaml.safe_load((HERE / "followups.yaml").read_text())
    names = sorted({c["doc"] for c in cases})
    absent = [n for n in names if not (CORPUS_DIR / n).exists()]
    if absent:
        sys.exit(f"missing {absent}; run: uv run python -m evals.rag.fetch_corpus")

    print("ingesting")
    lookup, _ = await ingest(names)
    rows: list[dict[str, str | int | None]] = []
    try:
        for case in cases:
            rewritten = await rewrite(case)
            stitched = search_text(case["question"], case["previous"])
            rows.append(
                {
                    "id": case["id"],
                    "rewritten": rewritten,
                    "stitched_rank": await rank(stitched, case, lookup),
                    "rewritten_rank": await rank(rewritten, case, lookup),
                }
            )
    finally:
        await cleanup(len(names))

    def top5(key: str) -> str:
        return f"{sum(1 for r in rows if (n := r[key]) is not None and int(n) <= 5)}/{len(rows)}"

    summary = {
        "stitched@5": top5("stitched_rank"),
        "rewritten@5": top5("rewritten_rank"),
        "cases": rows,
    }
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RESULTS / f"followups-{stamp}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
