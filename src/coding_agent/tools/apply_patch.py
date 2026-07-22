# src/coding_agent/tools/apply_patch.py
from __future__ import annotations

import asyncio
import difflib
from typing import Any

from swerex.runtime.abstract import ReadFileRequest, WriteFileRequest

from coding_agent.models import FileModification, Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult

VALID_TYPES = ("write", "update")


def _generate_diff(path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
    )
    return "".join(diff)


def _find_similar_lines(content: str, target: str, max_hints: int = 3) -> list[str]:
    lines = content.splitlines()
    if not lines or not target.strip():
        return []
    scored = [
        (line, difflib.SequenceMatcher(None, target, line).ratio())
        for line in lines
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    hints: list[str] = []
    for line, ratio in scored:
        if ratio < 0.3:
            break
        hints.append(line[:120])
        if len(hints) >= max_hints:
            break
    return hints


def _full_path(workspace_path: str, file_path: str) -> str:
    return f"{workspace_path.rstrip('/')}/{file_path}"


def _read_content(runtime: Any, path: str) -> str:
    try:
        response = asyncio.run(runtime.read_file(ReadFileRequest(path=path)))
        return response.content
    except Exception:
        return ""


def _write_content(runtime: Any, path: str, content: str) -> None:
    asyncio.run(runtime.write_file(WriteFileRequest(path=path, content=content)))


def _apply_write(
    runtime: Any,
    workspace_path: str,
    file_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    if "content" not in tool_input or not isinstance(tool_input.get("content"), str):
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "write requires string content",
        )
    full = _full_path(workspace_path, file_path)
    try:
        _write_content(runtime, full, tool_input["content"])
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.ERROR, str(exc),
        )
    return ToolExecutionResult(
        ToolName.APPLY_PATCH, Outcome.OK,
        f"wrote {file_path}",
        output={"encoding": "utf-8", "newline": "lf"},
        modifications=[FileModification(path=file_path, write_status=Outcome.OK)],
    )


def _apply_update(
    runtime: Any,
    workspace_path: str,
    file_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    old_string = tool_input.get("old_string", "")
    new_string = tool_input.get("new_string", "")
    if not old_string:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "update requires non-empty old_string",
        )
    if not isinstance(new_string, str):
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "update requires new_string",
        )
    full = _full_path(workspace_path, file_path)
    content = _read_content(runtime, full)
    if not content:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED,
            f"file not found or empty: {file_path}",
        )

    count = content.count(old_string)
    if count == 0:
        hints = _find_similar_lines(content, old_string)
        msg = f"old_string not found in {file_path}"
        if hints:
            quoted = "\n".join(f"  > {h}" for h in hints)
            msg += f"\nMost similar lines in the file:\n{quoted}"
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED, msg,
        )
    if count > 1:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED,
            f"old_string appears {count} times in {file_path}. "
            "Include more surrounding context to make it unique.",
        )

    new_content = content.replace(old_string, new_string, 1)
    diff = _generate_diff(file_path, content, new_content)
    try:
        _write_content(runtime, full, new_content)
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.ERROR, str(exc),
        )
    return ToolExecutionResult(
        ToolName.APPLY_PATCH, Outcome.OK,
        f"applied edit to {file_path}",
        output={"patch": diff, "encoding": "utf-8", "newline": "lf"},
        modifications=[FileModification(path=file_path, write_status=Outcome.OK)],
    )


def apply_patch(
    runtime: Any,
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    """Structured file modification via SWE-ReX runtime.

    Two operations:
    - write: create or overwrite file_path with content
    - update: replace old_string with new_string via exact match
    """
    patch_type = tool_input.get("type", "")
    if patch_type not in VALID_TYPES:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            f"type must be one of {', '.join(VALID_TYPES)}, got: {patch_type}",
        )
    file_path = str(tool_input.get("file_path", ""))
    if not file_path:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "file_path must not be empty",
        )
    if patch_type == "write":
        return _apply_write(runtime, workspace_path, file_path, tool_input)
    return _apply_update(runtime, workspace_path, file_path, tool_input)
