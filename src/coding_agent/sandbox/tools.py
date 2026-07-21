from __future__ import annotations

import json
import posixpath
import time
from typing import Any

from coding_agent.models import FileModification, Outcome, TestResult, TestStatus, ToolName
from coding_agent.sandbox.docker_cli import DockerCli, DockerCommandError, DockerCommandTimeout
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.tools.test_command_policy import validate_self_test_command


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


def _container_textio_prelude() -> str:
    return (
        "from pathlib import Path\n"
        "import json, re, sys\n"
        "class BinaryFileError(Exception): pass\n"
        "class TextDecodeError(Exception): pass\n"
        "def looks_binary(data):\n"
        "    if not data: return False\n"
        "    if b'\\x00' in data: return True\n"
        "    control=sum(1 for b in data if b < 32 and b not in (9,10,12,13))\n"
        "    return control / len(data) > 0.30\n"
        "def detect_newline(data):\n"
        "    crlf=data.count(b'\\r\\n')\n"
        "    normalized=data.replace(b'\\r\\n', b'')\n"
        "    lf=normalized.count(b'\\n')\n"
        "    cr=normalized.count(b'\\r')\n"
        "    kinds=sum(1 for c in (crlf,lf,cr) if c)\n"
        "    if kinds == 0: return 'none'\n"
        "    if kinds > 1: return 'mixed'\n"
        "    if crlf: return 'crlf'\n"
        "    if cr: return 'cr'\n"
        "    return 'lf'\n"
        "def read_text(path):\n"
        "    data=path.read_bytes()\n"
        "    if looks_binary(data): raise BinaryFileError('binary file is not supported')\n"
        "    for enc in ('utf-8','gbk'):\n"
        "        try: return data.decode(enc), enc, detect_newline(data)\n"
        "        except UnicodeDecodeError: pass\n"
        "    raise TextDecodeError('file is not supported text; tried utf-8, gbk')\n"
        "def normalize_newlines(content, newline):\n"
        "    seq={'lf':'\\n','crlf':'\\r\\n','cr':'\\r'}.get(newline)\n"
        "    if seq is None: return content\n"
        "    normalized=content.replace('\\r\\n','\\n').replace('\\r','\\n')\n"
        "    return normalized.replace('\\n', seq)\n"
        "def write_text(path, content, encoding, newline):\n"
        "    path.write_bytes(normalize_newlines(content, newline).encode(encoding))\n"
    )


class ContainerToolExecutor:
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
        if tool_name is ToolName.APPLY_PATCH:
            return self.apply_patch(tool_input)
        if tool_name is ToolName.SEARCH_CODE:
            return self.search_code(tool_input)
        if tool_name is ToolName.RUN_TESTS:
            return self.run_tests(tool_input)
        raise ValueError(f"unsupported tool: {tool_name}")

    def read_file(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        try:
            path = _repo_file_path(self._repo_path, str(tool_input.get("path", "")))
            bounds = _line_bounds(tool_input)
            script = _container_textio_prelude() + (
                "p=Path(sys.argv[1])\n"
                "start=int(sys.argv[2]) if sys.argv[2] else None\n"
                "end=int(sys.argv[3]) if sys.argv[3] else None\n"
                "try:\n"
                "    text, enc, nl = read_text(p)\n"
                "except (BinaryFileError, TextDecodeError) as exc:\n"
                "    print(json.dumps({'error': str(exc)})); sys.exit(1)\n"
                "lines=text.splitlines(keepends=True)\n"
                "total=len(text.splitlines())\n"
                "if start is None:\n"
                "    start=1; end=min(1000, max(total, 1))\n"
                "selected=''.join(lines[start-1:end])\n"
                "actual_end=min(end, total) if total else 0\n"
                "payload={'content': selected, 'encoding': enc, 'newline': nl, 'line_start': start if total else 0, 'line_end': actual_end, 'total_lines': total, 'truncated': (False if total == 0 else start > 1 or end < total)}\n"
                "print(json.dumps(payload, ensure_ascii=False))\n"
            )
            start_arg = "" if bounds is None else str(bounds[0])
            end_arg = "" if bounds is None else str(bounds[1])
            result = self._docker.exec(self._container_name, ["python", "-c", script, path, start_arg, end_arg])
            output = json.loads(result.stdout)
            if output.get("line_start") and (bounds is not None or output.get("truncated")):
                output_summary = f"read lines {output['line_start']}-{output['line_end']} ({len(output['content'])} characters)"
            else:
                output_summary = f"read {len(output['content'])} characters"
        except (TypeError, ValueError) as exc:
            return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, str(exc))
        except DockerCommandError as exc:
            try:
                payload = json.loads(exc.result.stdout or "{}")
            except json.JSONDecodeError:
                return _docker_error(ToolName.READ_FILE, exc)
            return ToolExecutionResult(ToolName.READ_FILE, Outcome.FAILED, str(payload.get("error") or exc))
        except (DockerCommandTimeout, json.JSONDecodeError) as exc:
            return _docker_error(ToolName.READ_FILE, exc)
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.OK, output_summary, output=output)

    def apply_patch(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        patch_type = tool_input.get("type", "")
        if patch_type not in ("add_file", "update", "move"):
            return ToolExecutionResult(
                ToolName.APPLY_PATCH,
                Outcome.REJECTED,
                f"patch type must be add_file, update, or move, got: {patch_type}",
            )

        if patch_type == "add_file":
            content = tool_input.get("content", "")
            if not isinstance(content, str):
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "add_file requires string content")
            try:
                path = _repo_file_path(self._repo_path, str(tool_input.get("path", "")))
                relative_path = posixpath.relpath(path, self._repo_path)
                newline = str(tool_input.get("newline", "lf"))
                if newline not in {"lf", "crlf", "cr", "none"}:
                    newline = "lf"
                script = _container_textio_prelude() + (
                    "p=Path(sys.argv[1])\n"
                    "newline=sys.argv[2]\n"
                    "if p.exists():\n"
                    "    print(json.dumps({'error':'file exists'}))\n"
                    "    sys.exit(1)\n"
                    "p.parent.mkdir(parents=True, exist_ok=True)\n"
                    "write_text(p, sys.stdin.read(), 'utf-8', newline)\n"
                    "print(json.dumps({'status':'ok','encoding':'utf-8','newline':newline}))\n"
                )
                result = self._docker.exec(self._container_name, ["python", "-c", script, path, newline], stdin=content)
                output = json.loads(result.stdout or "{}")
            except ValueError as exc:
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
            except DockerCommandError as exc:
                try:
                    payload = json.loads(exc.result.stdout or "{}")
                except json.JSONDecodeError:
                    return _docker_error(ToolName.APPLY_PATCH, exc)
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, str(payload.get("error") or exc))
            except (DockerCommandTimeout, json.JSONDecodeError) as exc:
                return _docker_error(ToolName.APPLY_PATCH, exc)
            return ToolExecutionResult(
                ToolName.APPLY_PATCH,
                Outcome.OK,
                f"created {relative_path}",
                output={"encoding": output.get("encoding", "utf-8"), "newline": output.get("newline", "lf")},
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
                script = _container_textio_prelude() + (
                    "p=Path(sys.argv[1])\n"
                    "old=sys.argv[2]\n"
                    "new=sys.argv[3]\n"
                    "try:\n"
                    "    content, enc, nl = read_text(p)\n"
                    "except (BinaryFileError, TextDecodeError) as exc:\n"
                    "    print(json.dumps({'error': str(exc)}))\n"
                    "    sys.exit(1)\n"
                    "count=content.count(old)\n"
                    "if count == 0:\n"
                    "    print(json.dumps({'error':'not found'}))\n"
                    "    sys.exit(1)\n"
                    "if count > 1:\n"
                    "    print(json.dumps({'error':f'appears {count} times'}))\n"
                    "    sys.exit(1)\n"
                    "new_content=content.replace(old,new,1)\n"
                    "write_text(p,new_content,enc,nl)\n"
                    "print(json.dumps({'status':'ok','encoding':enc,'newline':nl}))"
                )
                result = self._docker.exec(self._container_name, ["python", "-c", script, path, old_string, new_string])
                output = json.loads(result.stdout or "{}")
            except ValueError as exc:
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
            except DockerCommandError as exc:
                try:
                    payload = json.loads(exc.result.stdout or "{}")
                except json.JSONDecodeError:
                    return _docker_error(ToolName.APPLY_PATCH, exc)
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, str(payload.get("error") or exc))
            except (DockerCommandTimeout, json.JSONDecodeError) as exc:
                return _docker_error(ToolName.APPLY_PATCH, exc)
            return ToolExecutionResult(
                ToolName.APPLY_PATCH,
                Outcome.OK,
                f"applied edit to {relative_path}",
                output={"encoding": output.get("encoding", "utf-8"), "newline": output.get("newline", "lf")},
                modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
            )

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
            ToolName.APPLY_PATCH,
            Outcome.OK,
            f"moved {old_relative} -> {new_relative}",
            modifications=[
                FileModification(path=old_relative, write_status=Outcome.OK),
                FileModification(path=new_relative, write_status=Outcome.OK),
            ],
        )

    def search_code(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        query = str(tool_input.get("query", ""))
        if not query:
            return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, "query must not be empty")
        max_results = int(tool_input.get("max_results", 20))
        script = _container_textio_prelude() + (
            "root=Path(sys.argv[1]); query=sys.argv[2]; limit=int(sys.argv[3]); matches=[]; truncated=False; binary_skipped=0\n"
            "try:\n"
            "    pattern=re.compile(query)\n"
            "except re.error as exc:\n"
            "    print(json.dumps({'error': f'invalid regular expression: {exc}'})); sys.exit(2)\n"
            "for path in sorted(p for p in root.rglob('*') if p.is_file()):\n"
            "    try:\n"
            "        text, enc, nl = read_text(path)\n"
            "        lines=text.splitlines()\n"
            "    except BinaryFileError:\n"
            "        binary_skipped += 1\n"
            "        continue\n"
            "    except TextDecodeError: continue\n"
            "    for idx,line in enumerate(lines,1):\n"
            "        if pattern.search(line):\n"
            "            if len(matches) >= limit: truncated=True; break\n"
            "            matches.append({'path': path.relative_to(root).as_posix(), 'line': idx, 'text': line, 'encoding': enc, 'newline': nl})\n"
            "    if truncated: break\n"
            "print(json.dumps({'matches': matches, 'truncated': truncated, 'binary_skipped': binary_skipped}, ensure_ascii=False))"
        )
        try:
            result = self._docker.exec(self._container_name, ["python", "-c", script, self._repo_path, query, str(max_results)])
            output = json.loads(result.stdout or '{"matches": [], "truncated": false, "binary_skipped": 0}')
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
