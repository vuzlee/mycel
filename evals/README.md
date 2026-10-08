# Evals

Tests catch broken code. Evals catch broken **quality**: an answer with no error that is
simply worse than the last one.

Two suites:

- **Summariser golden set** in `summariser/`: prompt → what a good summary must contain.
- **RAG benchmark** in `rag/`: does Knowledge document search find, cite and state the right passage.

## Summariser golden set

```
summariser/
  case.py      # one case and its checks
  run.py       # runs every case, scores it, saves or compares a baseline
  golden/
    empty-window-invents-nothing.yaml
    on-track-quiet-week.yaml
    over-estimate-is-not-overdue.yaml
    overdue-is-at-risk.yaml
    truncated-window-admits-it.yaml
    unassigned-work-has-no-owner.yaml
```

Checks are structural: health verdict, at-risk and shipped keys, no invented keys,
load rows per person, notes for a truncated window.
`--save-baseline` writes `summariser/baseline.json`; `--compare-baseline` exits 1 if the score drops.

## RAG benchmark

- `corpus.yaml`: public documents with pinned sha256.
- `questions.yaml`: questions with evidence and reference answers, plus unanswerable ones.
- `followups.yaml`: two-turn cases for the follow-up rewrite (batch 074).
- `results/`: retrieval reports, `answers.jsonl`, `grades.jsonl`. Runs resume from these files.

The grader uses the same model as the answerer: the orchestrator's model and fallbacks.

## Running them

Evals are **not in CI**. Every model call goes through the LiteLLM gateway, which CI cannot reach.
Run them by hand, and say how many calls before you do.

| Command | Model calls | Measures |
|---|---|---|
| `uv run python -m evals.rag.fetch_corpus` | 0 | downloads the corpus to `.cache/rag-corpus/`, checks hashes |
| `uv run python -m evals.rag.retrieval` | 0 | Recall@5/10/20, MRR, latency |
| `uv run python -m evals.rag.answers` | ~31 | citation correctness, declining unanswerable |
| `uv run python -m evals.rag.grade` | ~26 | answer content against the reference |
| `uv run python -m evals.rag.followups` | 5 | follow-up search: stitched vs rewritten, top-5 hits |
| `uv run python -m evals.summariser.run --save-baseline` | 6 | summariser golden set, records the score |
| `uv run python -m evals.summariser.run --compare-baseline` | 6 | same, fails if the score dropped |

## Committed baseline

| Field | Value |
|---|---|
| Date | 2026-10-08 |
| Commit | after `2662251`: a refusal cites nothing, and a few late items is `at_risk` |
| Models | `claude-sonnet-5` for answers, grades and the summariser (the grader is the answerer's own model) |
| Corpus size | 8 documents, 31 questions (26 answerable, 5 not) |
| Recall@5 / @10 / @20 | 0.962 / 0.962 / 1.0 |
| MRR | 0.793 |
| Grounded | 25/26 (`a01` misses: Adam's defaults rank 11th) |
| Declined | 5/5 |
| Grades (correct / partly / wrong) | 29 / 1 / 1 (`a01`) |
| Follow-ups @5 (stitched / rewritten) | 3/5 / 5/5, `gemini-3.5-flash-lite` rewrites (after `b515fec`) |
| Summariser | 0.976 over 6 cases (one miss: `MYC-62`, far over estimate, left out of `at_risk`), saved to `evals/summariser/baseline.json` |
