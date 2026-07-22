# src/coding_agent/tools/run_tests.py
from __future__ import annotations

import asyncio
import time
from typing import Any

from swerex.runtime.abstract import Command

from coding_agent.models import Outcome, TestResult, TestStatus, ToolName
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.test_command_policy import validate_self_test_command


def _summarize_output(stdout: str, stderr: str, limit: int = 4000) -> str:
    out = stdout or ""
    err = stderr or ""
    combined = (out + ("\n" if out and err else "") + err).strip()
    return combined[:limit]


def run_tests(
    runtime: Any,
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
    timeout_seconds: float,
) -> ToolExecutionResult:
    """Run a self-test command in the container via SWE-ReX runtime."""
    command = str(tool_input.get("command", ""))
    started = time.monotonic()

    policy = validate_self_test_command(command)
    if not policy.allowed:
        test_result = TestResult(
            command, TestStatus.REJECTED, 0.0,
            output_summary=policy.reason,
        )
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.REJECTED,
            policy.reason, test_result=test_result,
        )

    argv = list(policy.argv)
    cmd_str = " ".join(argv)
    try:
        response = asyncio.run(runtime.execute(Command(
            command=cmd_str,
            cwd=workspace_path,
            timeout=timeout_seconds,
            check=False,
        )))
    except asyncio.TimeoutError:
        duration = time.monotonic() - started
        test_result = TestResult(
            command, TestStatus.TIMEOUT, duration,
            output_summary="command timed out",
        )
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.TIMEOUT,
            "test command timed out", test_result=test_result,
        )
    except Exception as exc:
        duration = time.monotonic() - started
        test_result = TestResult(
            command, TestStatus.EXECUTION_ERROR, duration,
            output_summary=str(exc),
        )
        return ToolExecutionResult(
            ToolName.RUN_TESTS, Outcome.ERROR, str(exc),
            test_result=test_result,
        )

    duration = time.monotonic() - started
    status = TestStatus.PASSED if response.exit_code == 0 else TestStatus.FAILED
    outcome = Outcome.OK if response.exit_code == 0 else Outcome.FAILED
    summary = _summarize_output(response.stdout, response.stderr)
    test_result = TestResult(
        command, status, duration, response.exit_code,
        output_summary=summary,
    )
    return ToolExecutionResult(
        ToolName.RUN_TESTS, outcome,
        summary or status.value, test_result=test_result,
    )
