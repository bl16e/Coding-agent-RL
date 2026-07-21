import json
from pathlib import Path

from coding_agent.cli import main


def test_fake_swesmith_pipeline_exports_only_resolved(tmp_path: Path, monkeypatch):
    subset = tmp_path / "subset.json"
    subset.write_text(
        json.dumps(
            [
                {"instance_id": "inst-1", "problem_statement": "Fix one", "FAIL_TO_PASS": ["a"]},
                {"instance_id": "inst-2", "problem_statement": "Fix two", "FAIL_TO_PASS": ["b"]},
            ]
        ),
        encoding="utf-8",
    )

    def fake_run_subset(**kwargs):
        root = Path(kwargs["output_dir"])
        for instance_id in ("inst-1", "inst-2"):
            run_dir = root / instance_id
            run_dir.mkdir(parents=True)
            (run_dir / "summary.json").write_text(json.dumps({"instance_id": instance_id, "model_name": "mock"}), encoding="utf-8")
            (run_dir / "final.patch").write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
            (run_dir / "trajectory.jsonl").write_text(
                json.dumps({"action_type": "model", "reasoning_summary": "Inspect."}) + "\n"
                + json.dumps(
                    {
                        "action_type": "tool_result",
                        "tool_call": {"tool_name": "read_file", "input": {"file_path": "app.py"}},
                        "tool_result": {"output": {"content": "x"}},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        (root / "preds.jsonl").write_text("", encoding="utf-8")
        (root / "batch_summary.json").write_text(json.dumps({"total": 2}), encoding="utf-8")
        return 0

    monkeypatch.setattr("coding_agent.cli.run_swesmith_subset", fake_run_subset, raising=False)
    runs = tmp_path / "runs"
    assert (
        main(
            [
                "swesmith",
                "run-subset",
                "--subset",
                str(subset),
                "--output-dir",
                str(runs),
                "--max-steps",
                "1",
                "--timeout-seconds",
                "60",
                "--test-timeout-seconds",
                "10",
                "--backend",
                "mock",
            ]
        )
        == 0
    )

    eval_dir = tmp_path / "eval"
    for instance_id, resolved in {"inst-1": True, "inst-2": False}.items():
        report_dir = eval_dir / instance_id
        report_dir.mkdir(parents=True)
        (report_dir / "report.json").write_text(json.dumps({"resolved": resolved}), encoding="utf-8")

    output = tmp_path / "sft.jsonl"
    assert main(["swesmith", "export-sft", "--runs", str(runs), "--eval-dir", str(eval_dir), "--out", str(output)]) == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["instance_id"] for row in rows] == ["inst-1"]
