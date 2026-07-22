# src/coding_agent/tools/search_code.py
from __future__ import annotations

import asyncio
import re
from typing import Any

from swerex.runtime.abstract import Command

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.result import ToolExecutionResult

DEFAULT_EXCLUDE_DIRS = (
    ".git,.venv,venv,node_modules,build,dist,.tox,__pycache__,.pytest_cache"
)


def _build_grep_cmd(tool_input: dict[str, Any]) -> list[str]:
    pattern = str(tool_input.get("pattern", ""))
    cmd = ["grep", "-rn", "--color=never"]
    cmd.extend(["--exclude-dir={" + DEFAULT_EXCLUDE_DIRS + "}"])
    if tool_input.get("ignore_case"):
        cmd.append("-i")
    head_limit = int(tool_input.get("head_limit", 250))
    cmd.extend(["-m", str(head_limit)])
    glob_pattern = tool_input.get("glob")
    if glob_pattern and glob_pattern != "**/*":
        cmd.extend(["--include", glob_pattern.replace("**/", "").lstrip("/")])
    cmd.append(pattern)
    cmd.append(".")
    return cmd


def search_code(
    runtime: Any,
    *,
    workspace_path: str,
    tool_input: dict[str, Any],
) -> ToolExecutionResult:
    """Search repository files via grep in the container."""
    pattern_str = str(tool_input.get("pattern", ""))
    if not pattern_str:
        return ToolExecutionResult(
            ToolName.SEARCH_CODE, Outcome.REJECTED,
            "pattern must not be empty",
        )

    # Validate regex locally before sending to container
    flags = re.IGNORECASE if tool_input.get("ignore_case") else 0
    try:
        re.compile(pattern_str, flags)
    except re.error as exc:
        return ToolExecutionResult(
            ToolName.SEARCH_CODE, Outcome.REJECTED,
            f"invalid regular expression: {exc}",
        )

    cmd = _build_grep_cmd(tool_input)
    try:
        response = asyncio.run(runtime.execute(Command(
            command=cmd,
            cwd=workspace_path,
            timeout=30,
            check=False,
        )))
    except Exception as exc:
        return ToolExecutionResult(
            ToolName.SEARCH_CODE, Outcome.ERROR, str(exc),
        )

    output = response.stdout or ""
    matches: list[dict[str, Any]] = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        # grep -n output format: path:lineno:content
        parts = line.split(":", 2)
        if len(parts) >= 3:
            matches.append({
                "path": parts[0],
                "line": int(parts[1]),
                "text": parts[2],
            })

    head_limit = int(tool_input.get("head_limit", 250))
    truncated = len(matches) >= head_limit
    return ToolExecutionResult(
        ToolName.SEARCH_CODE,
        Outcome.OK,
        f"found {len(matches)} matches",
        output={
            "matches": matches[:head_limit],
            "truncated": truncated,
            "files_searched": len(set(m["path"] for m in matches)),
        },
    )
