import json
from pathlib import Path

from coding_agent.agent import create_task_from_paths, run_task
from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend
from coding_agent.models import Outcome, RunBudget, ToolName
from coding_agent.tools.result import ToolExecutionResult


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[ToolName, dict]] = []

    def execute(self, tool_name: ToolName, tool_input: dict) -> ToolExecutionResult:
        self.calls.append((tool_name, dict(tool_input)))
        return ToolExecutionResult(
            tool_name=tool_name,
            status=Outcome.OK,
            output_summary="recorded",
            output={"content": "hello\n"},
        )


def test_existing_run_accepts_custom_executor_without_changing_artifacts(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("hello\n", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Read the file.", encoding="utf-8")
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=("python -m pytest",),
    )
    executor = RecordingExecutor()

    run_task(
        task=task,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        backend=MockBackend(
            [
                AgentAction(
                    action=AgentActionType.READ_FILE,
                    tool_input={"path": "README.md"},
                    reasoning_summary="Need context",
                ),
                
            ]
        ),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        tool_executor=executor,
    )

    assert executor.calls == [(ToolName.READ_FILE, {"path": "README.md"})]
    summary = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["instance_id"] == "example__repo-1"
