# src/coding_agent/tools/executor.py
from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Protocol

from coding_agent.models import Outcome, TestResult, TestStatus, ToolName
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.search_code import search_code


class ToolExecutor(Protocol):
    """Protocol boundary between agent loop and tool execution."""
    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult: ...


def to_cli_command(tool_name: ToolName, tool_input: dict[str, Any]) -> str:
    """Convert a function call to a CLI command string (R2E-Gym pattern).

    This produces commands that invoke standalone scripts installed at
    /usr/local/bin/ inside the container.
    """
    if tool_name is ToolName.EXECUTE_BASH:
        cmd = tool_input.get("command", "")
        return f"bash -lc {shlex.quote(cmd)}"

    if tool_name is ToolName.FINISH:
        result = tool_input.get("result", "")
        if result:
            return f"finish --result {shlex.quote(result)}"
        return "finish"

    if tool_name is ToolName.READ_FILE:
        fp = shlex.quote(str(tool_input.get("file_path", "")))
        cli = f"read_file --file_path {fp}"
        vr = tool_input.get("view_range")
        if vr and len(vr) == 2:
            cli += f" --view_range {int(vr[0])} {int(vr[1])}"
        return cli

    if tool_name is ToolName.APPLY_PATCH:
        fp = shlex.quote(str(tool_input.get("path", "")))
        old_raw = str(tool_input.get("old_string", ""))
        new = shlex.quote(str(tool_input.get("new_string", "")))
        if old_raw:
            old = shlex.quote(old_raw)
            return f"apply_patch --path {fp} --old_string {old} --new_string {new}"
        return f"apply_patch --path {fp} --new_string {new}"

    if tool_name in (ToolName.SEARCH, ToolName.SEARCH_CODE):
        pattern = shlex.quote(str(tool_input.get("pattern", "")))
        cli = f"search --pattern {pattern}"
        glob_pat = tool_input.get("glob")
        if glob_pat:
            cli += f" --glob {shlex.quote(str(glob_pat))}"
        hl = tool_input.get("head_limit")
        if hl is not None:
            cli += f" --head_limit {int(hl)}"
        return cli

    raise ValueError(f"cannot convert to CLI: {tool_name}")


class LocalToolExecutor:
    """Execute tools on the local filesystem (no Docker)."""

    def __init__(self, *, workspace: str | Path, test_timeout_seconds: float):
        self.workspace = Path(workspace).resolve()
        self.test_timeout_seconds = test_timeout_seconds

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        if tool_name is ToolName.READ_FILE:
            return _local_read_file(self.workspace, tool_input)
        if tool_name is ToolName.APPLY_PATCH:
            return _local_apply_patch(self.workspace, tool_input)
        if tool_name in (ToolName.SEARCH, ToolName.SEARCH_CODE):
            return _local_search_code(self.workspace, tool_input)
        if tool_name is ToolName.EXECUTE_BASH:
            return _local_execute_bash(self.workspace, tool_input)
        if tool_name is ToolName.FINISH:
            return _local_finish(tool_input)
        raise ValueError(f"unsupported tool: {tool_name}")


class SweRexToolExecutor:
    """Execute tools inside a SWE-ReX container.

    Structured tools are dispatched as CLI commands via the runtime's
    execute() method, matching the standalone-script pattern.
    """

    def __init__(self, runtime: Any, *, workspace_path: str, test_timeout_seconds: float):
        self._runtime = runtime
        self._workspace_path = workspace_path
        self._test_timeout_seconds = test_timeout_seconds

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        if tool_name is ToolName.EXECUTE_BASH:
            return _remote_execute_bash(self._runtime, workspace_path=self._workspace_path, tool_input=tool_input)
        if tool_name is ToolName.FINISH:
            return _local_finish(tool_input)
        # Structured tools: convert to CLI and run via runtime.execute()
        return _remote_run_cli(self._runtime, tool_name, tool_input,
                               workspace_path=self._workspace_path)


# -- local tool implementations --

def _resolve_local(workspace: Path, file_path: str) -> Path | None:
    target = (workspace / file_path).resolve()
    try:
        target.relative_to(workspace)
    except ValueError:
        return None
    return target


def _local_read_file(workspace: Path, tool_input: dict) -> ToolExecutionResult:
    fp = str(tool_input.get("file_path", ""))
    if not fp:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, "file_path must not be empty")
    target = _resolve_local(workspace, fp)
    if target is None:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, f"path escapes workspace: {fp}")
    if not target.is_file():
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.FAILED, f"file not found: {fp}")
    try:
        content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.FAILED, str(exc))
    lines = content.splitlines()
    width = max(4, len(str(len(lines))))
    formatted = "".join(f"{i+1:>{width}}\t{line}\n" for i, line in enumerate(lines))
    if len(formatted) > 50000:
        formatted = formatted[:50000] + "\n... [truncated]\n"
    return ToolExecutionResult(ToolName.READ_FILE, Outcome.OK, f"read {len(content)} chars", output={"content": formatted, "encoding": "utf-8"})


def _local_apply_patch(workspace: Path, tool_input: dict) -> ToolExecutionResult:
    fp = str(tool_input.get("path", ""))
    old = str(tool_input.get("old_string", ""))
    new = str(tool_input.get("new_string", ""))
    if not fp:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "path must not be empty")
    target = _resolve_local(workspace, fp)
    if target is None:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, f"path escapes workspace: {fp}")

    # Create mode
    if not old:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new, encoding="utf-8")
        except OSError as exc:
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.ERROR, str(exc))
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.OK, f"Created: {fp}")

    # Update mode
    if not target.is_file():
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, f"file not found: {fp}")
    try:
        content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, str(exc))
    count = content.count(old)
    if count == 0:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, f"old_string not found in {fp}")
    if count > 1:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, f"old_string appears {count} times")
    try:
        target.write_text(content.replace(old, new, 1), encoding="utf-8")
    except OSError as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.ERROR, str(exc))
    return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.OK, f"Patched: {fp}")


def _local_search_code(workspace: Path, tool_input: dict) -> ToolExecutionResult:
    return search_code(workspace, tool_input)


# -- execute_bash / finish local implementations --

_BASH_ENV = "export PYTHONWARNINGS=ignore && "
_BLOCKED_BASH_COMMANDS = {
    "git", "ipython", "jupyter", "nohup",
    "cat", "head", "tail", "less", "more",
    "grep", "find", "awk", "sed",
}
_BASH_TIMEOUT = 30.0


def _local_execute_bash(workspace: Path, tool_input: dict) -> ToolExecutionResult:
    command = str(tool_input.get("command", "")).strip()
    if not command:
        return ToolExecutionResult(
            ToolName.EXECUTE_BASH, Outcome.REJECTED, "command must not be empty",
        )
    for subcmd in command.split("&&") + command.split(";"):
        if sub_first := subcmd.strip().split()[0] if subcmd.strip().split() else "":
            if sub_first in _BLOCKED_BASH_COMMANDS:
                return ToolExecutionResult(
                    ToolName.EXECUTE_BASH, Outcome.REJECTED,
                    f"'{sub_first}' is blocked - use search or read_file instead",
                )
    started = time.monotonic()
    try:
        completed = subprocess.run(
            ["bash", "-lc", _BASH_ENV + command],
            cwd=workspace, shell=False, text=True,
            capture_output=True, timeout=_BASH_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - started
        return ToolExecutionResult(
            ToolName.EXECUTE_BASH, Outcome.TIMEOUT,
            f"command timed out after {_BASH_TIMEOUT}s",
            output={"stdout": "", "stderr": "", "exit_code": -1, "duration_seconds": duration},
        )
    except OSError as exc:
        return ToolExecutionResult(
            ToolName.EXECUTE_BASH, Outcome.ERROR, str(exc),
            output={"stdout": "", "stderr": str(exc), "exit_code": -1, "duration_seconds": time.monotonic() - started},
        )
    duration = time.monotonic() - started
    stdout = completed.stdout.rstrip()
    stderr = completed.stderr.rstrip()
    output_summary = stdout[:200] if stdout else stderr[:200] or "(no output)"
    if completed.returncode != 0:
        if stdout:
            return ToolExecutionResult(
                ToolName.EXECUTE_BASH, Outcome.OK,
                f"[exit {completed.returncode}] {output_summary}",
                output={"stdout": stdout, "stderr": stderr, "exit_code": completed.returncode, "duration_seconds": duration},
            )
        return ToolExecutionResult(
            ToolName.EXECUTE_BASH, Outcome.FAILED,
            f"[exit {completed.returncode}] {stderr[:200] if stderr else '(no output)'}",
            output={"stdout": stdout, "stderr": stderr, "exit_code": completed.returncode, "duration_seconds": duration},
        )
    return ToolExecutionResult(
        ToolName.EXECUTE_BASH, Outcome.OK, output_summary,
        output={"stdout": stdout, "stderr": stderr, "exit_code": 0, "duration_seconds": duration},
    )


def _local_finish(tool_input: dict) -> ToolExecutionResult:
    result_msg = str(tool_input.get("result", "")).strip()
    return ToolExecutionResult(
        ToolName.FINISH, Outcome.OK,
        result_msg or "task submitted",
        output={"submission": result_msg},
    )


def _remote_execute_bash(runtime: Any, *, workspace_path: str, tool_input: dict) -> ToolExecutionResult:
    command = str(tool_input.get("command", "")).strip()
    if not command:
        return ToolExecutionResult(
            ToolName.EXECUTE_BASH, Outcome.REJECTED, "command must not be empty",
        )
    for subcmd in command.split("&&") + command.split(";"):
        if sub_first := subcmd.strip().split()[0] if subcmd.strip().split() else "":
            if sub_first in _BLOCKED_BASH_COMMANDS:
                return ToolExecutionResult(
                    ToolName.EXECUTE_BASH, Outcome.REJECTED,
                    f"'{sub_first}' is blocked - use search or read_file instead",
                )
    try:
        output, error_code = runtime.run(
            ["bash", "-lc", _BASH_ENV + command], timeout=_BASH_TIMEOUT,
        )
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.EXECUTE_BASH, Outcome.ERROR, str(exc),
            output={"stdout": "", "stderr": str(exc), "exit_code": -1},
        )
    if error_code != 0:
        if output and output.strip():
            return ToolExecutionResult(
                ToolName.EXECUTE_BASH, Outcome.OK,
                f"[exit {error_code}] {output[:200]}",
                output={"stdout": output, "stderr": "", "exit_code": error_code},
            )
        return ToolExecutionResult(
            ToolName.EXECUTE_BASH, Outcome.FAILED,
            f"[exit {error_code}] (no output)",
            output={"stdout": output, "stderr": "", "exit_code": error_code},
        )
    return ToolExecutionResult(
        ToolName.EXECUTE_BASH, Outcome.OK,
        output[:200] if output else "(no output)",
        output={"stdout": output, "stderr": "", "exit_code": 0},
    )


def _remote_run_cli(
    runtime: Any, tool_name: ToolName, tool_input: dict,
    *, workspace_path: str,
) -> ToolExecutionResult:
    """Run a structured tool as a CLI command via the SWE-ReX runtime."""
    cli_cmd = to_cli_command(tool_name, tool_input)
    try:
        output, error_code = runtime.run(
            ["bash", "-lc", _BASH_ENV + cli_cmd], timeout=60,
        )
    except Exception as exc:
        return ToolExecutionResult(
            tool_name, Outcome.ERROR, str(exc),
            output={"stdout": "", "stderr": str(exc), "exit_code": -1},
        )
    if error_code != 0:
        return ToolExecutionResult(
            tool_name, Outcome.FAILED,
            f"[exit {error_code}] {output[:200] if output else '(no output)'}",
            output={"stdout": output, "stderr": "", "exit_code": error_code},
        )
    return ToolExecutionResult(
        tool_name, Outcome.OK,
        output[:200] if output else "(no output)",
        output={"stdout": output, "stderr": "", "exit_code": 0},
    )
