"""Recall@k and MRR over labelled questions. Pure functions; no model, no store."""

import re
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ranked:
    """One question's search result: the passages in rank order, and their scores."""

    question_id: str
    evidence: str | None
    doc: str | None
    passages: Sequence[tuple[str, str]]  # (document name, passage text)
    scores: Sequence[float]


def normalise(text: str) -> str:
    """Case, whitespace and soft hyphenation stop mattering."""
    text = re.sub(r"-\s*\n\s*", "", text)
    return " ".join(text.lower().split())


def first_hit(result: Ranked) -> int | None:
    """1-based rank of the first passage from the right document containing the evidence."""
    if result.evidence is None:
        return None
    needle = normalise(result.evidence)
    for rank, (doc, text) in enumerate(result.passages, start=1):
        if (result.doc is None or doc == result.doc) and needle in normalise(text):
            return rank
    return None


def recall_at(results: Sequence[Ranked], k: int) -> float:
    answerable = [r for r in results if r.evidence is not None]
    if not answerable:
        return 0.0
    hits = sum(1 for r in answerable if (rank := first_hit(r)) is not None and rank <= k)
    return hits / len(answerable)


def mrr(results: Sequence[Ranked]) -> float:
    answerable = [r for r in results if r.evidence is not None]
    if not answerable:
        return 0.0
    return sum(1 / rank for r in answerable if (rank := first_hit(r))) / len(answerable)


def threshold(results: Sequence[Ranked], keep: float = 0.95) -> tuple[float, int, int]:
    """The highest top-score cut that still lets `keep` of answerable questions through.

    Returns (threshold, answerable kept, unanswerable blocked).
    """
    answerable = sorted(r.scores[0] for r in results if r.evidence is not None and r.scores)
    if not answerable:
        return 0.0, 0, 0
    allowed_to_lose = int(len(answerable) * (1 - keep))
    cut = answerable[allowed_to_lose]
    kept = sum(1 for s in answerable if s >= cut)
    blocked = sum(1 for r in results if r.evidence is None and r.scores and r.scores[0] < cut)
    return cut, kept, blocked
