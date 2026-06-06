from __future__ import annotations

import json
import posixpath
import time
from typing import Any

from coding_agent.models import FileModification, Outcome, TestResult, TestStatus, ToolName
from coding_agent.sandbox.docker_cli import DockerCli, DockerCommandError, DockerCommandTimeout
from coding_agent.tools.result import ToolExecutionResult


def _repo_file_path(repo_path: str, requested_path: str) -> str:
    if not requested_path:
        raise ValueError("path is required")
    relative = requested_path.lstrip("/")
    normalized = posixpath.normpath(posixpath.join(repo_path, relative))
    repo_root = posixpath.normpath(repo_path)
    if normalized != repo_root and not normalized.startswith(repo_root.rstrip("/") + "/"):
        raise ValueError("path escapes workspace")
    return normalized


def _docker_error(tool_name: ToolName, exc: Exception) -> ToolExecutionResult:
    return ToolExecutionResult(tool_name, Outcome.ERROR, str(exc))


def _line_bounds(tool_input: dict[str, Any]) -> tuple[int, int] | None:
    if "offset" in tool_input or "limit" in tool_input:
        start = int(tool_input.get("offset", 1))
        limit = int(tool_input.get("limit", 1))
        if start < 1 or limit < 1:
            raise ValueError("offset and limit must be 1-based positive integers")
        return start, start + limit - 1
    if "line" not in tool_input and "end_line" not in tool_input:
        return None
    start = int(tool_input.get("line", 1))
    end = int(tool_input.get("end_line", start))
    if start < 1 or end < start:
        raise ValueError("line range must be 1-based and end_line must be >= line")
    return start, end


class ContainerToolExecutor:
    """Execute the agent repository tools inside a prepared task container."""

    def __init__(
        self,
        *,
        docker: DockerCli,
        container_name: str,
        repo_path: str,
        allowed_test_commands: tuple[str, ...],
        test_timeout_seconds: float,
    ) -> None:
        self._docker = docker
        self._container_name = container_name
        self._repo_path = repo_path
        self._allowed_test_commands = tuple(allowed_test_commands)
        self._test_timeout_seconds = test_timeout_seconds

    def execute(self, tool_name: ToolName, tool_input: dict[str, Any]) -> ToolExecutionResult:
        if tool_name is ToolName.READ_FILE:
            return self.read_file(tool_input)
        if tool_name is ToolName.WRITE_FILE:
            return self.write_file(tool_input)
        if tool_name is ToolName.SEARCH_CODE:
            return self.search_code(tool_input)
        if tool_name is ToolName.RUN_TESTS:
            return self.run_tests(tool_input)
        raise ValueError(f"unsupported tool: {tool_name}")

    def read_file(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        try:
            path = _repo_file_path(self._repo_path, str(tool_input.get("path", "")))
            bounds = _line_bounds(tool_input)
            if bounds is None:
                script = "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text(encoding='utf-8'), end='')"
                result = self._docker.exec(self._container_name, ["python", "-c", script, path])
                output_summary = f"read {len(result.stdout)} characters"
            else:
                script = (
                    "from pathlib import Path; import sys; "
                    "lines=Path(sys.argv[1]).read_text(encoding='utf-8').splitlines(keepends=True); "
                    "start=int(sys.argv[2]); end=int(sys.argv[3]); "
                    "print(''.join(lines[start-1:end]), end='')"
                )
                result = self._docker.exec(self._container_name, ["python", "-c", script, path, str(bounds[0]), str(bounds[1])])
                output_summary = f"read lines {bounds[0]}-{bounds[1]} ({len(result.stdout)} characters)"
        except (TypeError, ValueError) as exc:
            return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, str(exc))
        except (DockerCommandError, DockerCommandTimeout) as exc:
            return _docker_error(ToolName.READ_FILE, exc)
        return ToolExecutionResult(
            ToolName.READ_FILE,
            Outcome.OK,
            output_summary,
            output={"content": result.stdout},
        )

    def write_file(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        if "content" not in tool_input or not isinstance(tool_input.get("content"), str):
            return ToolExecutionResult(ToolName.WRITE_FILE, Outcome.REJECTED, "write_file requires complete file content")
        try:
            path = _repo_file_path(self._repo_path, str(tool_input.get("path", "")))
            script = (
                "from pathlib import Path; import sys; "
                "p=Path(sys.argv[1]); p.parent.mkdir(parents=True, exist_ok=True); "
                "p.write_text(sys.stdin.read(), encoding='utf-8')"
            )
            self._docker.exec(self._container_name, ["python", "-c", script, path], stdin=tool_input["content"])
        except ValueError as exc:
            return ToolExecutionResult(ToolName.WRITE_FILE, Outcome.REJECTED, str(exc))
        except (DockerCommandError, DockerCommandTimeout) as exc:
            return _docker_error(ToolName.WRITE_FILE, exc)
        relative_path = posixpath.relpath(path, self._repo_path)
        return ToolExecutionResult(
            ToolName.WRITE_FILE,
            Outcome.OK,
            f"wrote {relative_path}",
            modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
        )

    def search_code(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        query = str(tool_input.get("query", ""))
        if not query:
            return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, "query must not be empty")
        max_results = int(tool_input.get("max_results", 20))
        script = (
            "from pathlib import Path; import json, sys; "
            "root=Path(sys.argv[1]); query=sys.argv[2]; limit=int(sys.argv[3]); matches=[]; truncated=False\n"
            "for path in sorted(p for p in root.rglob('*') if p.is_file()):\n"
            "    try: lines=path.read_text(encoding='utf-8').splitlines()\n"
            "    except UnicodeDecodeError: continue\n"
            "    for idx,line in enumerate(lines,1):\n"
            "        if query in line:\n"
            "            if len(matches) >= limit: truncated=True; break\n"
            "            matches.append({'path': path.relative_to(root).as_posix(), 'line': idx, 'text': line})\n"
            "    if truncated: break\n"
            "print(json.dumps({'matches': matches, 'truncated': truncated}))"
        )
        try:
            result = self._docker.exec(self._container_name, ["python", "-c", script, self._repo_path, query, str(max_results)])
            output = json.loads(result.stdout or '{"matches": [], "truncated": false}')
        except (DockerCommandError, DockerCommandTimeout, json.JSONDecodeError) as exc:
            return _docker_error(ToolName.SEARCH_CODE, exc)
        return ToolExecutionResult(
            ToolName.SEARCH_CODE,
            Outcome.OK,
            f"found {len(output.get('matches', []))} matches",
            output=output,
        )

    def run_tests(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        command = str(tool_input.get("command", ""))
        started = time.monotonic()
        if command not in self._allowed_test_commands:
            test_result = TestResult(command, TestStatus.REJECTED, 0.0, output_summary="command is not allowed")
            return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.REJECTED, "command is not allowed", test_result=test_result)
        try:
            result = self._docker.exec(
                self._container_name,
                ["sh", "-lc", f"cd {self._repo_path} && {command}"],
                timeout_seconds=self._test_timeout_seconds,
            )
        except DockerCommandTimeout:
            duration = time.monotonic() - started
            test_result = TestResult(command, TestStatus.TIMEOUT, duration, output_summary="test command timed out")
            return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.TIMEOUT, "test command timed out", test_result=test_result)
        except DockerCommandError as exc:
            duration = time.monotonic() - started
            output = (exc.result.stdout + exc.result.stderr).strip()[:4000]
            test_result = TestResult(command, TestStatus.FAILED, duration, exc.result.returncode, output)
            return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.FAILED, output or "failed", test_result=test_result)
        duration = time.monotonic() - started
        output = (result.stdout + result.stderr).strip()[:4000]
        test_result = TestResult(command, TestStatus.PASSED, duration, result.returncode, output)
        return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.OK, output or "passed", test_result=test_result)
