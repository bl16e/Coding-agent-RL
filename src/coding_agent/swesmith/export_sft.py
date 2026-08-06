from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from coding_agent.swesmith.evaluate import read_resolved_ids


SYSTEM_PROMPT = "You are a coding agent that solves repository issues using the provided tools."


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_issue(trajectory_jsonl_path: Path) -> str:
    trajectory_json_path = trajectory_jsonl_path.with_suffix(".json")
    if not trajectory_json_path.is_file():
        return ""
    try:
        payload = json.loads(trajectory_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    issue = payload.get("issue") if isinstance(payload, dict) else ""
    return str(issue or "").strip()


def _tool_xml(tool_name: str, arguments: dict[str, Any]) -> str:
    lines = [f"<function={tool_name}>"]
    for key, value in arguments.items():
        if key in {"old_string", "new_string", "content"}:
            lines.append(f"<parameter={key}>\n{value}\n</parameter>")
        else:
            lines.append(f"<parameter={key}>{value}</parameter>")
    lines.append("</function>")
    return "\n".join(lines)


def _messages_from_trajectory(path: Path) -> list[dict[str, str]]:
    events = _load_jsonl(path)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    issue = _load_issue(path)
    if issue:
        messages.append({"role": "user", "content": issue})
    pending_reasoning = ""
    for event in events:
        if event.get("action_type") == "model":
            pending_reasoning = str(event.get("reasoning_summary") or "")
            continue
        if event.get("action_type") != "tool_result":
            continue
        tool_call = event.get("tool_call") or {}
        tool_name = str(tool_call.get("tool_name") or "")
        arguments = tool_call.get("input") if isinstance(tool_call.get("input"), dict) else {}
        content = pending_reasoning.strip()
        xml = _tool_xml(tool_name, arguments)
        messages.append({"role": "assistant", "content": (content + "\n\n" + xml).strip()})
        observation = event.get("tool_result") or {}
        messages.append({"role": "user", "content": "OBSERVATION:\n" + json.dumps(observation, ensure_ascii=False, default=str)})
        pending_reasoning = ""
    return messages


def _traj_id(instance_id: str, runs_dir: Path) -> str:
    digest = hashlib.sha1(f"{runs_dir.resolve()}::{instance_id}".encode("utf-8")).hexdigest()[:12]
    return f"{instance_id}.{digest}"


def export_sft(*, runs_dir: str | Path, eval_dir: str | Path, output: str | Path, style: str = "xml") -> int:
    if style != "xml":
        raise ValueError("only xml style is supported in the first version")
    runs_root = Path(runs_dir)
    resolved_ids = read_resolved_ids(eval_dir)
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        summary_path = run_dir / "summary.json"
        trajectory_path = run_dir / "trajectory.jsonl"
        patch_path = run_dir / "final.patch"
        if not summary_path.is_file() or not trajectory_path.is_file():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        instance_id = str(summary.get("instance_id") or run_dir.name)
        if instance_id not in resolved_ids:
            continue
        rows.append(
            {
                "instance_id": instance_id,
                "resolved": True,
                "model": str(summary.get("model_name", "")),
                "traj_id": _traj_id(instance_id, runs_root),
                "patch": patch_path.read_text(encoding="utf-8") if patch_path.is_file() else "",
                "messages": _messages_from_trajectory(trajectory_path),
            }
        )
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return len(rows)
