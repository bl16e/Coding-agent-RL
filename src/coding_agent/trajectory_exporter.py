# src/coding_agent/trajectory.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coding_agent.models import (
    Outcome,
    Prediction,
    RunBudget,
    RunStatus,
    RunSummary,
    StepActionType,
    ToolCall,
    ToolName,
    TrajectoryStep,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _assistant_reasoning_summary(message: dict[str, Any]) -> str:
    content = message.get("content")
    if content:
        return str(content)

    for key in ("reasoning_content", "reasoning_summary"):
        value = message.get(key)
        if value:
            return str(value)

    extra = message.get("extra")
    if isinstance(extra, dict):
        for key in ("reasoning_content", "reasoning_summary"):
            value = extra.get(key)
            if value:
                return str(value)

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            arguments = function.get("arguments")
            if not arguments:
                continue
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            for key in ("reasoning_summary", "next_intent", "tool_selection_reason"):
                value = parsed.get(key)
                if value:
                    return str(value)
            name = function.get("name")
            if name:
                return _tool_call_fallback_summary(str(name), parsed)

    return ""


def _tool_call_fallback_summary(name: str, arguments: dict[str, Any]) -> str:
    visible_args = [
        f"{key}={_compact_argument(value)}"
        for key, value in arguments.items()
        if key not in {"old_string", "new_string", "command"}
    ]
    if not visible_args:
        return f"Call {name}."
    return f"Call {name} with {', '.join(visible_args[:3])}."


def _compact_argument(value: Any) -> str:
    text = str(value)
    if len(text) <= 120:
        return text
    return text[:117] + "..."


class TrajectoryExporter:
    """Derive all run artifacts from agent.messages at run end.

    Messages is the single source of truth — no parallel writer streams.
    """

    def __init__(self, output_dir: Path):
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        *,
        messages: list[dict[str, Any]],
        run_id: str,
        instance_id: str,
        model_name: str,
        budget: RunBudget,
        final_patch: str,
        error: str | None = None,
        changed_files: list[str] | None = None,
        test_summary: dict[str, int] | None = None,
    ) -> dict[str, Path]:
        changed_files = changed_files or []
        test_summary = test_summary or {}

        # --- trajectory.jsonl ---
        steps = self._messages_to_steps(messages)
        traj_jsonl_path = self._output_dir / "trajectory.jsonl"
        with open(traj_jsonl_path, "w", encoding="utf-8") as f:
            for step in steps:
                f.write(json.dumps(step.to_dict(), ensure_ascii=False) + "\n")

        # --- trajectory.json (summary format) ---
        traj_json_path = self._output_dir / "trajectory.json"
        traj_data = {
            "task_id": instance_id,
            "issue": self._find_user_message(messages),
            "final_diff": final_patch,
            "resolved": error is None,
            "trajectory": [s.to_dict() for s in steps],
        }
        with open(traj_json_path, "w", encoding="utf-8") as f:
            json.dump(traj_data, f, ensure_ascii=False, indent=2)

        # --- final.patch ---
        patch_path = self._output_dir / "final.patch"
        patch_path.write_text(final_patch, encoding="utf-8")

        # --- summary.json ---
        status = RunStatus.SOLVED if error is None else RunStatus.INCOMPLETE
        summary = RunSummary(
            run_id=run_id,
            instance_id=instance_id,
            model_name=model_name,
            status=status,
            budget=budget,
            changed_files=changed_files,
            test_summary=test_summary,
            error=error,
            artifacts={
                "trajectory": str(traj_jsonl_path),
                "trajectory_json": str(traj_json_path),
                "final_patch": str(patch_path),
            },
        )
        summary_path = self._output_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, ensure_ascii=False, indent=2)

        # --- prediction.jsonl ---
        pred = Prediction(instance_id, model_name, final_patch)
        pred_path = self._output_dir / "prediction.jsonl"
        with open(pred_path, "w", encoding="utf-8") as f:
            json.dump(pred.to_dict(), f, ensure_ascii=False)
            f.write("\n")

        return {
            "trajectory_jsonl": traj_jsonl_path,
            "trajectory_json": traj_json_path,
            "final_patch": patch_path,
            "summary_json": summary_path,
            "prediction_jsonl": pred_path,
        }

    def _messages_to_steps(self, messages: list[dict]) -> list[TrajectoryStep]:
        steps: list[TrajectoryStep] = []
        step_idx = 0

        for msg in messages:
            role = msg.get("role", "")
            if role in ("system",):
                continue
            now = _utc_now()
            if role == "user":
                continue
            elif role == "assistant":
                extra = msg.get("extra", {})
                if extra.get("exit_status"):
                    steps.append(TrajectoryStep(
                        step_index=step_idx,
                        timestamp=now,
                        action_type=StepActionType.FINAL,
                        outcome=Outcome.OK,
                        reasoning_summary=str(extra.get("submission", "")),
                    ))
                else:
                    steps.append(TrajectoryStep(
                        step_index=step_idx,
                        timestamp=now,
                        action_type=StepActionType.MODEL,
                        outcome=Outcome.OK,
                        reasoning_summary=_assistant_reasoning_summary(msg),
                    ))
                step_idx += 1
            elif role == "tool":
                extra = msg.get("extra") or {}
                data = extra.get("tool_result")
                if not isinstance(data, dict):
                    try:
                        data = json.loads(msg.get("content", "{}"))
                    except json.JSONDecodeError:
                        data = {}
                tool_name_str = data.get("tool_name", "unknown")
                try:
                    tool_name = ToolName(tool_name_str)
                except ValueError:
                    continue
                tool_input = data.get("tool_input", {})
                if not isinstance(tool_input, dict):
                    tool_input = {}
                tool_call = ToolCall(
                    tool_name=tool_name,
                    input=tool_input,
                    output_summary=data.get("output_summary", ""),
                    status=Outcome(data.get("status", "ok")),
                    started_at=now,
                    ended_at=now,
                )
                # Build observation from the formatted tool result content
                from coding_agent.agent import _format_tool_result_content
                observation = _format_tool_result_content(data)
                steps.append(TrajectoryStep(
                    step_index=step_idx,
                    timestamp=now,
                    action_type=StepActionType.TOOL_RESULT,
                    outcome=Outcome(data.get("status", "ok")),
                    observation=observation,
                    tool_call=tool_call,
                    tool_result=data,
                ))
                step_idx += 1
        return steps

    def _find_user_message(self, messages: list[dict]) -> str:
        for msg in messages:
            if msg.get("role") == "user":
                return str(msg.get("content", ""))
        return ""

# === Trajectory compatibility helpers ===

def write_summary(path, summary):
    """Write RunSummary to JSON file."""
    import json as _json
    from pathlib import Path as _Path
    destination = _Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_json.dumps(summary.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")


def load_summary(path):
    """Load summary.json as dict."""
    import json as _json
    from pathlib import Path as _Path
    return _json.loads(_Path(path).read_text(encoding="utf-8"))


def load_trajectory(path):
    """Load trajectory.jsonl as list of dicts."""
    import json as _json
    from pathlib import Path as _Path
    return [_json.loads(line) for line in _Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def render_inspect_report(summary, trajectory_steps):
    """Render human-readable inspect report."""
    changed_files = summary.get("changed_files") or []
    last_tool = None
    for step in reversed(trajectory_steps):
        tool_call = step.get("tool_call") or {}
        if step.get("action_type") == "tool_result" and tool_call.get("status") == "ok":
            last_tool = tool_call.get("tool_name")
            break
    last_tool = last_tool or summary.get("last_successful_tool_call") or "none"
    error = summary.get("error") or "none"
    return "\n".join([
        f"Final status: {summary.get('status', 'unknown')}",
        "Changed files: " + (", ".join(changed_files) if changed_files else "none"),
        f"Last successful tool call: {last_tool}",
        f"Error point or budget stop: {error}",
    ])


def convert_trajectory_to_summary_format(*, trajectory_jsonl, task_id, issue, final_diff, resolved, output_path):
    """Convert detailed JSONL trajectory to simplified summary format."""
    import json as _json
    from pathlib import Path as _Path

    with open(trajectory_jsonl, "r", encoding="utf-8") as f:
        raw_steps = [_json.loads(line) for line in f if line.strip()]

    steps = []
    i = 0
    step_counter = 0

    while i < len(raw_steps):
        current = raw_steps[i]
        if current.get("action_type") != "model":
            i += 1
            continue

        thought = current.get("reasoning_summary", "")

        if i + 1 < len(raw_steps) and raw_steps[i + 1].get("action_type") == "tool_result":
            tool_result = raw_steps[i + 1]
            tool_call = tool_result.get("tool_call", {})
            tool_name = tool_call.get("tool_name", "")
            tool_input = tool_call.get("input", {})
            tool_status = str(tool_call.get("status") or tool_result.get("outcome") or "")
            output_summary = str(tool_call.get("output_summary") or "")

            args = {k: v for k, v in tool_input.items() if k not in ("reasoning_summary", "next_intent", "tool_selection_reason")}
            result = tool_result.get("tool_result", {})
            observation = _fmt_obs(tool_name, result, tool_status=tool_status, output_summary=output_summary)

            steps.append({"step": step_counter, "thought": thought, "action": {"tool": tool_name, "args": args}, "observation": observation})
            step_counter += 1
            i += 2
        else:
            i += 1

    reward = 1.0 if resolved else 0.0
    summary = {"task_id": task_id, "issue": issue, "steps": steps, "final_diff": final_diff, "resolved": resolved, "reward": reward}

    with open(output_path, "w", encoding="utf-8") as f:
        _json.dump(summary, f, indent=2, ensure_ascii=False)


def _fmt_obs(tool_name, result, *, tool_status="", output_summary=""):
    """Format observation from tool result for summary trajectory."""
    output = result.get("output", {}) if isinstance(result, dict) else {}
    if not isinstance(output, dict):
        output = {}

    if tool_name == "read_file":
        # Content may be in "content" (local executor) or "stdout" (Docker CLI)
        return {"content": output.get("content") or output.get("stdout") or output_summary}
    elif tool_name == "apply_patch":
        stdout = output.get("stdout", "")
        return {"output": stdout or output_summary}
    elif tool_name in ("search", "search_code"):
        matches = output.get("matches", [])
        if not matches:
            return {"matches": 0, "hint": "0 matches — try a broader pattern or remove glob filter"}
        return {
            "matches": len(matches),
            "results": matches[:10],
            "truncated": output.get("truncated", False),
        }
    elif tool_name == "execute_bash":
        return {
            "stdout": output.get("stdout", ""),
            "stderr": output.get("stderr", ""),
            "exit_code": output.get("exit_code"),
        }
    elif tool_name == "finish":
        return {"submission": output.get("submission", output_summary)}
    return {"raw": result}
