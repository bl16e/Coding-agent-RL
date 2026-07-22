# src/coding_agent/tools/read_file.py
from __future__ import annotations

import asyncio
from typing import Any

from swerex.runtime.abstract import ReadFileRequest

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult

DEFAULT_PAGE_LINES = 200
MAX_CHARS = 50000


def _parse_bounds(tool_input: dict[str, Any]) -> tuple[int, int] | None:
    has_offset = "offset" in tool_input
    has_limit = "limit" in tool_input
    if not has_offset and not has_limit:
        return None
    start = int(tool_input.get("offset", 1))
    limit = int(tool_input.get("limit", DEFAULT_PAGE_LINES))
    if start < 1:
        raise ValueError("offset must be >= 1")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return start, start + limit - 1


def _format_with_line_numbers(content: str, start_line: int) -> str:
    if not content:
        return ""
    lines = content.splitlines(keepends=True)
    end_line = start_line + len(lines) - 1
    width = max(4, len(str(end_line)))
    formatted: list[str] = []
    for i, line in enumerate(lines):
        num = start_line + i
        if line.endswith("\n"):
            formatted.append(f"{num:>{width}}\t{line[:-1]}\n")
        elif line.endswith("\r\n"):
            formatted.append(f"{num:>{width}}\t{line[:-2]}\r\n")
        else:
            formatted.append(f"{num:>{width}}\t{line}")
    return "".join(formatted)


def read_file(
    runtime: Any,
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    """Read a UTF-8 text file from the container via SWE-ReX runtime."""
    file_path = str(tool_input.get("file_path", ""))
    if not file_path:
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.REJECTED,
            "file_path must not be empty",
        )

    try:
        bounds = _parse_bounds(tool_input)
    except (TypeError, ValueError) as exc:
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.REJECTED, str(exc),
        )

    full_path = f"{workspace_path.rstrip('/')}/{file_path}"

    try:
        response = asyncio.run(
            runtime.read_file(ReadFileRequest(path=full_path))
        )
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.FAILED,
            f"failed to read file: {exc}",
        )

    content = response.content
    if not content:
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.FAILED,
            f"file not found or empty: {file_path}",
        )

    lines = content.splitlines()
    total_lines = len(lines)

    if bounds is None:
        start = 1
        end = min(DEFAULT_PAGE_LINES, max(total_lines, 1))
    else:
        start, end = bounds

    actual_end = min(end, total_lines)
    selected_lines = lines[start - 1 : actual_end]
    selected = "\n".join(selected_lines)
    truncated = start > 1 or actual_end < total_lines

    if len(selected) > MAX_CHARS:
        selected = selected[:MAX_CHARS]
        truncated = True

    formatted = _format_with_line_numbers(selected, start) if selected else ""

    if truncated and total_lines > actual_end:
        remaining = total_lines - actual_end
        formatted = formatted.rstrip("\n\r") + (
            f"\n... [truncated, {remaining} lines remaining]\n"
        )

    if bounds is not None or truncated:
        output_summary = (
            f"read lines {start}-{actual_end} "
            f"({len(selected)} characters)"
        )
    else:
        output_summary = f"read {len(selected)} characters"

    return ToolExecutionResult(
        ToolName.READ_FILE,
        Outcome.OK,
        output_summary,
        output={
            "content": formatted,
            "encoding": "utf-8",
            "line_start": start if total_lines else 0,
            "line_end": actual_end,
            "total_lines": total_lines,
            "truncated": truncated,
        },
    )
