"""Phase A of batch 063: does search find the right passage at all?

    uv run python scripts/tools/fetch_rag_corpus.py
    uv run python -m evals.rag.retrieval [--keep]

Ingests the corpus through the same parse / chunk / embed code as the worker into one
eval owner id, asks every question for its top 20, and reports Recall@5/10/20, MRR,
latency and a suggested no-answer threshold. No Gemini call is made.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evals.rag.metrics import Ranked, first_hit, mrr, recall_at, threshold
from mycel.infra.documents.chunk import passages
from mycel.infra.documents.parse import parse
from mycel.infra.vectors import documents as vectors

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
CORPUS_DIR = ROOT / ".cache" / "rag-corpus"
RESULTS = HERE / "results"
TOP_K = 20

#: An owner id far above any real user, so the eval never touches real rows.
EVAL_OWNER_ID = 900_000
FIRST_DOCUMENT_ID = 900_000


def load_questions() -> list[dict[str, object]]:
    questions: list[dict[str, object]] = yaml.safe_load((HERE / "questions.yaml").read_text())
    return questions


def check_evidence(questions: list[dict[str, object]], texts: dict[str, str]) -> list[str]:
    """Every label must occur in its parsed document, or the measure is measuring a typo."""
    from evals.rag.metrics import normalise

    missing = []
    for q in questions:
        if q.get("answerable") is False:
            continue
        doc, evidence = str(q["doc"]), str(q["evidence"])
        if normalise(evidence) not in normalise(texts[doc]):
            missing.append(f"{q['id']}: {evidence!r} not found in {doc}")
    return missing


async def ingest(names: list[str]) -> tuple[dict[int, tuple[str, str]], dict[str, str]]:
    """Parse, chunk and index every document. Returns chunk lookup and full texts."""
    lookup: dict[int, tuple[str, str]] = {}
    texts: dict[str, str] = {}
    next_chunk = 0
    for offset, name in enumerate(names):
        document_id = FIRST_DOCUMENT_ID + offset
        started = time.monotonic()
        doc = await asyncio.to_thread(parse, CORPUS_DIR / name)
        found = await asyncio.to_thread(passages, doc)
        texts[name] = "\n".join(p.text for p in found)
        ids = list(range(next_chunk, next_chunk + len(found)))
        next_chunk += len(found)
        for chunk_id, p in zip(ids, found, strict=True):
            lookup[chunk_id] = (name, p.text)
        await vectors.delete(document_id)
        await vectors.write(EVAL_OWNER_ID, document_id, True, ids, [p.text for p in found])
        print(f"  {name}: {len(found)} passages in {time.monotonic() - started:.0f}s")
    return lookup, texts


async def ask(
    questions: list[dict[str, object]], lookup: dict[int, tuple[str, str]]
) -> tuple[list[Ranked], list[float]]:
    results, latencies = [], []
    for q in questions:
        started = time.monotonic()
        hits = await vectors.search(EVAL_OWNER_ID, str(q["question"]), TOP_K)
        latencies.append(time.monotonic() - started)
        answerable = q.get("answerable") is not False
        results.append(Ranked(
            question_id=str(q["id"]),
            evidence=str(q["evidence"]) if answerable else None,
            doc=str(q["doc"]) if answerable else None,
            passages=[lookup[h.chunk_id] for h in hits],
            scores=[h.score for h in hits],
        ))
    return results, latencies


async def cleanup(count: int) -> None:
    for offset in range(count):
        await vectors.delete(FIRST_DOCUMENT_ID + offset)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


def report(results: list[Ranked], latencies: list[float]) -> dict[str, object]:
    cut, kept, blocked = threshold(results)
    answerable = [r for r in results if r.evidence is not None]
    return {
        "questions": len(results),
        "answerable": len(answerable),
        "recall@5": round(recall_at(results, 5), 3),
        "recall@10": round(recall_at(results, 10), 3),
        "recall@20": round(recall_at(results, 20), 3),
        "mrr": round(mrr(results), 3),
        "latency_p50_ms": round(percentile(latencies, 0.5) * 1000),
        "latency_p95_ms": round(percentile(latencies, 0.95) * 1000),
        "threshold": round(cut, 4),
        "threshold_keeps": f"{kept}/{len(answerable)}",
        "threshold_blocks_unanswerable": f"{blocked}/{len(results) - len(answerable)}",
        "misses": [
            {"id": r.question_id, "rank": first_hit(r), "top_score": round(r.scores[0], 4)}
            for r in answerable
            if (first_hit(r) or TOP_K + 1) > 5
        ],
        "unanswerable_top_scores": [
            round(r.scores[0], 4) for r in results if r.evidence is None and r.scores
        ],
    }


async def main_async(keep: bool) -> int:
    questions = load_questions()
    names = sorted({str(q["doc"]) for q in questions if q.get("answerable") is not False})
    absent = [n for n in names if not (CORPUS_DIR / n).exists()]
    if absent:
        sys.exit(f"missing {absent}; run: uv run python scripts/tools/fetch_rag_corpus.py")

    print("ingesting")
    lookup, texts = await ingest(names)
    try:
        missing = check_evidence(questions, texts)
        if missing:
            print("labels not found in the parsed text:")
            print("\n".join(f"  {m}" for m in missing))
            return 1
        results, latencies = await ask(questions, lookup)
    finally:
        if not keep:
            await cleanup(len(names))

    summary = report(results, latencies)
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RESULTS / f"retrieval-{stamp}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="leave the eval vectors in Qdrant")
    return asyncio.run(main_async(parser.parse_args().keep))


if __name__ == "__main__":
    sys.exit(main())
