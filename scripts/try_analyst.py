"""Run the analyst against a real model. The one thing tests cannot prove.

    uv run python scripts/try_analyst.py
    uv run python scripts/try_analyst.py local:qwen3-4b

Reads the credential its spec needs from `.env`. Not a test: it costs money and needs the
network, so it stays out of `tests/` where `ALLOW_MODEL_REQUESTS` is off.
"""

import sys
from dataclasses import replace

from mycel.agents.agent.analyst import Analyst
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps
from mycel.observability.tracing import setup_tracing

PROMPT = """\
Revenue: Q1 1,200,000 USD -> Q2 1,410,000 USD.
Tickets: Q1 840 -> Q2 902.

Report the growth in each, and whether they moved together.
"""


def main() -> int:
    # Spans are batched, so the provider is flushed before the process exits — otherwise
    # a script that finishes in two seconds exports nothing.
    provider = setup_tracing()

    cfg = AgentSettings.from_config("analyst")
    if len(sys.argv) > 1:
        cfg = replace(cfg, model_spec=sys.argv[1])
    print(f"model: {cfg.model_spec}\n")

    deps = build_deps("try-analyst", ceiling_usd="0.50", settings=cfg)
    analysis = runner.run_sync(Analyst.build(cfg), PROMPT, deps)

    for f in analysis.figures:
        print(f"  {f.label}: {f.value} {f.unit or ''}  [{f.source}]")
    for finding in analysis.findings:
        print(f"  - {finding}")
    for caveat in analysis.caveats:
        print(f"  ! {caveat}")
    print(f"\nspent: ${deps.budget.spent_usd}")

    if provider is not None:
        provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
