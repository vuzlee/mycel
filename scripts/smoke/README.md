# Smoke scripts

Hand-run, against real providers. Each one drives a single piece end to end and prints what
came back, which is the question CI cannot answer: a mocked model says the wiring holds, not
that the answer is worth reading.

Gitignored (`scripts/smoke/`) and never imported by the app. They spend real quota — the
Gemini free tier is 20 requests a day — so run one, read it, stop.

```bash
uv run python scripts/smoke/try_researcher.py "what to search for"
```
