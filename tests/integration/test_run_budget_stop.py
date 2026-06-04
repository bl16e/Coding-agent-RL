import json
from pathlib import Path

from coding_agent.agent import create_task_from_paths, run_task
from coding_agent.models import RunBudget
from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend


def test_max_step_budget_stop_is_recorded_in_summary(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
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
            AgentAction(action=AgentActionType.READ_FILE, reasoning_summary="Need file", next_intent="Read"),
            AgentAction(action=AgentActionType.READ_FILE, reasoning_summary="Still need file", next_intent="Read"),
        ]
    )

    run_task(
        task=task,
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    summary = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "incomplete"
    assert "max steps" in summary["error"]
