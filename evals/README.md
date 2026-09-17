# Evals

Tests catch broken code. Evals catch broken **quality** — a report with no syntax error that
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
