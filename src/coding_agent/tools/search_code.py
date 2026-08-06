# src/coding_agent/tools/search_code.py
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from swerex.runtime.abstract import Command

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    ".tox",
    "__pycache__",
    ".pytest_cache",
}


def _looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    control = sum(1 for byte in data if byte < 32 and byte not in (9, 10, 12, 13))
    return control / len(data) > 0.30


def _newline_style(data: bytes) -> str:
    if b"\r\n" in data:
        return "crlf"
    if b"\r" in data:
        return "cr"
    return "lf"


def _decode_text(data: bytes) -> tuple[str, str] | None:
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None


def _match_glob(rel_path: str, glob_pattern: str | None) -> bool:
    if not glob_pattern or glob_pattern == "**/*":
        return True
    parts = glob_pattern.replace("\\", "/").split("/")
    regex_parts: list[str] = []
    prev_double_star = False
    for part in parts:
        if part == "**":
            if regex_parts:
                regex_parts.append("/")
            regex_parts.append(r"(?:[^/]+/)*")
            prev_double_star = True
            continue
        escaped = re.escape(part).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        if regex_parts and not prev_double_star:
            regex_parts.append("/")
        regex_parts.append(escaped)
        prev_double_star = False
    return bool(re.match("^" + "".join(regex_parts) + "$", rel_path))


def _local_search(workspace: Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    pattern = str(tool_input.get("pattern", ""))
    if not pattern:
        return ToolExecutionResult(
            ToolName.SEARCH, Outcome.REJECTED, "pattern must not be empty"
        )

    flags = re.IGNORECASE if tool_input.get("ignore_case") else 0
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        return ToolExecutionResult(
            ToolName.SEARCH,
            Outcome.REJECTED,
            f"invalid regular expression: {exc}",
        )

    head_limit = int(tool_input.get("head_limit", 250))
    glob_pattern = tool_input.get("glob")
    matches: list[dict[str, Any]] = []
    content_files: list[tuple[Path, str]] = []
    binary_skipped = 0
    files_searched = 0
    truncated = False

    root = workspace.resolve()
    files = sorted(path for path in root.rglob("*") if path.is_file())

    for filepath in files:
        rel = filepath.relative_to(root).as_posix()
        if set(filepath.relative_to(root).parts) & DEFAULT_EXCLUDE_DIRS:
            continue
        if not _match_glob(rel, str(glob_pattern) if glob_pattern else None):
            continue
        content_files.append((filepath, rel))
        if compiled.search(rel):
            if len(matches) >= head_limit:
                truncated = True
                continue
            matches.append(
                {
                    "path": rel,
                    "line": None,
                    "text": "",
                    "match_type": "path",
                }
            )

    has_context = any(
        int(tool_input.get(key, 0) or 0) > 0
        for key in ("context_before", "context_after", "context_around")
    )
    ctx_before = int(tool_input.get("context_before", 0) or 0)
    ctx_after = int(tool_input.get("context_after", 0) or 0)
    ctx_around = int(tool_input.get("context_around", 0) or 0)

    for filepath, rel in content_files:
        try:
            data = filepath.read_bytes()
        except OSError:
            continue
        if _looks_binary(data):
            binary_skipped += 1
            continue
        decoded = _decode_text(data)
        if decoded is None:
            continue
        text, encoding = decoded
        files_searched += 1
        newline = _newline_style(data)
        lines = text.splitlines()
        for idx, line in enumerate(lines, 1):
            if not compiled.search(line):
                continue
            if len(matches) >= head_limit:
                truncated = True
                break
            entry: dict[str, Any] = {
                "path": rel,
                "line": idx,
                "text": line,
                "encoding": encoding,
                "newline": newline,
                "match_type": "content",
            }
            if has_context:
                before_count = max(ctx_before, ctx_around)
                after_count = max(ctx_after, ctx_around)
                entry["context_before"] = [
                    {"line": line_idx + 1, "text": lines[line_idx]}
                    for line_idx in range(max(0, idx - before_count - 1), idx - 1)
                ]
                entry["context_after"] = [
                    {"line": line_idx + 1, "text": lines[line_idx]}
                    for line_idx in range(idx, min(len(lines), idx + after_count))
                ]
            matches.append(entry)

    return ToolExecutionResult(
        ToolName.SEARCH,
        Outcome.OK,
        f"found {len(matches)} matches",
        output={
            "matches": matches[:head_limit],
            "truncated": truncated,
            "files_searched": files_searched,
            "binary_skipped": binary_skipped,
            "engine": "python",
        },
    )


def _remote_search(
    runtime: Any,
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    pattern = str(tool_input.get("pattern", ""))
    if not pattern:
        return ToolExecutionResult(
            ToolName.SEARCH, Outcome.REJECTED, "pattern must not be empty"
        )
    cmd = ["search", "--pattern", pattern]
    if glob_pattern := tool_input.get("glob"):
        cmd.extend(["--glob", str(glob_pattern)])
    if head_limit := tool_input.get("head_limit"):
        cmd.extend(["--head_limit", str(int(head_limit))])
    if tool_input.get("ignore_case"):
        cmd.append("--ignore_case")

    try:
        response = asyncio.run(
            runtime.execute(
                Command(command=cmd, cwd=workspace_path, timeout=60, check=False)
            )
        )
    except Exception as exc:
        return ToolExecutionResult(ToolName.SEARCH, Outcome.ERROR, str(exc))

    stdout = response.stdout or ""
    if response.returncode != 0:
        return ToolExecutionResult(
            ToolName.SEARCH,
            Outcome.FAILED,
            (response.stderr or stdout or f"exit {response.returncode}")[:200],
            output={"stdout": stdout, "stderr": response.stderr or "", "exit_code": response.returncode},
        )
    try:
        parsed = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        parsed = {"stdout": stdout}
    matches = parsed.get("matches", []) if isinstance(parsed, dict) else []
    return ToolExecutionResult(
        ToolName.SEARCH,
        Outcome.OK,
        f"found {len(matches)} matches",
        output=parsed if isinstance(parsed, dict) else {"stdout": stdout},
    )


def search_code(
    runtime_or_workspace: Any,
    tool_input: dict[str, Any] | None = None,
    *,
    workspace_path: str | None = None,
) -> ToolExecutionResult:
    """Search code text and repo-relative paths without changing tool input schema."""
    if tool_input is not None and workspace_path is None:
        return _local_search(Path(runtime_or_workspace), tool_input)
    if workspace_path is None or tool_input is None:
        return ToolExecutionResult(
            ToolName.SEARCH,
            Outcome.REJECTED,
            "workspace_path and tool_input are required for runtime search",
        )
    return _remote_search(
        runtime_or_workspace,
        workspace_path=workspace_path,
        tool_input=tool_input,
    )
