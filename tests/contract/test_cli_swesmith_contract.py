import json
from pathlib import Path

from coding_agent.cli import main


def test_swesmith_help_lists_official_pipeline_commands(capsys):
    exit_code = main(["swesmith", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "create-subset" in captured.out
    assert "run-subset" in captured.out
    assert "eval" in captured.out
    assert "export-sft" in captured.out


def test_swesmith_run_subset_wires_arguments(tmp_path: Path, monkeypatch):
    subset = tmp_path / "subset.json"
    subset.write_text(json.dumps([{"instance_id": "inst-1", "problem_statement": "Fix", "FAIL_TO_PASS": ["a"]}]), encoding="utf-8")
    captured = {}

    def fake_run_swesmith_subset(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("coding_agent.cli.run_swesmith_subset", fake_run_swesmith_subset, raising=False)

    exit_code = main(
        [
            "swesmith",
            "run-subset",
            "--subset",
            str(subset),
            "--output-dir",
            str(tmp_path / "runs"),
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--backend",
            "mock",
            "--model",
            "mock",
            "--reference-path",
            str(tmp_path / "Reference" / "SWE-smith"),
        ]
    )

    assert exit_code == 0
    assert captured["subset_path"] == str(subset)
    assert captured["output_dir"] == Path(tmp_path / "runs")
    assert captured["model_name"] == "mock"
