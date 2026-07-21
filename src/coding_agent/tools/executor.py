from __future__ import annotations

from pathlib import Path
from typing import Protocol

from coding_agent.models import ToolName
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.run_tests import run_tests
from coding_agent.tools.read_file import read_file
from coding_agent.tools.search_code import search_code
from coding_agent.tools.apply_patch import apply_patch


class ToolExecutor(Protocol):
    """Protocol boundary between the agent loop and tool execution.

    Both local workspaces and Docker containers implement this interface so
    agent.py only needs to select a tool name and input, without knowing
    where reads/writes happen.
    """

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        """Execute one already-selected tool action."""


class LocalToolExecutor:
    """Execute tools in a prepared local workspace."""

    def __init__(
        self,
        *,
        workspace: str | Path,
        test_timeout_seconds: float,
    ) -> None:
        self.workspace = Path(workspace)
        self.test_timeout_seconds = test_timeout_seconds

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        """Dispatch tool by name to the local implementation."""
        if tool_name is ToolName.READ_FILE:
            return read_file(self.workspace, tool_input)
        if tool_name is ToolName.APPLY_PATCH:
            return apply_patch(self.workspace, tool_input)
        if tool_name is ToolName.SEARCH_CODE:
            return search_code(self.workspace, tool_input)
        if tool_name is ToolName.RUN_TESTS:
            return run_tests(
                self.workspace,
                tool_input,
                timeout_seconds=self.test_timeout_seconds,
            )
        raise ValueError(f"unsupported tool: {tool_name}")
