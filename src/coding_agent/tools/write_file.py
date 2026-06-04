from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from coding_agent.models import FileModification, Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.workspace import WorkspacePathError, resolve_workspace_path, to_workspace_relative


def _hash_text(content: str | None) -> str | None:
    """Hash text content for trajectory metadata without storing duplicates."""

    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def write_file(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """Write complete UTF-8 file content inside the task workspace.

    The tool does not accept patches or partial edits. Full-file writes make the
    model/tool contract simple and leave the final patch generator as the single
    component responsible for deriving diffs.
    """

    if "content" not in tool_input or not isinstance(tool_input.get("content"), str):
        return ToolExecutionResult(ToolName.WRITE_FILE, Outcome.REJECTED, "write_file requires complete file content")
    try:
        path = resolve_workspace_path(workspace, tool_input.get("path", ""))
        relative_path = to_workspace_relative(workspace, path)
    except WorkspacePathError as exc:
        return ToolExecutionResult(ToolName.WRITE_FILE, Outcome.REJECTED, str(exc))

    before = path.read_text(encoding="utf-8") if path.exists() else None
    try:
        # Parent creation is allowed because the resolved target path has
        # already been proven to stay inside the workspace.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tool_input["content"], encoding="utf-8")
    except OSError as exc:
        return ToolExecutionResult(ToolName.WRITE_FILE, Outcome.ERROR, str(exc))

    modification = FileModification(
        path=relative_path,
        write_status=Outcome.OK,
        before_hash=_hash_text(before),
        after_hash=_hash_text(tool_input["content"]),
    )
    return ToolExecutionResult(
        ToolName.WRITE_FILE,
        Outcome.OK,
        f"wrote {relative_path}",
        modifications=[modification],
    )
