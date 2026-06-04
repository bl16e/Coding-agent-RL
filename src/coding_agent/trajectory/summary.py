from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coding_agent.models import RunSummary


def write_summary(path: str | Path, summary: RunSummary) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")


def load_summary(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_trajectory(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def last_successful_tool_call(trajectory_steps: list[dict[str, Any]]) -> str | None:
    for step in reversed(trajectory_steps):
        tool_call = step.get("tool_call") or {}
        if step.get("action_type") == "tool_result" and tool_call.get("status") == "ok":
            return tool_call.get("tool_name")
    return None


def render_inspect_report(summary: dict[str, Any], trajectory_steps: list[dict[str, Any]]) -> str:
    changed_files = summary.get("changed_files") or []
    last_tool = last_successful_tool_call(trajectory_steps) or summary.get("last_successful_tool_call") or "none"
    error = summary.get("error") or "none"
    return "\n".join(
        [
            f"Final status: {summary.get('status', 'unknown')}",
            "Changed files: " + (", ".join(changed_files) if changed_files else "none"),
            f"Last successful tool call: {last_tool}",
            f"Error point or budget stop: {error}",
        ]
    )
