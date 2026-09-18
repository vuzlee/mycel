"""Run the researcher against a real model and the real Tavily. What mocks cannot prove.

    uv run python scripts/try_researcher.py
    uv run python scripts/try_researcher.py "what to search for"

`tests/test_web_search.py` answers every request from a `MockTransport`, so it proves the
tool parses the payload *this repo assumes* Tavily returns. It cannot prove the assumption:
that the live API still names the field `published_date`, that the key works, or that a
model handed the tool actually cites what it read. That is this script's job.

Reads `GEMINI_API_KEY` and `TAVILY_API_KEY` from `.env`. Not a test: it costs money and
needs the network, so it stays out of `tests/` where `ALLOW_MODEL_REQUESTS` is off.
"""

import sys

from mycel.agents.agent.researcher import Researcher
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps
from mycel.observability.tracing import setup_tracing

PROMPT = "What is the current stable release of Python, and when was it published?"


def main() -> int:
    # Spans are batched, so the provider is flushed before the process exits — otherwise
    # a script that finishes in two seconds exports nothing.
    provider = setup_tracing()

    cfg = AgentSettings.from_config("researcher")
    prompt = sys.argv[1] if len(sys.argv) > 1 else PROMPT
    print(f"model: {cfg.model_spec}\n")

    deps = build_deps("try-researcher", ceiling_usd="0.50", settings=cfg)
    research = runner.run_sync(Researcher.build(cfg), prompt, deps)

    for claim in research.claims:
        print(f"  {claim.statement}")
        print(f"    as of {claim.as_of or 'unknown'} — {', '.join(claim.sources)}")
    for point in research.contested:
        print(f"  ? {point}")
    for gap in research.gaps:
        print(f"  ! {gap}")
    print(f"\nspent: ${deps.budget.spent_usd}")

    if provider is not None:
        provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
