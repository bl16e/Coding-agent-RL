from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult


def search_code(workspace: str | Path, tool_input: dict[str, Any]) -> ToolExecutionResult:
    """Search UTF-8 text files in the workspace with a Python regular expression.

    This is intentionally a small deterministic search tool rather than a shell
    wrapper. It avoids exposing arbitrary command execution while still giving
    the agent enough repository context for the MVP.
    """

    root = Path(workspace).resolve()
    query = str(tool_input.get("query", ""))
    if not query:
        return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, "query must not be empty")
    try:
        pattern = re.compile(query)
    except re.error as exc:
        return ToolExecutionResult(ToolName.SEARCH_CODE, Outcome.REJECTED, f"invalid regular expression: {exc}")
    max_results = int(tool_input.get("max_results", 20))
    matches: list[dict[str, Any]] = []
    truncated = False
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            # Binary or non-UTF-8 files cannot be represented cleanly in JSONL
            # trajectory output, so they are skipped consistently with patch
            # snapshot behavior.
            continue
        for line_number, line in enumerate(lines, start=1):
            if pattern.search(line):
                if len(matches) >= max_results:
                    truncated = True
                    break
                matches.append({"path": path.relative_to(root).as_posix(), "line": line_number, "text": line})
        if truncated:
            break
    return ToolExecutionResult(
        ToolName.SEARCH_CODE,
        Outcome.OK,
        f"found {len(matches)} matches",
        output={"matches": matches, "truncated": truncated},
    )
