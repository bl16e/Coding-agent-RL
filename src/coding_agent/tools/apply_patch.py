from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from coding_agent.models import FileModification, Outcome, ToolName
from coding_agent.textio import BinaryFileError, TextDecodeError, read_text_file, write_text_file
from coding_agent.tools.result import ToolExecutionResult
from coding_agent.workspace import WorkspacePathError, resolve_workspace_path, to_workspace_relative


VALID_TYPES = ("write", "update")


def _generate_diff(path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
    )
    return "".join(diff)


def _find_similar_lines(content: str, target: str, *, max_hints: int = 3) -> list[str]:
    """Return lines from *content* that are most similar to *target*.

    Used to give the model actionable hints when ``old_string`` isn't found.
    """
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


def _apply_write(
    workspace: str | Path,
    path: Path,
    relative_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    """Create or overwrite a file in the workspace."""
    if "content" not in tool_input or not isinstance(tool_input.get("content"), str):
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED, "write requires string content",
        )
    existed = path.exists()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_file(path, tool_input["content"], encoding="utf-8", newline="lf")
    except OSError as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.ERROR, str(exc))
    summary = f"{'overwrote' if existed else 'created'} {relative_path}"
    return ToolExecutionResult(
        ToolName.APPLY_PATCH, Outcome.OK, summary,
        output={"encoding": "utf-8", "newline": "lf"},
        modifications=[FileModification(path=relative_path, write_status=Outcome.OK)],
    )


def _apply_update(
    workspace: str | Path,
    path: Path,
    relative_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    """Replace *old_string* with *new_string* via exact match.

    ``old_string`` must be non-empty and appear exactly once in the file.
    When the match fails, the error includes the closest-looking lines from
    the file so the model can adjust indentation or surrounding context.
    """
    old_string = tool_input.get("old_string", "")
    new_string = tool_input.get("new_string", "")
    if not old_string:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            "update requires non-empty old_string",
        )
    if not isinstance(new_string, str):
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED, "update requires new_string",
        )
    if not path.is_file():
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED, f"file not found: {relative_path}",
        )
    try:
        text_file = read_text_file(path)
    except (BinaryFileError, TextDecodeError) as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, str(exc))

    content = text_file.content
    count = content.count(old_string)
    if count == 0:
        hints = _find_similar_lines(content, old_string)
        msg = f"old_string not found in {relative_path}"
        if hints:
            quoted = "\n".join(f"  > {h}" for h in hints)
            msg += f"\nMost similar lines in the file:\n{quoted}"
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.FAILED, msg)
    if count > 1:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.FAILED,
            f"old_string appears {count} times in {relative_path}. "
            "Include more surrounding context to make it unique.",
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


def apply_patch(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """Structured file modification tool.

    Two operations:

    - ``write``: create or overwrite ``file_path`` with ``content``.
    - ``update``: replace ``old_string`` with ``new_string`` in ``file_path``
      via exact match. ``old_string`` must appear exactly once.

    All paths are validated through workspace.py so the model cannot escape the
    task workspace.
    """

    patch_type = tool_input.get("type", "")
    if patch_type not in VALID_TYPES:
        return ToolExecutionResult(
            ToolName.APPLY_PATCH, Outcome.REJECTED,
            f"type must be one of {', '.join(VALID_TYPES)}, got: {patch_type}",
        )

    if patch_type == "write":
        try:
            path = resolve_workspace_path(workspace, tool_input.get("file_path", ""))
            relative_path = to_workspace_relative(workspace, path)
        except WorkspacePathError as exc:
            return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
        return _apply_write(workspace, path, relative_path, tool_input)

    # patch_type == "update"
    try:
        path = resolve_workspace_path(workspace, tool_input.get("file_path", ""))
        relative_path = to_workspace_relative(workspace, path)
    except WorkspacePathError as exc:
        return ToolExecutionResult(ToolName.APPLY_PATCH, Outcome.REJECTED, str(exc))
    return _apply_update(workspace, path, relative_path, tool_input)
