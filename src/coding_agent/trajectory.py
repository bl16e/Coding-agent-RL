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
        now = _utc_now()

        for msg in messages:
            role = msg.get("role", "")
            if role in ("system",):
                continue
            if role == "user":
                steps.append(TrajectoryStep(
                    step_index=step_idx,
                    timestamp=now,
                    action_type=StepActionType.MODEL,
                    outcome=Outcome.OK,
                ))
                step_idx += 1
            elif role == "assistant":
                content = msg.get("content")
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
                        reasoning_summary=str(content or ""),
                    ))
                step_idx += 1
            elif role == "tool":
                try:
                    data = json.loads(msg.get("content", "{}"))
                except json.JSONDecodeError:
                    data = {}
                tool_name_str = data.get("tool_name", "unknown")
                try:
                    tool_name = ToolName(tool_name_str)
                except ValueError:
                    continue
                tool_call = ToolCall(
                    tool_name=tool_name,
                    input={},
                    output_summary=data.get("output_summary", ""),
                    status=Outcome(data.get("status", "ok")),
                    started_at=now,
                    ended_at=now,
                )
                steps.append(TrajectoryStep(
                    step_index=step_idx,
                    timestamp=now,
                    action_type=StepActionType.TOOL_RESULT,
                    outcome=Outcome(data.get("status", "ok")),
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
