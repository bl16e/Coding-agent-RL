import json
from pathlib import Path

from coding_agent.models import RunBudget, ToolName
from tests.helpers.query_backend import ScriptedQueryBackend, ToolCallSpec, make_task, run_agent_for_test


def test_agent_persists_model_reasoning_text(tmp_path: Path):
    task = make_task(tmp_path)
    backend = ScriptedQueryBackend(
        [ToolCallSpec(ToolName.READ_FILE, {"file_path": "app.py"})],
        final="done",
    )

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=5),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    first = json.loads((tmp_path / "run" / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["action_type"] == "model"


def test_summary_trajectory_preserves_failed_apply_patch_status(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    task = make_task(tmp_path, workspace=workspace)
    backend = ScriptedQueryBackend(
        [
            ToolCallSpec(
                ToolName.APPLY_PATCH,
                {
                    "type": "update",
                    "file_path": "app.py",
                    "old_string": "nope",
                    "new_string": "yep",
                },
            )
        ],
        final="done",
    )

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=5),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    trajectory = json.loads((tmp_path / "run" / "trajectory.json").read_text(encoding="utf-8"))
    tool_steps = [
        step for step in trajectory["trajectory"]
        if step["action_type"] == "tool_result"
    ]
    assert tool_steps[0]["tool_call"]["status"] == "failed"
    assert "not found" in tool_steps[0]["tool_call"]["output_summary"]
