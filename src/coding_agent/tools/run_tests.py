from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from coding_agent.models import Outcome, TestResult, TestStatus, ToolName
from coding_agent.tools.result import ToolExecutionResult


def _summarize_output(stdout: str, stderr: str, limit: int = 4000) -> str:
    """限制测试输出长度后再写入轨迹产物。

    测试失败时输出可能非常长；轨迹只需要足够诊断的信息，完整日志不应把 JSONL
    产物撑到难以读取。
    """

    combined = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
    return combined[:limit]


def run_tests(
    workspace: str | Path,
    tool_input: dict[str, Any],
    allowed_commands: tuple[str, ...],
    timeout_seconds: float,
) -> ToolExecutionResult:
    """在任务工作区运行一条预先声明的测试命令。

    命令必须精确匹配调用方提供的 allowlist。这样既保留官方 SWE-Bench 风格的
    “评估方指定测试命令”，又防止模型把测试工具变成通用 shell。
    """

    command = str(tool_input.get("command", ""))
    started = time.monotonic()
    if command not in allowed_commands:
        test_result = TestResult(command, TestStatus.REJECTED, 0.0, output_summary="command is not allowed")
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.REJECTED, "command is not allowed", test_result=test_result)
    try:
        # shell=True 只在这里可接受：命令字符串已经通过精确 allowlist 校验，模型
        # 无法在运行时拼接额外 shell 片段。
        completed = subprocess.run(
            command,
            cwd=Path(workspace),
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        output = _summarize_output(exc.stdout or "", exc.stderr or "")
        test_result = TestResult(command, TestStatus.TIMEOUT, duration, output_summary=output)
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.TIMEOUT, "test command timed out", test_result=test_result)
    except OSError as exc:
        duration = time.monotonic() - started
        test_result = TestResult(command, TestStatus.EXECUTION_ERROR, duration, output_summary=str(exc))
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.ERROR, str(exc), test_result=test_result)

    duration = time.monotonic() - started
    status = TestStatus.PASSED if completed.returncode == 0 else TestStatus.FAILED
    outcome = Outcome.OK if completed.returncode == 0 else Outcome.FAILED
    summary = _summarize_output(completed.stdout, completed.stderr)
    test_result = TestResult(command, status, duration, completed.returncode, summary)
    return ToolExecutionResult(ToolName.RUN_TESTS, outcome, summary or status.value, test_result=test_result)
