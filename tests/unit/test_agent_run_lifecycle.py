import json
from pathlib import Path

import pytest

from coding_agent.agent import create_task_from_paths, run_task
from coding_agent.models import RunBudget, RunStatus
from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend


class CapturingBackend:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def next_action(self, messages: list[dict[str, str]]) -> AgentAction:
        self.messages = messages
        return AgentAction(action=AgentActionType.FINAL, final_status="incomplete")


class TwoStepCapturingBackend:
    def __init__(self) -> None:
        self.messages_by_call: list[list[dict[str, str]]] = []

    def next_action(self, messages: list[dict[str, str]]) -> AgentAction:
        self.messages_by_call.append(messages)
        if len(self.messages_by_call) == 1:
            return AgentAction(action=AgentActionType.READ_FILE, tool_input={"path": "README.md"})
        return AgentAction(action=AgentActionType.FINAL, final_status="incomplete")


class NativeToolCallCapturingBackend:
    def __init__(self) -> None:
        self.messages_by_call: list[list[dict]] = []

    def next_action(self, messages: list[dict]) -> AgentAction:
        self.messages_by_call.append(messages)
        if len(self.messages_by_call) == 1:
            raw_message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            }
            return AgentAction(
                action=AgentActionType.READ_FILE,
                tool_input={"path": "README.md"},
                tool_call_id="call_read",
                raw_message=raw_message,
            )
        return AgentAction(action=AgentActionType.FINAL, final_status="incomplete")


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


def test_agent_prompt_describes_action_json_schema_and_allowed_tests(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix it.", encoding="utf-8")
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=("python -m pytest tests/test_issue.py::test_fix",),
    )
    backend = CapturingBackend()

    run_task(
        task=task,
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    system_prompt = backend.messages[0]["content"]
    # System prompt is task-focused; tool schemas are sent via API's tools parameter
    assert "coding agent" in system_prompt.lower()
    assert "solve" in system_prompt.lower() or "issue" in system_prompt.lower()
    assert "python -m pytest tests/test_issue.py::test_fix" in system_prompt


def test_agent_sends_tool_result_history_to_next_model_turn(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("important context", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix it.", encoding="utf-8")
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=("python -m pytest",),
    )
    backend = TwoStepCapturingBackend()

    run_task(
        task=task,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    second_turn = backend.messages_by_call[1]
    assert any("read_file" in message["content"] for message in second_turn)
    assert any("important context" in message["content"] for message in second_turn)


def test_agent_sends_native_tool_call_and_tool_result_history(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("important context", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix it.", encoding="utf-8")
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=("python -m pytest",),
    )
    backend = NativeToolCallCapturingBackend()

    run_task(
        task=task,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    second_turn = backend.messages_by_call[1]
    assert second_turn[-2]["role"] == "assistant"
    assert second_turn[-2]["tool_calls"][0]["id"] == "call_read"
    assert second_turn[-1]["role"] == "tool"
    assert second_turn[-1]["tool_call_id"] == "call_read"
    assert "important context" in second_turn[-1]["content"]


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


def test_agent_downgrades_solved_after_unresolved_tool_failure(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix it.", encoding="utf-8")
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=("python -m pytest tests/test_issue.py::test_fix",),
    )

    summary = run_task(
        task=task,
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=10),
        backend=MockBackend(
            [
                AgentAction(
                    action=AgentActionType.RUN_TESTS,
                    tool_input={"command": "python -m pytest"},
                ),
                AgentAction(action=AgentActionType.FINAL, final_status="solved"),
            ]
        ),
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    trajectory = json.loads((tmp_path / "run" / "trajectory.json").read_text(encoding="utf-8"))
    assert summary.status is RunStatus.INCOMPLETE
    assert "unresolved tool failure" in (summary.error or "")
    assert trajectory["resolved"] is False
