from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from coding_agent.models import Outcome, TestResult, TestStatus, ToolName
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.test_command_policy import validate_self_test_command


def _summarize_output(stdout: str, stderr: str, limit: int = 4000) -> str:
    """Truncate test output before writing to trajectory artifacts."""

    out = stdout or ""
    err = stderr or ""
    combined = (out + ("\n" if out and err else "") + err).strip()
    return combined[:limit]


def run_tests(
    workspace: str | Path,
    tool_input: dict[str, Any],
    *,
    timeout_seconds: float,
) -> ToolExecutionResult:
    """Run a self-test or diagnostic command in the task workspace.

    Commands are validated against a safety policy that blocks destructive
    operations (curl, rm, git push, sudo, etc.) while allowing pytest, python
    diagnostics, and read-only git inspection.
    """

    command = str(tool_input.get("command", ""))
    description = str(tool_input.get("description", ""))
    started = time.monotonic()

    policy = validate_self_test_command(command)
    if not policy.allowed:
        test_result = TestResult(command, TestStatus.REJECTED, 0.0, output_summary=policy.reason)
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.REJECTED, policy.reason, test_result=test_result,
        )

    argv = list(policy.argv)
    try:
        # shell=False: each argument is passed safely without interpretation.
        completed = subprocess.run(
            argv,
            cwd=Path(workspace),
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        output = _summarize_output(exc.stdout or "", exc.stderr or "")
        test_result = TestResult(command, TestStatus.TIMEOUT, duration, output_summary=output)
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.TIMEOUT, "test command timed out", test_result=test_result,
        )
    except OSError as exc:
        duration = time.monotonic() - started
        test_result = TestResult(command, TestStatus.EXECUTION_ERROR, duration, output_summary=str(exc))
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.ERROR, str(exc), test_result=test_result,
        )

    duration = time.monotonic() - started
    status = TestStatus.PASSED if completed.returncode == 0 else TestStatus.FAILED
    outcome = Outcome.OK if completed.returncode == 0 else Outcome.FAILED
    summary = _summarize_output(completed.stdout, completed.stderr)
    test_result = TestResult(command, status, duration, completed.returncode, summary)
    return ToolExecutionResult(
        ToolName.RUN_TESTS, outcome, summary or status.value, test_result=test_result,
    )
