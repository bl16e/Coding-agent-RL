import json
from pathlib import Path

from coding_agent.cli import main


def test_summary_patch_and_prediction_are_consistent(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('hello')\n", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix the app.", encoding="utf-8")
    output_dir = tmp_path / "run"

    assert main(
        [
            "run",
            "--backend",
            "mock",
            "--instance-id",
            "example__repo-1",
            "--workspace",
            str(workspace),
            "--problem-statement-file",
            str(problem),
            "--allowed-test",
            "python -m pytest",
            "--max-steps",
            "3",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--output-dir",
            str(output_dir),
        ]
    ) == 0

    final_patch = (output_dir / "final.patch").read_text(encoding="utf-8")
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    prediction = json.loads((output_dir / "prediction.jsonl").read_text(encoding="utf-8"))

    assert prediction["instance_id"] == summary["instance_id"]
    assert prediction["model_name_or_path"] == summary["model_name"]
    assert prediction["model_patch"] == final_patch

