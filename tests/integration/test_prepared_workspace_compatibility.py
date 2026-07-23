import json
from pathlib import Path

from coding_agent.models import Outcome, RunBudget, ToolName
from coding_agent.tools.result import ToolExecutionResult
from tests.helpers.query_backend import ScriptedQueryBackend, ToolCallSpec, make_task, run_agent_for_test


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
    task = make_task(tmp_path, problem_statement="Read the file.")
    executor = RecordingExecutor()

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        backend=ScriptedQueryBackend(
            [ToolCallSpec(ToolName.READ_FILE, {"file_path": "README.md"})]
        ),
        output_dir=tmp_path / "run",
        tool_executor=executor,
    )

    assert executor.calls == [(ToolName.READ_FILE, {"file_path": "README.md"})]
    summary = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["instance_id"] == "example__repo-1"
