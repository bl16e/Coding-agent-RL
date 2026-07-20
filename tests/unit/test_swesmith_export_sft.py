import json
from pathlib import Path

from coding_agent.swesmith.export_sft import export_sft


def _write_run(root: Path, instance_id: str, resolved: bool) -> None:
    run_dir = root / instance_id
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"instance_id": instance_id, "model_name": "mock-model"}),
        encoding="utf-8",
    )
    (run_dir / "final.patch").write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps({"action_type": "model", "reasoning_summary": "I will inspect the code."}) + "\n"
        + json.dumps(
            {
                "action_type": "tool_result",
                "tool_call": {"tool_name": "read_file", "input": {"path": "app.py"}},
                "tool_result": {"output": {"content": "print('hi')"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report_dir = root.parent / "eval" / instance_id
    report_dir.mkdir(parents=True)
    report_dir.joinpath("report.json").write_text(json.dumps({"resolved": resolved}), encoding="utf-8")


def test_export_sft_includes_only_resolved_runs(tmp_path: Path):
    runs = tmp_path / "runs"
    _write_run(runs, "inst-1", True)
    _write_run(runs, "inst-2", False)
    output = tmp_path / "out.jsonl"

    count = export_sft(runs_dir=runs, eval_dir=tmp_path / "eval", output=output, style="xml")

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert count == 1
    assert rows[0]["instance_id"] == "inst-1"
    assert rows[0]["resolved"] is True
    assert rows[0]["messages"][0]["role"] == "system"
    assert any("<function=read_file>" in message["content"] for message in rows[0]["messages"])
