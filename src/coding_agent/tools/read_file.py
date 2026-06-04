from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.workspace import WorkspacePathError, resolve_workspace_path


def read_file(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """Read a UTF-8 text file from inside the task workspace.

    Path validation happens before existence checks so attempts such as
    "../secret.py" are rejected as policy violations rather than reported as
    ordinary missing files.
    """

    try:
        path = resolve_workspace_path(workspace, tool_input.get("path", ""))
    except WorkspacePathError as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.REJECTED, str(exc))
    if not path.is_file():
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.FAILED, f"file not found: {tool_input.get('path')}")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return ToolExecutionResult(ToolName.READ_FILE, Outcome.FAILED, f"file is not UTF-8 text: {exc}")
    return ToolExecutionResult(
        ToolName.READ_FILE,
        Outcome.OK,
        f"read {len(content)} characters",
        output={"content": content},
    )
