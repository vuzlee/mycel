"""The MCP client against a server that actually answers."""

import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

import mycel.mcp.clients as clients
from mycel.core.exceptions import ConfigError

pytestmark = pytest.mark.anyio

SERVER = Path(__file__).parent / "fixtures" / "mcp_echo_server.py"


def _ctx() -> RunContext[Any]:
    """The minimum context `get_tools` needs to resolve a tool's retry budget."""
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


@pytest.fixture
def echo_config(tmp_path: Path) -> Path:
    """A config naming the fixture server, run under the interpreter running the tests."""
    path = tmp_path / "mcp.yaml"
    path.write_text(
        "servers:\n"
        "  echo:\n"
        "    transport: stdio\n"
        f"    command: {sys.executable}\n"
        f"    args: [{SERVER}]\n",
        encoding="utf-8",
    )
    return path


class TestTalkingToARealServer:
    async def test_the_declared_tools_arrive(self, echo_config: Path) -> None:
        """What the model will be offered is what the server actually exposes."""
        (toolset,) = clients.build_toolsets(config_path=echo_config)
        async with toolset:
            tools = await toolset.get_tools(_ctx())
        assert sorted(tools) == ["echo", "read_note"]

    async def test_a_tool_runs_with_its_arguments(self, echo_config: Path) -> None:
        """The part construction alone cannot show: arguments cross the boundary intact."""
        (toolset,) = clients.build_toolsets(config_path=echo_config)
        assert isinstance(toolset, MCPToolset)
        async with toolset:
            result = await toolset.direct_call_tool("echo", {"text": "xin chào"})
        assert "xin chào" in str(result)

    async def test_a_tool_reads_a_file_through_the_server(self, echo_config: Path) -> None:
        """A tool with side effects, not just one that reflects its input back."""
        (toolset,) = clients.build_toolsets(config_path=echo_config)
        assert isinstance(toolset, MCPToolset)
        async with toolset:
            result = await toolset.direct_call_tool("read_note", {"name": "hello"})
        assert "separate files" in str(result)

    async def test_the_server_refuses_a_path_outside_its_sandbox(self, echo_config: Path) -> None:
        """`name` comes from a model, so `../../.env` is an ordinary string to it."""
        (toolset,) = clients.build_toolsets(config_path=echo_config)
        assert isinstance(toolset, MCPToolset)
        async with toolset:
            with pytest.raises(Exception, match="outside the sandbox|Error executing tool"):
                await toolset.direct_call_tool("read_note", {"name": "../../../etc/passwd"})


class TestFailingWell:
    async def test_a_server_that_cannot_start_fails_when_it_is_used(self, tmp_path: Path) -> None:
        """Not at build time."""
        path = tmp_path / "mcp.yaml"
        path.write_text(
            "servers:\n"
            "  dead:\n"
            "    transport: stdio\n"
            f"    command: {sys.executable}\n"
            "    args: [-c, 'raise SystemExit(1)']\n",
            encoding="utf-8",
        )

        (toolset,) = clients.build_toolsets(config_path=path)  # no raise
        # Deliberately broad: the transport's exception class is a fastmcp detail.
        with pytest.raises(Exception):  # noqa: B017
            async with toolset:
                await toolset.get_tools(_ctx())

    def test_naming_an_undeclared_server_says_which_one(self, echo_config: Path) -> None:
        """The error names the server and what is available, so the fix is obvious."""
        with pytest.raises(ConfigError, match="absent"):
            clients.build_toolsets(["absent"], config_path=echo_config)
