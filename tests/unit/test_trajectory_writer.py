"""Tests for TrajectoryExporter (replaces old TrajectoryWriter)."""
import json
from datetime import datetime, timezone
from pathlib import Path

from coding_agent.models import (
    Outcome, RunBudget, StepActionType, ToolCall, ToolName, TrajectoryStep,
)
from coding_agent.trajectory_exporter import TrajectoryExporter


def _make_step(index: int, action_type: StepActionType, **kw) -> TrajectoryStep:
    return TrajectoryStep(
        step_index=index,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        action_type=action_type,
        outcome=Outcome.OK,
        **kw,
    )


def test_exporter_produces_trajectory_jsonl(tmp_path: Path):
    output_dir = tmp_path / "run"
    exporter = TrajectoryExporter(output_dir)

    messages = [
        {"role": "system", "content": "You are a coder."},
        {"role": "user", "content": "Fix the bug."},
        {
            "role": "assistant",
            "content": "Let me read the file.",
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "extra": {
                "tool_result": {
                    "tool_name": "read_file",
                    "tool_input": {"file_path": "app.py"},
                    "status": "ok",
                    "output_summary": "read 100 chars",
                    "output": {"content": "1  print('hello')", "encoding": "utf-8"},
                },
            },
        },
        {
            "role": "assistant",
            "content": "",
            "extra": {"exit_status": "Submitted", "submission": "fixed bug"},
        },
    ]

    artifacts = exporter.export(
        messages=messages,
        run_id="test-run",
        instance_id="test-1",
        model_name="test-model",
        budget=RunBudget(max_steps=5, timeout_seconds=60, test_timeout_seconds=30),
        final_patch="diff --git ...",
    )

    traj_path = artifacts["trajectory_jsonl"]
    assert traj_path.exists()
    steps = [json.loads(line) for line in traj_path.read_text().splitlines() if line.strip()]
    assert len(steps) >= 3  # user(→MODEL), assistant(→MODEL), tool(→TOOL_RESULT), exit(→FINAL)
    action_types = [s["action_type"] for s in steps]
    assert "tool_result" in action_types
    assert "final" in action_types


def test_exporter_includes_observation_field(tmp_path: Path):
    output_dir = tmp_path / "run2"
    exporter = TrajectoryExporter(output_dir)

    messages = [
        {"role": "system", "content": "."},
        {"role": "user", "content": "Fix."},
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "extra": {
                "tool_result": {
                    "tool_name": "read_file",
                    "tool_input": {"file_path": "x.py"},
                    "status": "ok",
                    "output": {"content": "1  hello"},
                },
            },
        },
    ]

    artifacts = exporter.export(
        messages=messages,
        run_id="test-obs",
        instance_id="test-obs",
        model_name="m",
        budget=RunBudget(5, 60, 30),
        final_patch="",
    )

    steps = [json.loads(line) for line in artifacts["trajectory_jsonl"].read_text().splitlines() if line.strip()]
    tool_steps = [s for s in steps if s["action_type"] == "tool_result"]
    assert len(tool_steps) == 1
    assert "observation" in tool_steps[0]
    assert "hello" in tool_steps[0]["observation"]
