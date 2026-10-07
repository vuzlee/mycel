# Evals

Tests catch broken code. Evals catch broken **quality** — an answer with no syntax error that
is simply worse than the last one. Without evals, changing a prompt is guesswork.

## Golden set

`golden/` holds *input → expected output* pairs taken from real cases:

```
golden/
  weekly-summary-01.yaml    # sample gold data + a report a human found acceptable
```

Every time a prompt changes, a model changes, or an agent version is bumped: re-run the whole
golden set and compare scores against the previous run.

## Scoring

| Kind | How it is scored |
|---|---|
| Structured | Direct comparison — right figures, right dates, right names |
| Prose | An LLM scores against a rubric, with humans reviewing a random sample |

Record each run's scores to see the trend. A prompt that drops the score blocks the merge; it
is not a matter of taste.

## Running them

Evals are **not in CI**. Every case is a real model call through the LiteLLM gateway, and
the primary model sits behind a model gateway CI cannot reach. Run them by hand, and say how
many calls before you do:

| Command | Model calls | Measures |
|---|---|---|
| `uv run python -m evals.run --compare-baseline` | 6 | summariser golden set |
| `uv run python -m evals.rag.retrieval` | **0** | Recall@5/10/20 for notebook search |
| `uv run python -m evals.rag.answers` | 30 (up to ~120 with retries) | citation correctness, declining unanswerable |
