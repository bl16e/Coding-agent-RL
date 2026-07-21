from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_agent.models import Outcome, ToolName
from coding_agent.textio import BinaryFileError, TextDecodeError, page_text, read_text_file
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.workspace import WorkspacePathError, resolve_workspace_path


def _parse_bounds(tool_input: dict[str, Any]) -> tuple[int, int] | None:
    """Parse optional line range from offset/limit.

    Returns (start, end) as a 1-based inclusive interval, or None to read the
    default page.  offset is the 1-based start line; limit is the number of
    lines to read.
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


def read_file(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """Read a UTF-8 text file from the workspace with cat -n style line numbers.

    Path validation runs before existence checks so path-traversal attempts are
    rejected as policy violations rather than opaque "not found" errors.
    """

    try:
        path = resolve_workspace_path(workspace, tool_input.get("file_path", ""))
        bounds = _parse_bounds(tool_input)
    except WorkspacePathError as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, str(exc))
    except (TypeError, ValueError) as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, str(exc))

    if path.is_dir():
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.FAILED,
            f"path is a directory, not a file: {tool_input.get('file_path')}",
        )
    if not path.is_file():
        return ToolExecutionResult(
            ToolName.READ_FILE, Outcome.FAILED,
            f"file not found: {tool_input.get('file_path')}",
        )

    try:
        text_file = read_text_file(path)
    except (BinaryFileError, TextDecodeError) as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.FAILED, str(exc))

    page = page_text(text_file, bounds)
    if page.line_start and (bounds is not None or page.truncated):
        output_summary = f"read lines {page.line_start}-{page.line_end} ({len(page.content)} characters)"
    else:
        output_summary = f"read {len(page.content)} characters"
    return ToolExecutionResult(
        ToolName.READ_FILE,
        Outcome.OK,
        output_summary,
        output=page.to_output(),
    )
