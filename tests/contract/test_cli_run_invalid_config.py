from pathlib import Path

from coding_agent.cli import main


def test_run_rejects_missing_workspace(tmp_path: Path, capsys):
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix the app.", encoding="utf-8")

    exit_code = main(
        [
            "run",
            "--backend",
            "mock",
            "--instance-id",
            "example__repo-1",
            "--workspace",
            str(tmp_path / "missing"),
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
            str(tmp_path / "run"),
        ]
    )

    assert exit_code == 2
    assert "workspace" in capsys.readouterr().err


def test_openai_backend_rejects_missing_model_environment(tmp_path: Path, monkeypatch, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix the app.", encoding="utf-8")
    for key in ("PROVIDER", "MODEL", "API_KEY", "BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "run",
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
            str(tmp_path / "run"),
        ]
    )

    assert exit_code == 2
    assert "missing required model environment variables" in capsys.readouterr().err

