from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_agent.models import ToolName
from coding_agent.tools.executor import LocalToolExecutor, ToolExecutor
from coding_agent.tools.read_file import read_file
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.run_tests import run_tests
from coding_agent.tools.search_code import search_code
from coding_agent.tools.write_file import write_file


def dispatch_tool(
    *,
    tool_name: ToolName,
    workspace: str | Path,
    tool_input: dict[str, Any],
    allowed_test_commands: tuple[str, ...],
    test_timeout_seconds: float,
) -> ToolExecutionResult:
    """Route an already-approved agent action to the concrete tool.

    The dispatcher is the only place where orchestration code knows about the
    concrete tool modules. Keeping this map centralized makes it obvious which
    tools are available to the model and prevents individual tools from needing
    model or trajectory dependencies.
    """

    return LocalToolExecutor(
        workspace=workspace,
        allowed_test_commands=allowed_test_commands,
        test_timeout_seconds=test_timeout_seconds,
    ).execute(tool_name, tool_input)


__all__ = [
    "LocalToolExecutor",
    "ToolExecutionResult",
    "ToolExecutor",
    "dispatch_tool",
    "read_file",
    "write_file",
    "search_code",
    "run_tests",
]
