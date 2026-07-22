# src/coding_agent/tools/executor.py
from __future__ import annotations

from typing import Protocol

from coding_agent.models import ToolName
from coding_agent.tools.apply_patch import apply_patch
from coding_agent.tools.read_file import read_file
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.run_tests import run_tests
from coding_agent.tools.search_code import search_code


class ToolExecutor(Protocol):
    """Protocol boundary between agent loop and tool execution."""
    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult: ...


class SweRexToolExecutor:
    """Execute structured tools inside a SWE-ReX container.

    All tool I/O goes through the AbstractRuntime, which ensures
    reads/writes/executions happen inside the task container.
    """

    def __init__(
        self,
        runtime,  # AbstractRuntime
        *,
        workspace_path: str,
        test_timeout_seconds: float,
    ):
        self._runtime = runtime
        self._workspace_path = workspace_path
        self._test_timeout_seconds = test_timeout_seconds

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        if tool_name is ToolName.READ_FILE:
            return read_file(
                self._runtime,
                workspace_path=self._workspace_path,
                tool_input=tool_input,
            )
        if tool_name is ToolName.APPLY_PATCH:
            return apply_patch(
                self._runtime,
                workspace_path=self._workspace_path,
                tool_input=tool_input,
            )
        if tool_name is ToolName.SEARCH_CODE:
            return search_code(
                self._runtime,
                workspace_path=self._workspace_path,
                tool_input=tool_input,
            )
        if tool_name is ToolName.RUN_TESTS:
            return run_tests(
                self._runtime,
                workspace_path=self._workspace_path,
                tool_input=tool_input,
                timeout_seconds=self._test_timeout_seconds,
            )
        raise ValueError(f"unsupported tool: {tool_name}")
