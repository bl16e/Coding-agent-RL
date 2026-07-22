from __future__ import annotations

import json
import posixpath
import subprocess
import time
from typing import Any, Protocol

from coding_agent.models import FileModification, Outcome, TestResult, TestStatus, ToolName
from coding_agent.sandbox_manager import DockerCli, DockerCommandError, DockerCommandTimeout
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


def _parse_bounds(tool_input: dict[str, Any]) -> tuple[int, int] | None:
    """Parse optional line range from offset/limit.

    Returns (start, end) as a 1-based inclusive interval, or None to read the
    default page.
    """
    has_offset = "offset" in tool_input
    has_limit = "limit" in tool_input
    if not has_offset and not has_limit:
        return None
    start = int(tool_input.get("offset", 1))
    limit = int(tool_input.get("limit", 1))
    if start < 1:
        raise ValueError("offset must be >= 1")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return start, start + limit - 1


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


def _container_python_search_script() -> str:
    return _container_textio_prelude() + (
        "root=Path(sys.argv[1]); pat=sys.argv[2]; limit=int(sys.argv[3]); matches=[]; truncated=False; binary_skipped=0\n"
        "ignore_case=bool(int(sys.argv[4])) if len(sys.argv) > 4 else False\n"
        "glob_pat=sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else None\n"
        "ctx_before=max(0, int(sys.argv[6])) if len(sys.argv) > 6 else 0\n"
        "ctx_after=max(0, int(sys.argv[7])) if len(sys.argv) > 7 else 0\n"
        "ctx_around=max(0, int(sys.argv[8])) if len(sys.argv) > 8 else 0\n"
        "has_context=ctx_before > 0 or ctx_after > 0 or ctx_around > 0\n"
        "flags=re.IGNORECASE if ignore_case else 0\n"
        "try:\n"
        "    compiled=re.compile(pat, flags)\n"
        "except re.error as exc:\n"
        "    print(json.dumps({'error': f'invalid regular expression: {exc}'})); sys.exit(2)\n"
        "excluded={'.git','.venv','venv','node_modules','build','dist','.tox','__pycache__','.pytest_cache'}\n"
        "def _match_glob(rel_path, glob_pat):\n"
        "    if glob_pat is None or glob_pat == '**/*': return True\n"
        "    parts=glob_pat.split('/'); regex_parts=[]; prev_ds=False\n"
        "    for part in parts:\n"
        "        if part == '**':\n"
        "            if regex_parts: regex_parts.append('/')\n"
        "            regex_parts.append(r'(?:[^/]+/)*'); prev_ds=True\n"
        "        else:\n"
        "            escaped=re.escape(part); escaped=escaped.replace(r'\\*', '[^/]*'); escaped=escaped.replace(r'\\?', '[^/]')\n"
        "            if regex_parts and not prev_ds: regex_parts.append('/')\n"
        "            regex_parts.append(escaped); prev_ds=False\n"
        "    regex='^'+''.join(regex_parts)+'$'\n"
        "    return bool(re.match(regex, rel_path))\n"
        "for path in sorted(p for p in root.rglob('*') if p.is_file() and not any(part in excluded for part in p.relative_to(root).parts)):\n"
        "    if glob_pat:\n"
        "        rel=path.relative_to(root).as_posix()\n"
        "        if not _match_glob(rel, glob_pat): continue\n"
        "    try:\n"
        "        text, enc, nl = read_text(path)\n"
        "        lines=text.splitlines()\n"
        "    except BinaryFileError:\n"
        "        binary_skipped += 1\n"
        "        continue\n"
        "    except TextDecodeError: continue\n"
        "    for idx,line in enumerate(lines,1):\n"
        "        if compiled.search(line):\n"
        "            if len(matches) >= limit: truncated=True; break\n"
        "            entry={'path': path.relative_to(root).as_posix(), 'line': idx, 'text': line, 'encoding': enc, 'newline': nl}\n"
        "            if has_context:\n"
        "                bc=max(ctx_before, ctx_around); ac=max(ctx_after, ctx_around)\n"
        "                entry['context_before']=[{'line': i+1, 'text': lines[i]} for i in range(max(0, idx-bc-1), idx-1)]\n"
        "                entry['context_after']=[{'line': i+1, 'text': lines[i]} for i in range(idx, min(len(lines), idx+ac))]\n"
        "            matches.append(entry)\n"
        "    if truncated: break\n"
        "print(json.dumps({'matches': matches, 'truncated': truncated, 'binary_skipped': binary_skipped, 'files_searched': 0}, ensure_ascii=False))"
    )


def _container_helper_script() -> str:
    return _container_textio_prelude() + (
        "def ok(payload): return {'ok': True, 'payload': payload}\n"
        "def fail(message): return {'ok': False, 'error': message}\n"
        "def handle(req):\n"
        "    method=req.get('method'); params=req.get('params') or {}\n"
        "    try:\n"
        "        if method == 'read_file':\n"
        "            p=Path(params['path']); bounds=params.get('bounds')\n"
        "            text, enc, nl = read_text(p); lines=text.splitlines(keepends=True); total=len(text.splitlines())\n"
        "            if bounds is None: start=1; end=min(200, max(total, 1))\n"
        "            else: start=int(bounds[0]); end=int(bounds[1])\n"
        "            actual_end=min(end, total) if total else 0\n"
        "            selected=''.join(lines[start-1:actual_end]); actual_end=min(end, total) if total else 0\n"
        "            truncated=(False if total == 0 else start > 1 or actual_end < total)\n"
        "            if len(selected) > 50000:\n"
        "                selected=selected[:50000]; actual_end=min(total, start + max(1, len(selected.splitlines())) - 1); truncated=True\n"
        "            # Format with line numbers (cat -n style)\n"
        "            formatted=''\n"
        "            if selected:\n"
        "                sel_lines=selected.splitlines(keepends=True)\n"
        "                width=max(4, len(str(start + len(sel_lines) - 1)))\n"
        "                for i, line in enumerate(sel_lines):\n"
        "                    num = start + i\n"
        "                    if line.endswith('\\n'): formatted += f'{num:>{width}}\\t{line[:-1]}\\n'\n"
        "                    elif line.endswith('\\r\\n'): formatted += f'{num:>{width}}\\t{line[:-2]}\\r\\n'\n"
        "                    else: formatted += f'{num:>{width}}\\t{line}'\n"
        "            if truncated and total > actual_end:\n"
        "                remaining = total - actual_end\n"
        "                formatted = formatted.rstrip('\\n\\r') + f'\\n... [truncated, {remaining} lines remaining]\\n'\n"
        "            return ok({'content': formatted, 'encoding': enc, 'newline': nl, 'line_start': start if total else 0, 'line_end': actual_end, 'total_lines': total, 'truncated': truncated})\n"
        "        if method == 'write':\n"
        "            p=Path(params['path']); content=params.get('content',''); newline=params.get('newline','lf')\n"
        "            p.parent.mkdir(parents=True, exist_ok=True); write_text(p, content, 'utf-8', newline)\n"
        "            return ok({'status':'ok','encoding':'utf-8','newline':newline})\n"
        "        if method == 'update':\n"
        "            p=Path(params['path']); old=params.get('old_string',''); new=params.get('new_string','')\n"
        "            text, enc, nl = read_text(p); count=text.count(old)\n"
        "            if count == 0:\n"
        "                lines=text.splitlines()\n"
        "                scored=[(l, sum(1 for a,b in zip(old,l) if a==b)/max(len(old),len(l),1)) for l in lines]\n"
        "                scored.sort(key=lambda x: x[1], reverse=True)\n"
        "                hints=[l[:120] for l,r in scored[:3] if r > 0.3]\n"
        "                msg='not found'\n"
        "                if hints: msg+='\\nMost similar lines in the file:\\n'+'\\n'.join('  > '+h for h in hints)\n"
        "                return fail(msg)\n"
        "            if count > 1: return fail(f'appears {count} times')\n"
        "            write_text(p, text.replace(old,new,1), enc, nl)\n"
        "            return ok({'status':'ok','encoding':enc,'newline':nl})\n"
        "        if method == 'search_code':\n"
        "            root=Path(params['root']); pat=params['pattern']; limit=int(params.get('head_limit', 250)); matches=[]; truncated=False; binary_skipped=0\n"
        "            ignore_case=params.get('ignore_case', False); glob_pat=params.get('glob')\n"
        "            ctx_before=max(0, int(params.get('context_before', 0))); ctx_after=max(0, int(params.get('context_after', 0)))\n"
        "            ctx_around=max(0, int(params.get('context_around', 0))); has_context=ctx_before>0 or ctx_after>0 or ctx_around>0\n"
        "            flags=re.IGNORECASE if ignore_case else 0; compiled=re.compile(pat, flags)\n"
        "            excluded={'.git','.venv','venv','node_modules','build','dist','.tox','__pycache__','.pytest_cache'}\n"
        "            def _glob_ok(rel_path, gpat):\n"
        "                if gpat is None or gpat == '**/*': return True\n"
        "                parts=gpat.split('/'); rparts=[]; prev_ds=False\n"
        "                for pt in parts:\n"
        "                    if pt == '**':\n"
        "                        if rparts: rparts.append('/')\n"
        "                        rparts.append(r'(?:[^/]+/)*'); prev_ds=True\n"
        "                    else:\n"
        "                        e=re.escape(pt); e=e.replace(r'\\\\*', '[^/]*'); e=e.replace(r'\\\\?', '[^/]')\n"
        "                        if rparts and not prev_ds: rparts.append('/')\n"
        "                        rparts.append(e); prev_ds=False\n"
        "                return bool(re.match('^'+''.join(rparts)+'$', rel_path))\n"
        "            for path in sorted(p for p in root.rglob('*') if p.is_file() and not any(part in excluded for part in p.relative_to(root).parts)):\n"
        "                if glob_pat:\n"
        "                    rel=path.relative_to(root).as_posix()\n"
        "                    if not _glob_ok(rel, glob_pat): continue\n"
        "                try: text, enc, nl = read_text(path); lines=text.splitlines()\n"
        "                except BinaryFileError: binary_skipped += 1; continue\n"
        "                except TextDecodeError: continue\n"
        "                for idx,line in enumerate(lines,1):\n"
        "                    if compiled.search(line):\n"
        "                        if len(matches) >= limit: truncated=True; break\n"
        "                        entry={'path': path.relative_to(root).as_posix(), 'line': idx, 'text': line, 'encoding': enc, 'newline': nl}\n"
        "                        if has_context:\n"
        "                            bc=max(ctx_before, ctx_around); ac=max(ctx_after, ctx_around)\n"
        "                            entry['context_before']=[{'line': i+1, 'text': lines[i]} for i in range(max(0, idx-bc-1), idx-1)]\n"
        "                            entry['context_after']=[{'line': i+1, 'text': lines[i]} for i in range(idx, min(len(lines), idx+ac))]\n"
        "                        matches.append(entry)\n"
        "                if truncated: break\n"
        "            return ok({'matches': matches, 'truncated': truncated, 'binary_skipped': binary_skipped, 'files_searched': 0})\n"
        "    except Exception as exc:\n"
        "        return fail(str(exc))\n"
        "    return fail(f'unknown method: {method}')\n"
        "for line in sys.stdin:\n"
        "    try: response=handle(json.loads(line))\n"
        "    except Exception as exc: response=fail(str(exc))\n"
        "    print(json.dumps(response, ensure_ascii=False), flush=True)\n"
    )


class JsonRpcHelper(Protocol):
    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send one request to a long-lived container helper."""


class ContainerJsonRpcHelper:
    def __init__(self, *, container_name: str, repo_path: str) -> None:
        self._process = subprocess.Popen(
            ["docker", "exec", "-i", container_name, "python", "-u", "-c", _container_helper_script(), repo_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("container helper is not connected")
        self._process.stdin.write(json.dumps({"method": method, "params": params}, ensure_ascii=False) + "\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            raise RuntimeError("container helper stopped")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error", "container helper failed")))
        return dict(response.get("payload") or {})

    def close(self) -> None:
        self._process.terminate()


class ContainerToolExecutor:
    def __init__(
        self,
        *,
        docker: DockerCli,
        container_name: str,
        repo_path: str,
        allowed_test_commands: tuple[str, ...],
        test_timeout_seconds: float,
        helper: JsonRpcHelper | None = None,
    ) -> None:
        self._docker = docker
        self._container_name = container_name
        self._repo_path = repo_path
        self._allowed_test_commands = tuple(allowed_test_commands)
        self._test_timeout_seconds = test_timeout_seconds
        self._helper = helper
        self._helper_enabled = helper is not None or isinstance(docker, DockerCli)

    def _helper_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self._helper_enabled:
            return None
        try:
            if self._helper is None:
                self._helper = ContainerJsonRpcHelper(container_name=self._container_name, repo_path=self._repo_path)
            return self._helper.request(method, params)
        except Exception:
            self._helper_enabled = False
            self._helper = None
            return None

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
            path = _repo_file_path(self._repo_path, str(tool_input.get("file_path", "")))
            bounds = _parse_bounds(tool_input)
            output = self._helper_request("read_file", {"path": path, "bounds": bounds})
            if output is not None:
                if output.get("line_start") and (bounds is not None or output.get("truncated")):
                    output_summary = f"read lines {output['line_start']}-{output['line_end']} ({len(output['content'])} characters)"
                else:
                    output_summary = f"read {len(output['content'])} characters"
                return ToolExecutionResult(ToolName.READ_FILE, Outcome.OK, output_summary, output=output)
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
                "    start=1; end=min(200, max(total, 1))\n"
                "actual_end=min(end, total) if total else 0\n"
                "selected=''.join(lines[start-1:actual_end])\n"
                "truncated=(False if total == 0 else start > 1 or actual_end < total)\n"
                "if len(selected) > 50000:\n"
                "    selected=selected[:50000]\n"
                "    actual_end=min(total, start + max(1, len(selected.splitlines())) - 1)\n"
                "    truncated=True\n"
                "# Format with line numbers (cat -n style)\n"
                "formatted=''\n"
                "if selected:\n"
                "    sel_lines=selected.splitlines(keepends=True)\n"
                "    width=max(4, len(str(start + len(sel_lines) - 1)))\n"
                "    for i, line in enumerate(sel_lines):\n"
                "        num = start + i\n"
                "        if line.endswith('\\\\n'): formatted += f'{num:>{width}}\\\\t{line[:-1]}\\\\n'\n"
                "        elif line.endswith('\\\\r\\\\n'): formatted += f'{num:>{width}}\\\\t{line[:-2]}\\\\r\\\\n'\n"
                "        else: formatted += f'{num:>{width}}\\\\t{line}'\n"
                "if truncated and total > actual_end:\n"
                "    remaining = total - actual_end\n"
                "    formatted = formatted.rstrip('\\\\n\\\\r') + f'\\\\n... [truncated, {remaining} lines remaining]\\\\n'\n"
                "payload={'content': formatted, 'encoding': enc, 'newline': nl, 'line_start': start if total else 0, 'line_end': actual_end, 'total_lines': total, 'truncated': truncated}\n"
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
        if patch_type not in ("write", "update"):
            return ToolExecutionResult(
                ToolName.APPLY_PATCH,
                Outcome.REJECTED,
                f"type must be write or update, got: {patch_type}",
            )

        if patch_type == "write":
            content = tool_input.get("content", "")
            if not isinstance(content, str):
                return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "write requires string content")
            try:
                path = _repo_file_path(self._repo_path, str(tool_input.get("file_path", "")))
                relative_path = posixpath.relpath(path, self._repo_path)
                newline = str(tool_input.get("newline", "lf"))
                if newline not in {"lf", "crlf", "cr", "none"}:
                    newline = "lf"
                output = self._helper_request("write", {"path": path, "content": content, "newline": newline})
                if output is not None:
                    return ToolExecutionResult(
                        ToolName.APPLY_PATCH,
                        Outcome.OK,
                        f"wrote {relative_path}",
                        output={"encoding": output.get("encoding", "utf-8"), "newline": output.get("newline", "lf")},
                        modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
                    )
                script = _container_textio_prelude() + (
                    "p=Path(sys.argv[1])\n"
                    "newline=sys.argv[2]\n"
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
                f"wrote {relative_path}",
                output={"encoding": output.get("encoding", "utf-8"), "newline": output.get("newline", "lf")},
                modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
            )

        # patch_type == "update"
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        if not old_string:
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "update requires non-empty old_string")
        if not isinstance(new_string, str):
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "update requires new_string")
        try:
            path = _repo_file_path(self._repo_path, str(tool_input.get("file_path", "")))
            relative_path = posixpath.relpath(path, self._repo_path)
            output = self._helper_request("update", {"path": path, "old_string": old_string, "new_string": new_string})
            if output is not None:
                return ToolExecutionResult(
                    ToolName.APPLY_PATCH,
                    Outcome.OK,
                    f"applied edit to {relative_path}",
                    output={"encoding": output.get("encoding", "utf-8"), "newline": output.get("newline", "lf")},
                    modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
                )
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
                "    lines=content.splitlines()\n"
                "    scored=[(l, sum(1 for a,b in zip(old,l) if a==b)/max(len(old),len(l),1)) for l in lines]\n"
                "    scored.sort(key=lambda x: x[1], reverse=True)\n"
                "    hints=[l[:120] for l,r in scored[:3] if r > 0.3]\n"
                "    msg='not found'\n"
                "    if hints: msg+='\\nMost similar lines in the file:\\n'+'\\n'.join('  > '+h for h in hints)\n"
                "    print(json.dumps({'error':msg}))\n"
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

    def search_code(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        pattern = str(tool_input.get("pattern", ""))
        if not pattern:
            return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, "pattern must not be empty")
        head_limit = int(tool_input.get("head_limit", 250))
        ignore_case = bool(tool_input.get("ignore_case", False))
        glob_pat = tool_input.get("glob") or ""
        context_before = max(0, int(tool_input.get("context_before", 0)))
        context_after = max(0, int(tool_input.get("context_after", 0)))
        context_around = max(0, int(tool_input.get("context_around", 0)))
        try:
            output = self._search_code_with_rg(pattern, head_limit, ignore_case, glob_pat, context_before, context_after, context_around)
            if output is None:
                output = self._helper_request("search_code", {
                    "root": self._repo_path, "pattern": pattern, "head_limit": head_limit,
                    "ignore_case": ignore_case, "glob": glob_pat or None,
                    "context_before": context_before, "context_after": context_after,
                    "context_around": context_around,
                })
            if output is None:
                result = self._docker.exec(self._container_name, [
                    "python", "-c", _container_python_search_script(),
                    self._repo_path, pattern, str(head_limit),
                    "1" if ignore_case else "0", glob_pat,
                    str(context_before), str(context_after), str(context_around),
                ])
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

    def _search_code_with_rg(
        self, pattern: str, head_limit: int, ignore_case: bool, glob_pat: str,
        context_before: int, context_after: int, context_around: int,
    ) -> dict[str, Any] | None:
        try:
            probe = self._docker.exec(self._container_name, ["sh", "-lc", "command -v rg >/dev/null 2>&1"])
            if probe.returncode != 0:
                return None
            command = [
                "rg",
                "--json",
                "--line-number",
                "--max-count",
                str(head_limit),
            ]
            if ignore_case:
                command.append("--ignore-case")
            if context_before > 0:
                command.extend(["-B", str(context_before)])
            if context_after > 0:
                command.extend(["-A", str(context_after)])
            if context_around > 0:
                command.extend(["-C", str(context_around)])
            # Exclude directories
            for d in [".git", ".venv", "venv", "node_modules", "build", "dist", ".tox", "__pycache__", ".pytest_cache"]:
                command.extend(["--glob", f"!{d}/**"])
            # User glob
            if glob_pat:
                command.extend(["--glob", glob_pat])
            command.append(pattern)
            command.append(self._repo_path)
            result = self._docker.exec(self._container_name, command)
        except (DockerCommandError, DockerCommandTimeout):
            return None

        matches: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            if len(matches) >= head_limit:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event.get("data") or {}
            path_text = ((data.get("path") or {}).get("text") or "").strip()
            if path_text.startswith(self._repo_path.rstrip("/") + "/"):
                path_text = path_text[len(self._repo_path.rstrip("/") + "/") :]
            line_text = ((data.get("lines") or {}).get("text") or "").rstrip("\r\n")
            matches.append(
                {
                    "path": path_text,
                    "line": int(data.get("line_number") or 0),
                    "text": line_text,
                    "encoding": "unknown",
                    "newline": "unknown",
                }
            )
        return {"matches": matches, "truncated": len(matches) >= head_limit, "binary_skipped": 0, "engine": "rg"}

    def run_tests(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        command = str(tool_input.get("command", ""))
        started = time.monotonic()
        policy = validate_self_test_command(command)
        # Official eval scripts (from validation.allowed_commands) contain
        # multi-line shell with "set -euxo pipefail" and won't pass policy.
        # They still need shell=True execution.
        is_eval = command in self._allowed_test_commands
        if policy.allowed:
            exec_command = list(policy.argv)
            workdir = self._repo_path
        elif is_eval:
            exec_command = ["sh", "-lc", f"cd {self._repo_path} && {command}"]
            workdir = None
        else:
            output_summary = f"command is not allowed: {policy.reason}"
            test_result = TestResult(command, TestStatus.REJECTED, 0.0, output_summary=output_summary)
            return ToolExecutionResult(ToolName.RUN_TESTS, Outcome.REJECTED, output_summary, test_result=test_result)
        try:
            result = self._docker.exec(
                self._container_name,
                exec_command,
                timeout_seconds=self._test_timeout_seconds,
                workdir=workdir,
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
