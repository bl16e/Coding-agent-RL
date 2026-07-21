import json
from pathlib import Path

from coding_agent.agent import create_task_from_paths, run_task
from coding_agent.models import RunBudget
from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend


def test_agent_persists_reasoning_intent_and_tool_selection_reason(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("old\n", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix it.", encoding="utf-8")
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=("python -m pytest",),
    )
    backend = MockBackend(
        [
            AgentAction(
                action=AgentActionType.READ_FILE,
                tool_input={"file_path": "app.py"},
                reasoning_summary="Need current implementation",
                next_intent="Read file",
                tool_selection_reason="app.py is likely relevant",
            ),
        ]
    )

    run_task(
        task=task,
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=5),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    first = json.loads((tmp_path / "run" / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["reasoning_summary"] == "Need current implementation"
    assert first["next_intent"] == "Read file"
    assert first["tool_selection_reason"] == "app.py is likely relevant"


def test_summary_trajectory_preserves_failed_apply_patch_status(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix it.", encoding="utf-8")
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=("python -m pytest",),
    )
    backend = MockBackend(
        [
            AgentAction(
                action=AgentActionType.APPLY_PATCH,
                tool_input={"type": "update", "file_path": "app.py", "old_string": "nope", "new_string": "yep"},
            ),
        ]
    )

    run_task(
        task=task,
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=5),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    trajectory = json.loads((tmp_path / "run" / "trajectory.json").read_text(encoding="utf-8"))
    assert trajectory["steps"][0]["observation"]["status"] == "failed"
    assert "not found" in trajectory["steps"][0]["observation"]["output"]
