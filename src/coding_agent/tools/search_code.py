from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from coding_agent.models import Outcome, ToolName
from coding_agent.textio import BinaryFileError, TextDecodeError, read_text_file
from coding_agent.tools.result import ToolExecutionResult


# Directories excluded by default from search.
DEFAULT_EXCLUDE_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "build", "dist", ".tox", "__pycache__", ".pytest_cache"})


def _match_glob(path: Path, root: Path, glob_pattern: str | None) -> bool:
    """Check whether *path* (relative to *root*) matches *glob_pattern*.

    When *glob_pattern* is None or ``"**/*"`` all files are included.
    Supports ``**`` for recursive directory matching.
    """
    if glob_pattern is None or glob_pattern == "**/*":
        return True
    relative = path.relative_to(root).as_posix()
    # Convert glob to regex: ** matches zero or more path segments
    parts = glob_pattern.split("/")
    regex_parts: list[str] = []
    prev_was_doublestar = False
    for part in parts:
        if part == "**":
            if regex_parts:
                regex_parts.append("/")
            # Match zero or more path segments (each ending with /)
            regex_parts.append(r"(?:[^/]+/)*")
            prev_was_doublestar = True
        else:
            escaped = re.escape(part)
            escaped = escaped.replace(r"\*", "[^/]*")
            escaped = escaped.replace(r"\?", "[^/]")
            if regex_parts and not prev_was_doublestar:
                regex_parts.append("/")
            regex_parts.append(escaped)
            prev_was_doublestar = False
    regex = "^" + "".join(regex_parts) + "$"
    return bool(re.match(regex, relative))


def _resolve_context(
    lines: list[str],
    match_line: int,
    context_before: int,
    context_after: int,
    context_around: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (before, after) context line entries for a match at *match_line*.

    Each entry is ``{"line": N, "text": "..."}``.
    """
    before_count = max(context_before, context_around)
    after_count = max(context_after, context_around)

    before: list[dict[str, Any]] = []
    for i in range(max(0, match_line - before_count - 1), match_line - 1):
        before.append({"line": i + 1, "text": lines[i]})

    after: list[dict[str, Any]] = []
    for i in range(match_line, min(len(lines), match_line + after_count)):
        after.append({"line": i + 1, "text": lines[i]})

    return before, after


def search_code(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """Search UTF-8 text files in the workspace with a regular expression.

    Supports glob-based file filtering, case-insensitive matching, and
    context lines around each match.
    """

    root = Path(workspace).resolve()
    pattern_str = str(tool_input.get("pattern", ""))
    if not pattern_str:
        return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, "pattern must not be empty")

    flags = re.IGNORECASE if tool_input.get("ignore_case") else 0
    try:
        compiled = re.compile(pattern_str, flags)
    except re.error as exc:
        return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, f"invalid regular expression: {exc}")

    head_limit = int(tool_input.get("head_limit", 250))
    glob_pattern: str | None = tool_input.get("glob")
    context_before = max(0, int(tool_input.get("context_before", 0)))
    context_after = max(0, int(tool_input.get("context_after", 0)))
    context_around = max(0, int(tool_input.get("context_around", 0)))
    has_context = context_before > 0 or context_after > 0 or context_around > 0

    matches: list[dict[str, Any]] = []
    truncated = False
    binary_skipped = 0
    files_searched = 0

    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        # Skip excluded directories
        parts = set(path.relative_to(root).parts)
        if parts & DEFAULT_EXCLUDE_DIRS:
            continue
        if not _match_glob(path, root, glob_pattern):
            continue

        files_searched += 1
        try:
            text_file = read_text_file(path)
            lines = text_file.content.splitlines()
        except BinaryFileError:
            binary_skipped += 1
            continue
        except TextDecodeError:
            continue

        for line_index, line in enumerate(lines):
            if not compiled.search(line):
                continue
            if len(matches) >= head_limit:
                truncated = True
                break

            entry: dict[str, Any] = {
                "path": path.relative_to(root).as_posix(),
                "line": line_index + 1,
                "text": line,
                "encoding": text_file.encoding,
                "newline": text_file.newline,
            }
            if has_context:
                before, after = _resolve_context(
                    lines, line_index + 1, context_before, context_after, context_around,
                )
                entry["context_before"] = before
                entry["context_after"] = after
            matches.append(entry)

        if truncated:
            break

    return ToolExecutionResult(
        ToolName.SEARCH_CODE,
        Outcome.OK,
        f"found {len(matches)} matches in {files_searched} files",
        output={
            "matches": matches,
            "truncated": truncated,
            "binary_skipped": binary_skipped,
            "files_searched": files_searched,
        },
    )
