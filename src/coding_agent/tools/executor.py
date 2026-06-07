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
    """Small boundary between the agent loop and repository tool location."""

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        """Execute one already-selected tool action."""


class LocalToolExecutor:
    """Execute tools against a prepared local workspace."""

    def __init__(
        self,
        *,
        workspace: str | Path,
        allowed_test_commands: tuple[str, ...],
        test_timeout_seconds: float,
    ) -> None:
        self.workspace = Path(workspace)
        self.allowed_test_commands = tuple(allowed_test_commands)
        self.test_timeout_seconds = test_timeout_seconds

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
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
                self.allowed_test_commands,
                self.test_timeout_seconds,
            )
        raise ValueError(f"unsupported tool: {tool_name}")
