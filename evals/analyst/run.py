"""Run the analyst golden set against gold and report what it scored.

    EVAL_USER=you@example.com uv run python -m evals.analyst.run [--model REF] [--save-baseline]

`--model` takes a picker ref: `host:<name>`, or `own:<id>` for one of EVAL_USER's own models.

Spends real model calls (about 2-4 per case): run by hand, never in CI.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelResponse, ToolCallPart

from evals.analyst.case import Case, Run, load_all
from evals.common import CEILING_USD
from evals.summarizer.run import Result, report
from mycel.agents.core import runner
from mycel.agents.core.model_source import ModelSource
from mycel.agents.core.settings import AgentSettings
from mycel.agents.registry import build_deps
from mycel.agents.specialists.analyst import Analysis, Analyst
from mycel.core.principal import Principal
from mycel.domains.chat_model import model_source
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.infra.postgres.session import session_scope

GOLDEN = Path(__file__).parent / "golden"
BASELINE = Path(__file__).parent / "baseline.json"


async def principal() -> Principal | None:
    """Whose gold the run reads; without one every tool returns nothing."""
    email = os.environ.get("EVAL_USER", "").strip()
    if not email:
        return None
    async with session_scope() as session:
        user = await IdentityRepository(session).user_by_email(email)
    return Principal(id=user.id, email=user.email) if user else None


async def run_case(
    case: Case, cfg: AgentSettings, who: Principal | None, model: ModelSource | None
) -> Result:
    deps = build_deps(f"eval:{case.name}", CEILING_USD, settings=cfg, principal=who, model=model)
    with capture_run_messages() as messages:
        try:
            analysis = await runner.run(Analyst.build(cfg), case.question, deps)
        except Exception as exc:
            return Result(case.name, [], error=f"{type(exc).__name__}: {exc}")
    assert isinstance(analysis, Analysis)
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    tools = [p.tool_name for m in responses for p in m.parts if isinstance(p, ToolCallPart)]
    return Result(case.name, case.check(Run(analysis, tools, len(responses))))


async def run_all(cases: list[Case], model: str | None) -> list[Result]:
    who = await principal()
    if who is None:
        print("EVAL_USER unset or unknown: gold reads as empty\n")
    cfg = AgentSettings.from_config("analyst")
    source = await model_source(who.id, model) if model and who else None
    return [await run_case(case, cfg, who, source) for case in cases]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", help="picker ref (host:<name> or own:<id>) instead of the default"
    )
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--compare-baseline", action="store_true")
    args = parser.parse_args(argv)

    overall = report(asyncio.run(run_all(load_all(GOLDEN), args.model)))
    key = args.model or "default"
    saved = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    if args.save_baseline:
        saved[key] = round(overall, 4)
        BASELINE.write_text(json.dumps(saved, indent=2) + "\n")
        print(f"  baseline saved for {key}: {overall:.3f}")
    if args.compare_baseline and key in saved:
        print(f"  baseline {saved[key]:.3f}")
        if round(overall, 4) < saved[key]:
            print("  SCORE DROPPED")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
