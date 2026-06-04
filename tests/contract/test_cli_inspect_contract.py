from pathlib import Path

from coding_agent.cli import main


def test_inspect_rejects_missing_run_dir(tmp_path: Path, capsys):
    exit_code = main(["inspect", "--run-dir", str(tmp_path / "missing")])

    assert exit_code == 2
    assert "run directory" in capsys.readouterr().err


def test_inspect_prints_concise_report(tmp_path: Path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        '{"status":"solved","changed_files":["app.py"],"error":null}', encoding="utf-8"
    )
    (run_dir / "trajectory.jsonl").write_text(
        '{"action_type":"tool_result","outcome":"ok","tool_call":{"tool_name":"read_file","status":"ok"}}\n',
        encoding="utf-8",
    )

    exit_code = main(["inspect", "--run-dir", str(run_dir)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Final status: solved" in output
    assert "Changed files: app.py" in output
    assert "Last successful tool call: read_file" in output

