import json
from pathlib import Path

from coding_agent.cli import main


def test_swebench_run_requires_declared_arguments(capsys):
    exit_code = main(["swebench", "run"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--dataset" in captured.err
    assert "--instance-id" in captured.err
    assert "--registry" in captured.err
    assert "--output-dir" in captured.err


def test_swebench_run_rejects_missing_dataset(tmp_path: Path, capsys):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")

    exit_code = main(
        [
            "swebench",
            "run",
            "--backend",
            "mock",
            "--dataset",
            str(tmp_path / "missing.parquet"),
            "--instance-id",
            "django__django-11099",
            "--registry",
            str(registry),
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--output-dir",
            str(tmp_path / "run"),
        ]
    )

    assert exit_code == 2
    assert "dataset" in capsys.readouterr().err


def test_swebench_run_rejects_missing_instance(tmp_path: Path, capsys):
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    dataset = tmp_path / "dataset.parquet"
    table = pyarrow.table(
        {
            "instance_id": ["django__django-1"],
            "repo": ["django/django"],
            "base_commit": ["abc123"],
            "problem_statement": ["Fix it."],
            "FAIL_TO_PASS": [["tests/test_issue.py::test_fix"]],
            "PASS_TO_PASS": [[]],
        }
    )
    parquet.write_table(table, dataset)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")

    exit_code = main(
        [
            "swebench",
            "run",
            "--backend",
            "mock",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-missing",
            "--registry",
            str(registry),
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--output-dir",
            str(tmp_path / "run"),
        ]
    )

    assert exit_code == 2
    assert "instance" in capsys.readouterr().err
