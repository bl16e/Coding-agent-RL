import json
from pathlib import Path

from coding_agent.cli import main


def test_mock_backend_end_to_end_run_artifacts(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('hello')\n", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix the app.", encoding="utf-8")
    output_dir = tmp_path / "run"

    exit_code = main(
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
            "python -m pytest tests/test_example.py",
            "--max-steps",
            "3",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] in {"solved", "failed", "incomplete", "errored"}
    assert (output_dir / "trajectory.jsonl").read_text(encoding="utf-8").strip()

