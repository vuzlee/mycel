# Smoke scripts

Hand-run, against real providers. Each one drives a single piece end to end and prints what
came back, which is the question CI cannot answer: a mocked model says the wiring holds, not
that the answer is worth reading.

Gitignored (`scripts/smoke/`) and never imported by the app. They spend real quota — the
Gemini free tier is 20 requests a day — so run one, read it, stop.

```bash
uv run python scripts/smoke/try_researcher.py "what to search for"
```

## Who the run belongs to

Since batch 055 a run reads only the projects its principal was granted, and deps built
without one are granted nothing. `try_analyst.py` and `try_orchestrator.py` reach team data,
so they read `SMOKE_USER`:

```bash
SMOKE_USER=you@example.com uv run python scripts/smoke/try_analyst.py
```

Unset, they still run and gold comes back empty — the wiring is what is being tested.
`try_researcher.py` and `try_mcp.py` never touch gold and take nothing.
