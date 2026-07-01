from __future__ import annotations

import json
import posixpath
import time
from typing import Any

from coding_agent.models import FileModification, Outcome, TestResult, TestStatus, ToolName
from coding_agent.sandbox.docker_cli import DockerCli, DockerCommandError, DockerCommandTimeout
from coding_agent.tools.test_command_policy import validate_self_test_command
from coding_agent.tools.result import ToolExecutionResult


def _repo_file_path(repo_path: str, requested_path: str) -> str:
    """解析容器内仓库路径，并阻止路径逃逸。

    Docker 容器里使用 POSIX 路径，因此这里不能复用宿主机 Path。先拼接、规范化，再
    检查结果仍位于 repo_path 下，避免模型通过 ../../ 读写仓库外文件。
    """
    if not requested_path:
        raise ValueError("path is required")
    relative = requested_path.lstrip("/")
    normalized = posixpath.normpath(posixpath.join(repo_path, relative))
    repo_root = posixpath.normpath(repo_path)
    if normalized != repo_root and not normalized.startswith(repo_root.rstrip("/") + "/"):
        raise ValueError("path escapes workspace")
    return normalized


def _docker_error(tool_name: ToolName, exc: Exception) -> ToolExecutionResult:
    """把 Docker 异常转换为工具结果，避免异常穿透 agent loop。"""
    return ToolExecutionResult(tool_name, Outcome.ERROR, str(exc))


def _line_bounds(tool_input: dict[str, Any]) -> tuple[int, int] | None:
    """兼容 offset/limit 和 line/end_line 两套行号参数。"""
    if "line" in tool_input:
        start = int(tool_input["line"])
        if "end_line" in tool_input:
            end = int(tool_input["end_line"])
        elif "limit" in tool_input:
            limit = int(tool_input["limit"])
            if limit < 1:
                raise ValueError("limit must be a positive integer")
            end = start + limit - 1
        else:
            end = start
        if start < 1 or end < start:
            raise ValueError("line range must be 1-based and end_line must be >= line")
        return start, end
    if "offset" in tool_input or "limit" in tool_input:
        start = int(tool_input.get("offset", 1))
        limit = int(tool_input.get("limit", 1))
        if start < 1 or limit < 1:
            raise ValueError("offset and limit must be 1-based positive integers")
        return start, start + limit - 1
    if "end_line" not in tool_input:
        return None
    end = int(tool_input["end_line"])
    if end < 1:
        raise ValueError("line range must be 1-based and end_line must be >= line")
    return 1, end


class ContainerToolExecutor:
    """在已准备好的任务容器中执行仓库工具。

    它实现与 LocalToolExecutor 相同的 execute 接口，因此 agent.py 不需要知道工具
    最终跑在宿主机还是 Docker 容器里。
    """

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
        """按工具名分发到容器内实现。"""
        if tool_name is ToolName.READ_FILE:
            return self.read_file(tool_input)
        if tool_name is ToolName.APPLY_PATCH:
            return self.apply_patch(tool_input)
        if tool_name is ToolName.SEARCH_CODE:
            return self.search_code(tool_input)
        if tool_name is ToolName.RUN_TESTS:
            return self.run_tests(tool_input)
        raise ValueError(f"unsupported tool: {tool_name}")

    def read_file(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        """在容器内读取 UTF-8 文本文件。"""
        try:
            path = _repo_file_path(self._repo_path, str(tool_input.get("path", "")))
            bounds = _line_bounds(tool_input)
            if bounds is None:
                # 通过 python -c 读取文件，避免依赖容器里是否安装 sed/head/tail 等工具。
                script = "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text(encoding='utf-8'), end='')"
                result = self._docker.exec(self._container_name, ["python", "-c", script, path])
                output_summary = f"read {len(result.stdout)} characters"
            else:
                # 行号切片在容器内完成，宿主侧只接收最终文本，减少大文件传输。
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

    def apply_patch(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        """在容器内执行受限文件修改。

        这里没有暴露任意 patch 命令，而是只支持 add_file/update/move 三类结构化操作，
        便于记录修改摘要并保持与本地工具的行为一致。
        """
        patch_type = tool_input.get("type", "")
        if patch_type not in ("add_file", "update", "move"):
            return ToolExecutionResult(
                ToolName.APPLY_PATCH, Outcome.REJECTED,
                f"patch type must be add_file, update, or move, got: {patch_type}",
            )

        if patch_type == "add_file":
            content = tool_input.get("content", "")
            if not isinstance(content, str):
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "add_file requires string content")
            try:
                path = _repo_file_path(self._repo_path, str(tool_input.get("path", "")))
                relative_path = posixpath.relpath(path, self._repo_path)
                # stdin 承载文件内容，避免把大段文本拼进命令参数。
                script = (
                    "from pathlib import Path\n"
                    "import sys\n"
                    "p=Path(sys.argv[1])\n"
                    "if p.exists():\n"
                    "    print('file exists')\n"
                    "    sys.exit(1)\n"
                    "p.parent.mkdir(parents=True, exist_ok=True)\n"
                    "p.write_text(sys.stdin.read(), encoding='utf-8')\n"
                )
                self._docker.exec(self._container_name, ["python", "-c", script, path], stdin=content)
            except ValueError as exc:
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
            except (DockerCommandError, DockerCommandTimeout) as exc:
                return _docker_error(ToolName.APPLY_PATCH, exc)
            return ToolExecutionResult(
                ToolName.APPLY_PATCH, Outcome.OK, f"created {relative_path}",
                modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
            )

        if patch_type == "update":
            old_string = tool_input.get("old_string", "")
            new_string = tool_input.get("new_string", "")
            if not old_string:
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "update requires non-empty old_string")
            if not isinstance(new_string, str):
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "update requires new_string")
            try:
                path = _repo_file_path(self._repo_path, str(tool_input.get("path", "")))
                relative_path = posixpath.relpath(path, self._repo_path)
                # update 要求 old_string 只出现一次，促使模型提供足够上下文，避免误改。
                script = (
                    "from pathlib import Path\n"
                    "import json\n"
                    "import sys\n"
                    "p=Path(sys.argv[1])\n"
                    "old=sys.argv[2]\n"
                    "new=sys.argv[3]\n"
                    "content=p.read_text(encoding='utf-8')\n"
                    "count=content.count(old)\n"
                    "if count == 0:\n"
                    "    print(json.dumps({'error':'not found'}))\n"
                    "    sys.exit(1)\n"
                    "if count > 1:\n"
                    "    print(json.dumps({'error':f'appears {count} times'}))\n"
                    "    sys.exit(1)\n"
                    "new_content=content.replace(old,new,1)\n"
                    "p.write_text(new_content,encoding='utf-8')\n"
                    "print(json.dumps({'status':'ok'}))"
                )
                self._docker.exec(self._container_name, ["python", "-c", script, path, old_string, new_string])
            except ValueError as exc:
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
            except (DockerCommandError, DockerCommandTimeout) as exc:
                return _docker_error(ToolName.APPLY_PATCH, exc)
            return ToolExecutionResult(
                ToolName.APPLY_PATCH, Outcome.OK, f"applied edit to {relative_path}",
                modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
            )

        # move
        old_path_str = tool_input.get("old_path", "")
        new_path_str = tool_input.get("new_path", "")
        if not old_path_str or not new_path_str:
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "move requires old_path and new_path")
        try:
            old_path = _repo_file_path(self._repo_path, old_path_str)
            new_path = _repo_file_path(self._repo_path, new_path_str)
            old_relative = posixpath.relpath(old_path, self._repo_path)
            new_relative = posixpath.relpath(new_path, self._repo_path)
            script = (
                "from pathlib import Path; import sys; "
                "old=Path(sys.argv[1]); new=Path(sys.argv[2]); "
                "if not old.exists(): print('src missing'); sys.exit(1)\n"
                "if new.exists(): print('dst exists'); sys.exit(1)\n"
                "new.parent.mkdir(parents=True, exist_ok=True); old.rename(new)"
            )
            self._docker.exec(self._container_name, ["python", "-c", script, old_path, new_path])
        except ValueError as exc:
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
        except (DockerCommandError, DockerCommandTimeout) as exc:
            return _docker_error(ToolName.APPLY_PATCH, exc)
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.OK, f"moved {old_relative} -> {new_relative}",
            modifications=[
                FileModification(path=old_relative, write_status=Outcome.OK),
                FileModification(path=new_relative, write_status=Outcome.OK),
            ],
        )

    def search_code(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        """在容器内递归搜索文本文件。

        这是一版标准库实现，避免依赖容器中是否存在 rg。遇到非 UTF-8 文件会跳过，
        与 read_file/apply_patch 的文本文件假设保持一致。
        """
        query = str(tool_input.get("query", ""))
        if not query:
            return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, "query must not be empty")
        max_results = int(tool_input.get("max_results", 20))
        script = (
            "from pathlib import Path; import json, re, sys; "
            "root=Path(sys.argv[1]); query=sys.argv[2]; limit=int(sys.argv[3]); matches=[]; truncated=False\n"
            "try:\n"
            "    pattern=re.compile(query)\n"
            "except re.error as exc:\n"
            "    print(json.dumps({'error': f'invalid regular expression: {exc}'})); sys.exit(2)\n"
            "for path in sorted(p for p in root.rglob('*') if p.is_file()):\n"
            "    try: lines=path.read_text(encoding='utf-8').splitlines()\n"
            "    except UnicodeDecodeError: continue\n"
            "    for idx,line in enumerate(lines,1):\n"
            "        if pattern.search(line):\n"
            "            if len(matches) >= limit: truncated=True; break\n"
            "            matches.append({'path': path.relative_to(root).as_posix(), 'line': idx, 'text': line})\n"
            "    if truncated: break\n"
            "print(json.dumps({'matches': matches, 'truncated': truncated}))"
        )
        try:
            result = self._docker.exec(self._container_name, ["python", "-c", script, self._repo_path, query, str(max_results)])
            output = json.loads(result.stdout or '{"matches": [], "truncated": false}')
            if isinstance(output, dict) and output.get("error"):
                return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, str(output["error"]))
        except (DockerCommandError, DockerCommandTimeout, json.JSONDecodeError) as exc:
            return _docker_error(ToolName.SEARCH_CODE, exc)
        return ToolExecutionResult(
            ToolName.SEARCH_CODE,
            Outcome.OK,
            f"found {len(output.get('matches', []))} matches",
            output=output,
        )

    def run_tests(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        """在容器内执行测试或诊断命令。"""
        command = str(tool_input.get("command", ""))
        started = time.monotonic()
        policy = validate_self_test_command(command)
        use_shell = command in self._allowed_test_commands and not policy.allowed
        if not use_shell and not policy.allowed:
            output_summary = f"command is not allowed: {policy.reason}"
            test_result = TestResult(command, TestStatus.REJECTED, 0.0, output_summary=output_summary)
            return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.REJECTED, output_summary, test_result=test_result)
        exec_command = ["sh", "-lc", f"cd {self._repo_path} && {command}"] if use_shell else list(policy.argv)
        try:
            result = self._docker.exec(
                self._container_name,
                exec_command,
                timeout_seconds=self._test_timeout_seconds,
                workdir=None if use_shell else self._repo_path,
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
