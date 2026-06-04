from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from coding_agent.models import Outcome, TestResult, TestStatus, ToolName
from coding_agent.tools.result import ToolExecutionResult


def _summarize_output(stdout: str, stderr: str, limit: int = 4000) -> str:
    """Bound captured test output before storing it in trajectory artifacts."""

    combined = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
    return combined[:limit]


def run_tests(
    workspace: str | Path,
    tool_input: dict[str, Any],
    allowed_commands: tuple[str, ...],
    timeout_seconds: float,
) -> ToolExecutionResult:
    """Run one pre-declared test command in the task workspace.

    The command must exactly match a caller-provided allowlist entry. This keeps
    the model from turning the test tool into a general shell while preserving
    official SWE-Bench-style workflows where evaluators choose the test command.
    """

    command = str(tool_input.get("command", ""))
    started = time.monotonic()
    if command not in allowed_commands:
        test_result = TestResult(command, TestStatus.REJECTED, 0.0, output_summary="command is not allowed")
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.REJECTED, "command is not allowed", test_result=test_result)
    try:
        # shell=True is acceptable only because the exact command string was
        # allowlisted by the caller before reaching this point.
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
