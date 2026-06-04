from pathlib import Path

import pytest

from coding_agent.agent import create_task_from_paths, run_task
from coding_agent.models import RunBudget, RunStatus
from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend


def test_agent_run_moves_from_pending_to_terminal_status(tmp_path: Path):
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
            AgentAction(
                action=AgentActionType.FINAL,
                reasoning_summary="No edits required",
                next_intent="Finish",
                final_status="solved",
                final_message="Solved",
            )
        ]
    )

    summary = run_task(
        task=task,
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    assert summary.status is RunStatus.SOLVED


def test_agent_run_rejects_invalid_final_status(tmp_path: Path):
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

    with pytest.raises(ValueError, match="unsupported final status"):
        run_task(
            task=task,
            budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=10),
            backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="unknown")]),
            model_name="mock-model",
            output_dir=tmp_path / "run",
        )

