import json
from pathlib import Path

from coding_agent.cli import main


def test_swesmith_quality_gate_cli_writes_report_and_filtered_sft(tmp_path: Path):
    runs = tmp_path / "runs"
    run = runs / "inst-1"
    run.mkdir(parents=True)
    run.joinpath("summary.json").write_text(
        json.dumps({"instance_id": "inst-1", "model_name": "mock", "budget": {"max_steps": 50}}),
        encoding="utf-8",
    )
    run.joinpath("final.patch").write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
    run.joinpath("trajectory.jsonl").write_text(
        json.dumps({"action_type": "model", "reasoning_summary": "Inspect the file."}) + "\n"
        + json.dumps(
            {
                "action_type": "tool_result",
                "tool_call": {"tool_name": "read_file", "input": {"file_path": "app.py"}},
                "tool_result": {"status": "ok"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    eval_report = tmp_path / "eval" / "inst-1"
    eval_report.mkdir(parents=True)
    eval_report.joinpath("report.json").write_text(json.dumps({"resolved": True}), encoding="utf-8")
    report = tmp_path / "quality.json"
    filtered = tmp_path / "filtered.jsonl"

    exit_code = main(
        [
            "swesmith",
            "quality-gate",
            "--runs",
            str(runs),
            "--eval-dir",
            str(tmp_path / "eval"),
            "--out",
            str(report),
            "--filtered-sft",
            str(filtered),
        ]
    )

    assert exit_code == 0
    assert json.loads(report.read_text(encoding="utf-8"))["accepted_count"] == 1
    assert len([line for line in filtered.read_text(encoding="utf-8").splitlines() if line.strip()]) == 1
