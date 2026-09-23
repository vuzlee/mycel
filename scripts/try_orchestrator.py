"""Run the orchestrator against real models, calling real specialists. End to end.

    uv run python scripts/try_orchestrator.py
    uv run python scripts/try_orchestrator.py "a question"

`tests/test_orchestrator.py` fakes `runner.delegate`, so it proves the plumbing: a failure
is reported rather than raised, a delegated run is billed once. It cannot prove that a
model handed two specialists actually splits a request between them, or that the sources
survive the trip back. That is what this script is for.

The prompt below needs both specialists on purpose — figures to compute and a fact to look
up — because an orchestrator that only ever calls one of them is not orchestrating.

Reads `GEMINI_API_KEY` and `TAVILY_API_KEY` from `.env`. Not a test: it costs money and
needs the network, so it stays out of `tests/` where `ALLOW_MODEL_REQUESTS` is off.
"""

import sys

from mycel.agents.agent.orchestrator import Orchestrator
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps
from mycel.observability.tracing import setup_tracing

PROMPT = """\
Our support tickets went from 840 in Q1 to 902 in Q2. Report the growth, and find out what
the current stable release of Python is and when it was published.
"""


def main() -> int:
    # Spans are batched, so the provider is flushed before the process exits — otherwise
    # a script that finishes in two seconds exports nothing.
    provider = setup_tracing()

    cfg = AgentSettings.from_config("orchestrator")
    prompt = sys.argv[1] if len(sys.argv) > 1 else PROMPT
    print(f"model: {cfg.model_spec}\n")

    # A whole-job ceiling, not a per-run one: every specialist spends from this same pot.
    deps = build_deps("try-orchestrator", ceiling_usd="1.00", settings=cfg)
    answer = runner.run_sync(Orchestrator.build(cfg), prompt, deps)

    print(answer)
    print(f"\nspent: ${deps.budget.spent_usd}")

    if provider is not None:
        provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
