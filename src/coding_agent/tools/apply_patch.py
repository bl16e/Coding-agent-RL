from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from coding_agent.models import FileModification, Outcome, ToolName
from coding_agent.textio import BinaryFileError, TextDecodeError, read_text_file, write_text_file
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.workspace import WorkspacePathError, resolve_workspace_path, to_workspace_relative


PATCH_TYPES = ("add_file", "update", "move")


def _generate_diff(path: str, old_text: str, new_text: str) -> str:
    """为单文件更新生成 unified diff，写入工具输出供轨迹审计。"""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
    )
    return "".join(diff)


def _apply_add_file(workspace: str | Path, path: Path, relative_path: str, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """创建新文件，拒绝覆盖已有路径。"""
    if "content" not in tool_input or not isinstance(tool_input.get("content"), str):
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "add_file requires string content")
    if path.exists():
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, f"file already exists: {relative_path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_file(path, tool_input["content"], encoding="utf-8", newline="lf")
    except OSError as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.ERROR, str(exc))
    return ToolExecutionResult(
        ToolName.APPLY_PATCH, Outcome.OK, f"created {relative_path}",
        output={"encoding": "utf-8", "newline": "lf"},
        modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
    )


def _apply_update(workspace: str | Path, path: Path, relative_path: str, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """用精确字符串替换更新文件。

    old_string 必须非空且只出现一次。这个约束牺牲一点便利性，但能显著降低模型把
    相似代码块误改掉的风险。
    """
    old_string = tool_input.get("old_string", "")
    new_string = tool_input.get("new_string", "")
    if not old_string:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "update requires non-empty old_string")
    if not isinstance(new_string, str):
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "update requires new_string")
    if not path.is_file():
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, f"file not found: {relative_path}")
    try:
        text_file = read_text_file(path)
    except (BinaryFileError, TextDecodeError) as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, str(exc))
    content = text_file.content
    count = content.count(old_string)
    if count == 0:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, f"old_string not found in {relative_path}")
    if count > 1:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED,
            f"old_string appears {count} times in {relative_path}. Include more surrounding context.",
        )
    new_content = content.replace(old_string, new_string, 1)
    diff = _generate_diff(relative_path, content, new_content)
    try:
        write_text_file(path, new_content, encoding=text_file.encoding, newline=text_file.newline)
    except OSError as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.ERROR, str(exc))
    return ToolExecutionResult(
        ToolName.APPLY_PATCH, Outcome.OK, f"applied edit to {relative_path}",
        output={"patch": diff, "encoding": text_file.encoding, "newline": text_file.newline},
        modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
    )


def _apply_move(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """移动工作区内文件，拒绝覆盖目标路径。"""
    old_path_str = tool_input.get("old_path", "")
    new_path_str = tool_input.get("new_path", "")
    if not old_path_str or not new_path_str:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, "move requires old_path and new_path")
    try:
        old_path = resolve_workspace_path(workspace, old_path_str)
        old_relative = to_workspace_relative(workspace, old_path)
        new_path = resolve_workspace_path(workspace, new_path_str)
        new_relative = to_workspace_relative(workspace, new_path)
    except WorkspacePathError as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
    if not old_path.exists():
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, f"source not found: {old_relative}")
    if new_path.exists():
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, f"destination exists: {new_relative}")
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)
    except OSError as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.ERROR, str(exc))
    return ToolExecutionResult(
        ToolName.APPLY_PATCH, Outcome.OK, f"moved {old_relative} -> {new_relative}",
        modifications=[
            FileModification(path=old_relative, write_status=Outcome.OK),
            FileModification(path=new_relative, write_status=Outcome.OK),
        ],
    )


def apply_patch(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """统一的结构化文件修改工具。

    根据 ``type`` 参数分发：

    - ``add_file``：在 ``path`` 创建新文件。
    - ``update``：把已有文件中的精确 ``old_string`` 替换为 ``new_string``。
    - ``move``：把 ``old_path`` 重命名为 ``new_path``。

    路径解析统一走 workspace.py，确保模型无法通过相对路径逃出任务工作区。
    """

    patch_type = tool_input.get("type", "")
    if patch_type not in PATCH_TYPES:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            f"patch type must be one of {', '.join(PATCH_TYPES)}, got: {patch_type}",
        )

    if patch_type == "add_file":
        try:
            path = resolve_workspace_path(workspace, tool_input.get("path", ""))
            relative_path = to_workspace_relative(workspace, path)
        except WorkspacePathError as exc:
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
        return _apply_add_file(workspace, path, relative_path, tool_input)

    if patch_type == "update":
        try:
            path = resolve_workspace_path(workspace, tool_input.get("path", ""))
            relative_path = to_workspace_relative(workspace, path)
        except WorkspacePathError as exc:
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
        return _apply_update(workspace, path, relative_path, tool_input)

    # 剩下的合法类型只能是 move。
    return _apply_move(workspace, tool_input)
