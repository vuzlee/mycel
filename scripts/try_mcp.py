"""Give a real agent a real MCP server, and see whether the model uses it.

    uv run python scripts/try_mcp.py
    uv run python scripts/try_mcp.py "ask something else"

`tests/test_mcp_live.py` starts the same server and calls its tools directly, which proves
the transport works. It cannot prove the last step: that a tool arriving over MCP reaches
the model as something it understands and chooses to call. A tool the model never calls is
indistinguishable from a tool that does not exist, and only a real model shows the
difference.

Costs money and needs `GEMINI_API_KEY`, so it stays out of `tests/`.
"""

import sys
from pathlib import Path

from pydantic import BaseModel, Field

from mycel.agents.core import runner
from mycel.agents.core.base import BaseAgent
from mycel.agents.core.config import AgentSettings
from mycel.agents.registry import build_deps
from mycel.observability.tracing import setup_tracing

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "tests" / "fixtures" / "mcp_echo_server.py"

PROMPT = "Read the note called 'hello' and tell me what it says."


class Answer(BaseModel):
    """Deliberately plain: this script is about the tool call, not the output schema."""

    answer: str = Field(description="What the note says, in one sentence.")
    tool_used: str | None = Field(
        default=None, description="Which tool you called to find out, if any."
    )


class Prober(BaseAgent[Answer]):
    """An agent that has nothing but MCP tools, so a wrong answer can only come from
    the model's own memory — which is the failure this script is looking for."""

    name = "mcp-prober"
    instructions = (
        "Answer using your tools. You have no knowledge of this repository, so if a tool "
        "cannot tell you, say so rather than guessing."
    )
    output_type = Answer


def main() -> int:
    provider = setup_tracing()

    config = ROOT / "scripts" / "_mcp_probe.yaml"
    config.write_text(
        "servers:\n"
        "  echo:\n"
        "    transport: stdio\n"
        f"    command: {sys.executable}\n"
        f"    args: [{SERVER}]\n",
        encoding="utf-8",
    )

    try:
        # `mcp_servers` is what wires the server in — the agent class above names no
        # toolset at all, which is the point.
        cfg = AgentSettings.from_config("researcher")
        cfg = AgentSettings(**{**cfg.__dict__, "mcp_servers": ("echo",)})
        print(f"model: {cfg.model_spec}\nserver: {SERVER.name}\n")

        prompt = sys.argv[1] if len(sys.argv) > 1 else PROMPT
        deps = build_deps("try-mcp", ceiling_usd="0.50", settings=cfg)
        answer = runner.run_sync(Prober.build(cfg), prompt, deps)

        print(f"  {answer.answer}")
        print(f"  via tool: {answer.tool_used or '(none reported)'}")
        print(f"\nspent: ${deps.budget.spent_usd}")
    finally:
        config.unlink(missing_ok=True)
        if provider is not None:
            provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
