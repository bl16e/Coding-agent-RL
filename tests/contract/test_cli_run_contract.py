from pathlib import Path

from coding_agent.cli import main


def test_run_requires_all_declared_arguments(capsys):
    exit_code = main(["run"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--instance-id" in captured.err
    assert "--workspace" in captured.err
    assert "--allowed-test" in captured.err


def test_run_with_mock_backend_returns_zero_and_creates_artifacts(tmp_path: Path):
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
    assert (output_dir / "trajectory.jsonl").is_file()
    assert (output_dir / "final.patch").is_file()
    assert (output_dir / "summary.json").is_file()
    assert (output_dir / "prediction.jsonl").is_file()

