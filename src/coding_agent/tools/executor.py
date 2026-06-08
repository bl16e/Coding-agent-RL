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
    """agent loop 与仓库工具执行位置之间的协议边界。

    本地工作区和 Docker 容器都实现这个接口，因此 agent.py 只需要选择工具名和输入，
    不需要知道读写发生在哪个文件系统里。
    """

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        """Execute one already-selected tool action."""


class LocalToolExecutor:
    """在已准备好的本地工作区中执行工具。"""

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
        """按工具名分发到本地实现。

        与 ContainerToolExecutor 保持同样入口，是本地模式和 Docker 模式复用 agent loop
        的关键。
        """
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
