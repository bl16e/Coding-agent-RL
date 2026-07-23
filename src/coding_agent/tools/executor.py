# src/coding_agent/tools/executor.py
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any, Protocol

from coding_agent.models import Outcome, TestResult, TestStatus, ToolName
from coding_agent.tools.read_file import read_file as _read_remote
from coding_agent.tools.apply_patch import apply_patch as _apply_remote
from coding_agent.tools.search_code import search_code as _search_remote
from coding_agent.tools.run_tests import run_tests as _run_tests_remote
from coding_agent.tools.result import ToolExecutionResult


class ToolExecutor(Protocol):
    """Protocol boundary between agent loop and tool execution."""
    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult: ...


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
        if tool_name is ToolName.SEARCH_CODE:
            return _local_search_code(self.workspace, tool_input)
        if tool_name is ToolName.RUN_TESTS:
            return _local_run_tests(self.workspace, tool_input, self.test_timeout_seconds)
        raise ValueError(f"unsupported tool: {tool_name}")


class SweRexToolExecutor:
    """Execute structured tools inside a SWE-ReX container."""

    def __init__(self, runtime: Any, *, workspace_path: str, test_timeout_seconds: float):
        self._runtime = runtime
        self._workspace_path = workspace_path
        self._test_timeout_seconds = test_timeout_seconds

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        if tool_name is ToolName.READ_FILE:
            return _read_remote(self._runtime, workspace_path=self._workspace_path, tool_input=tool_input)
        if tool_name is ToolName.APPLY_PATCH:
            return _apply_remote(self._runtime, workspace_path=self._workspace_path, tool_input=tool_input)
        if tool_name is ToolName.SEARCH_CODE:
            return _search_remote(self._runtime, workspace_path=self._workspace_path, tool_input=tool_input)
        if tool_name is ToolName.RUN_TESTS:
            return _run_tests_remote(self._runtime, workspace_path=self._workspace_path, tool_input=tool_input, timeout_seconds=self._test_timeout_seconds)
        raise ValueError(f"unsupported tool: {tool_name}")


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
    patch_type = tool_input.get("type", "")
    fp = str(tool_input.get("file_path", ""))
    if patch_type not in ("write", "update"):
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, f"invalid type: {patch_type}")
    if not fp:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "file_path must not be empty")
    target = _resolve_local(workspace, fp)
    if target is None:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, f"path escapes workspace: {fp}")
    if patch_type == "write":
        content = tool_input.get("content", "")
        if not isinstance(content, str):
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "write requires string content")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.ERROR, str(exc))
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.OK, f"wrote {fp}")
    # update
    old = tool_input.get("old_string", "")
    new = tool_input.get("new_string", "")
    if not old:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "old_string must not be empty")
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
    return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.OK, f"applied edit to {fp}")


def _local_search_code(workspace: Path, tool_input: dict) -> ToolExecutionResult:
    pattern = str(tool_input.get("pattern", ""))
    if not pattern:
        return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, "pattern must not be empty")
    try:
        compiled = re.compile(pattern, re.IGNORECASE if tool_input.get("ignore_case") else 0)
    except re.error as exc:
        return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, f"invalid regex: {exc}")
    matches = []
    head_limit = int(tool_input.get("head_limit", 250))
    exclude = {".git", ".venv", "venv", "node_modules", "build", "dist", ".tox", "__pycache__", ".pytest_cache"}
    for f in sorted(workspace.rglob("*")):
        if not f.is_file():
            continue
        if set(f.relative_to(workspace).parts) & exclude:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines()):
                if compiled.search(line):
                    matches.append({"path": f.relative_to(workspace).as_posix(), "line": i + 1, "text": line})
                    if len(matches) >= head_limit:
                        break
        except Exception:
            continue
        if len(matches) >= head_limit:
            break
    return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.OK, f"found {len(matches)} matches", output={"matches": matches})


def _local_run_tests(workspace: Path, tool_input: dict, timeout_seconds: float) -> ToolExecutionResult:
    targets = str(tool_input.get("targets", "")).strip()
    if not targets:
        tr = TestResult("", TestStatus.REJECTED, 0.0, output_summary="targets is required")
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.REJECTED, "targets must not be empty", test_result=tr)
    started = time.monotonic()
    argv = ["python", "-m", "pytest"] + targets.split() + ["-x", "--tb=short"]
    try:
        completed = subprocess.run(argv, cwd=workspace, shell=False, text=True, capture_output=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        tr = TestResult(targets, TestStatus.TIMEOUT, time.monotonic() - started, output_summary="timeout")
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.TIMEOUT, "timeout", test_result=tr)
    except OSError as exc:
        tr = TestResult(targets, TestStatus.EXECUTION_ERROR, time.monotonic() - started, output_summary=str(exc))
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.ERROR, str(exc), test_result=tr)
    duration = time.monotonic() - started
    status = TestStatus.PASSED if completed.returncode == 0 else TestStatus.FAILED
    outcome = Outcome.OK if completed.returncode == 0 else Outcome.FAILED
    summary = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()[:4000]
    tr = TestResult(targets, status, duration, completed.returncode, output_summary=summary)
    return ToolExecutionResult(ToolName.RUN_TESTS, outcome, summary or status.value, test_result=tr)
