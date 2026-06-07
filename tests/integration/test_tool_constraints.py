import json
from pathlib import Path

from coding_agent.agent import create_task_from_paths, run_task
from coding_agent.models import RunBudget
from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend


def test_agent_records_only_allowed_tool_types(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("old\n", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix it.", encoding="utf-8")
    allowed = "python -c \"print('ok')\""
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=(allowed,),
    )
    backend = MockBackend(
        [
            AgentAction(action=AgentActionType.READ_FILE, tool_input={"path": "app.py"}),
            AgentAction(action=AgentActionType.APPLY_PATCH, tool_input={"type": "update", "path": "app.py", "old_string": "old", "new_string": "new"}),
            AgentAction(action=AgentActionType.SEARCH_CODE, tool_input={"query": "new"}),
            AgentAction(action=AgentActionType.RUN_TESTS, tool_input={"command": allowed}),
            AgentAction(action=AgentActionType.FINAL, final_status="solved"),
        ]
    )

    run_task(
        task=task,
        budget=RunBudget(max_steps=10, timeout_seconds=60, test_timeout_seconds=5),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    tool_names = []
    for line in (tmp_path / "run" / "trajectory.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["action_type"] == "tool_result":
            tool_names.append(row["tool_call"]["tool_name"])

    assert tool_names == ["read_file", "apply_patch", "search_code", "run_tests"]

