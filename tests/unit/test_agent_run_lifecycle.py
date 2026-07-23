import json
from pathlib import Path

from coding_agent.models import RunBudget, RunStatus, ToolName
from tests.helpers.query_backend import ScriptedQueryBackend, ToolCallSpec, make_task, run_agent_for_test


def test_agent_run_stops_naturally(tmp_path: Path):
    task = make_task(tmp_path)
    backend = ScriptedQueryBackend(final="All done.")

    summary = run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    assert summary.status is RunStatus.SOLVED


def test_agent_prompt_describes_tools_and_allowed_tests(tmp_path: Path):
    task = make_task(
        tmp_path,
        allowed_test_commands=("test/cli/commands_test.py::test__cli__command_directed",),
    )
    backend = ScriptedQueryBackend(final="done")

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    system_prompt = backend.messages_by_call[0][0]["content"]
    assert "coding agent" in system_prompt.lower()
    assert "apply_patch" in system_prompt
    assert "test__cli__command_directed" in system_prompt


def test_agent_sends_tool_result_history_to_next_model_turn(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("important context", encoding="utf-8")
    task = make_task(tmp_path, workspace=workspace)
    backend = ScriptedQueryBackend(
        [ToolCallSpec(ToolName.READ_FILE, {"file_path": "README.md"})],
        final="Looks good.",
    )

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    second_turn = backend.messages_by_call[1]
    assert any("read_file" in (message["content"] or "") for message in second_turn)
    assert any("important context" in (message["content"] or "") for message in second_turn)


def test_read_file_history_shows_source_text_without_json_escaping(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "validators.py").write_text("regex = r'^[\\w.@+-]+$'\n", encoding="utf-8")
    task = make_task(tmp_path, workspace=workspace)
    backend = ScriptedQueryBackend(
        [ToolCallSpec(ToolName.READ_FILE, {"file_path": "validators.py"})],
        final="Finished.",
    )

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    observation = backend.messages_by_call[1][-1]["content"]
    assert "regex = r'^[\\w.@+-]+$'" in observation
    assert "regex = r'^[\\\\w.@+-]+$'" not in observation


def test_agent_sends_native_tool_call_and_tool_result_history(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("important context\nregex = r'^[\\w.@+-]+$'\n", encoding="utf-8")
    task = make_task(tmp_path, workspace=workspace)
    backend = ScriptedQueryBackend(
        [ToolCallSpec(ToolName.READ_FILE, {"file_path": "README.md"}, tool_call_id="call_read")],
        final="All done.",
    )

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    second_turn = backend.messages_by_call[1]
    assert second_turn[-2]["role"] == "assistant"
    assert second_turn[-2]["tool_calls"][0]["id"] == "call_read"
    assert second_turn[-1]["role"] == "tool"
    assert second_turn[-1]["tool_call_id"] == "call_read"
    assert "important context" in second_turn[-1]["content"]
    assert "regex = r'^[\\w.@+-]+$'" in second_turn[-1]["content"]
    assert "regex = r'^[\\\\w.@+-]+$'" not in second_turn[-1]["content"]


def test_trajectory_records_native_tool_results(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("important context", encoding="utf-8")
    task = make_task(tmp_path, workspace=workspace)
    backend = ScriptedQueryBackend(
        [ToolCallSpec(ToolName.READ_FILE, {"file_path": "README.md"})],
        final="done",
    )

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "run" / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any((row.get("tool_call") or {}).get("tool_name") == "read_file" for row in rows)
