import json
from pathlib import Path

from coding_agent.models import RunBudget, ToolName
from tests.helpers.query_backend import ScriptedQueryBackend, ToolCallSpec, make_task, run_agent_for_test


def test_max_step_budget_stop_is_recorded_in_summary(tmp_path: Path):
    task = make_task(tmp_path)
    backend = ScriptedQueryBackend(
        [
            ToolCallSpec(ToolName.READ_FILE, {"file_path": "missing_one.py"}),
            ToolCallSpec(ToolName.READ_FILE, {"file_path": "missing_two.py"}),
        ]
    )

    run_agent_for_test(
        task=task,
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        backend=backend,
        output_dir=tmp_path / "run",
    )

    summary = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "incomplete"
    assert summary["error"] == "LimitsExceeded"
