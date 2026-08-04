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


def test_exporter_does_not_record_user_prompt_as_model_step(tmp_path: Path):
    exporter = TrajectoryExporter(tmp_path / "run3")

    artifacts = exporter.export(
        messages=[
            {"role": "system", "content": "You are a coder."},
            {"role": "user", "content": "Fix the bug."},
            {"role": "assistant", "content": "I will inspect the code."},
        ],
        run_id="test-no-user-step",
        instance_id="test-no-user-step",
        model_name="m",
        budget=RunBudget(5, 60, 30),
        final_patch="",
    )

    steps = [json.loads(line) for line in artifacts["trajectory_jsonl"].read_text().splitlines() if line.strip()]

    assert len(steps) == 1
    assert steps[0]["action_type"] == "model"
    assert steps[0]["reasoning_summary"] == "I will inspect the code."


def test_exporter_uses_provider_reasoning_content_when_tool_call_content_is_empty(tmp_path: Path):
    exporter = TrajectoryExporter(tmp_path / "run4")

    artifacts = exporter.export(
        messages=[
            {"role": "system", "content": "You are a coder."},
            {"role": "user", "content": "Fix the bug."},
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "I need to inspect the failing code before editing.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"file_path": "/testbed/app.py"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "extra": {
                    "tool_result": {
                        "tool_name": "read_file",
                        "tool_input": {"file_path": "/testbed/app.py"},
                        "status": "ok",
                        "output": {"content": "1  print('hello')"},
                    },
                },
            },
        ],
        run_id="test-provider-reasoning",
        instance_id="test-provider-reasoning",
        model_name="m",
        budget=RunBudget(5, 60, 30),
        final_patch="",
    )

    steps = [json.loads(line) for line in artifacts["trajectory_jsonl"].read_text().splitlines() if line.strip()]

    assert steps[0]["action_type"] == "model"
    assert steps[0]["reasoning_summary"] == "I need to inspect the failing code before editing."


def test_exporter_uses_tool_call_intent_fields_when_content_is_empty(tmp_path: Path):
    exporter = TrajectoryExporter(tmp_path / "run5")

    artifacts = exporter.export(
        messages=[
            {"role": "system", "content": "You are a coder."},
            {"role": "user", "content": "Fix the bug."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "search_code",
                            "arguments": json.dumps(
                                {
                                    "pattern": "broken_func",
                                    "reasoning_summary": "Search for the broken function first.",
                                }
                            ),
                        },
                    }
                ],
            },
        ],
        run_id="test-tool-intent",
        instance_id="test-tool-intent",
        model_name="m",
        budget=RunBudget(5, 60, 30),
        final_patch="",
    )

    steps = [json.loads(line) for line in artifacts["trajectory_jsonl"].read_text().splitlines() if line.strip()]

    assert steps[0]["reasoning_summary"] == "Search for the broken function first."


def test_exporter_synthesizes_tool_call_summary_when_provider_omits_content(tmp_path: Path):
    exporter = TrajectoryExporter(tmp_path / "run6")

    artifacts = exporter.export(
        messages=[
            {"role": "system", "content": "You are a coder."},
            {"role": "user", "content": "Fix the bug."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps(
                                {
                                    "file_path": "/testbed/pandas/tests/indexing/test_loc.py",
                                    "view_range": [2990, 3025],
                                }
                            ),
                        },
                    }
                ],
            },
        ],
        run_id="test-tool-call-fallback",
        instance_id="test-tool-call-fallback",
        model_name="m",
        budget=RunBudget(5, 60, 30),
        final_patch="",
    )

    steps = [json.loads(line) for line in artifacts["trajectory_jsonl"].read_text().splitlines() if line.strip()]

    assert steps[0]["reasoning_summary"] == (
        "Call read_file with file_path=/testbed/pandas/tests/indexing/test_loc.py, "
        "view_range=[2990, 3025]."
    )
