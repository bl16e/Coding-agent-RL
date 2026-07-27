import json
from pathlib import Path

from coding_agent.models import RunBudget, ToolName
from tests.helpers.query_backend import ScriptedQueryBackend, ToolCallSpec, make_task, run_agent_for_test


def test_agent_records_only_allowed_tool_types(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("old\n", encoding="utf-8")
    task = make_task(tmp_path, workspace=workspace)
    backend = ScriptedQueryBackend(
        [
            ToolCallSpec(ToolName.READ_FILE, {"file_path": "app.py"}),
            ToolCallSpec(
                ToolName.APPLY_PATCH,
                {"path": "app.py", "old_string": "old", "new_string": "new"},
            ),
            ToolCallSpec(ToolName.SEARCH_CODE, {"pattern": "new"}),
        ]
    )

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=10, timeout_seconds=60, test_timeout_seconds=5),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    tool_names = []
    for line in (tmp_path / "run" / "trajectory.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["action_type"] == "tool_result":
            tool_names.append(row["tool_call"]["tool_name"])

    assert tool_names == ["read_file", "apply_patch", "search_code", "execute_bash", "finish"]
