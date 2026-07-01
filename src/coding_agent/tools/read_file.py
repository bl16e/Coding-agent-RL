from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.workspace import WorkspacePathError, resolve_workspace_path


def _line_bounds(tool_input: dict[str, Any]) -> tuple[int, int] | None:
    """解析可选行号范围。

    offset/limit 兼容分页式调用，line/end_line 兼容直接指定闭区间。内部统一返回
    1-based 闭区间，便于生成稳定的 output_summary。
    """
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


def _slice_lines(content: str, bounds: tuple[int, int] | None) -> tuple[str, str]:
    """根据行号范围截取文本，并返回面向轨迹的摘要。"""
    if bounds is None:
        return content, f"read {len(content)} characters"
    start, end = bounds
    selected = "".join(content.splitlines(keepends=True)[start - 1 : end])
    return selected, f"read lines {start}-{end} ({len(selected)} characters)"


def read_file(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """读取任务工作区内的 UTF-8 文本文件。

    路径校验先于文件存在性检查。像 "../secret.py" 这样的输入会被归类为策略拒绝，
    而不是普通文件不存在。
    """

    try:
        path = resolve_workspace_path(workspace, tool_input.get("path", ""))
        bounds = _line_bounds(tool_input)
    except WorkspacePathError as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, str(exc))
    except (TypeError, ValueError) as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, str(exc))
    if not path.is_file():
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.FAILED, f"file not found: {tool_input.get('path')}")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.FAILED, f"file is not UTF-8 text: {exc}")
    content, output_summary = _slice_lines(content, bounds)
    return ToolExecutionResult(
        ToolName.READ_FILE,
        Outcome.OK,
        output_summary,
        output={"content": content},
    )
