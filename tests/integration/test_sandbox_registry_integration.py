import json
from pathlib import Path

from coding_agent.cli import main


def _write_dataset(path: Path) -> None:
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    parquet.write_table(
        pyarrow.table(
            {
                "instance_id": ["django__django-1"],
                "repo": ["django/django"],
                "base_commit": ["abc123"],
                "problem_statement": ["Fix it."],
                "FAIL_TO_PASS": [["tests/test_issue.py::test_fix"]],
                "PASS_TO_PASS": [[]],
            }
        ),
        path,
    )


def test_swebench_run_missing_base_image_fails_before_model_execution(tmp_path: Path):
    dataset = tmp_path / "dataset.parquet"
    registry = tmp_path / "sandboxes.json"
    _write_dataset(dataset)
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
            "django__django-1",
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
    assert not (tmp_path / "run" / "trajectory.jsonl").exists()


def test_swebench_run_unmarked_base_image_fails_before_model_execution(tmp_path: Path):
    dataset = tmp_path / "dataset.parquet"
    registry = tmp_path / "sandboxes.json"
    _write_dataset(dataset)
    registry.write_text(
        json.dumps(
            {
                "sandboxes": {
                    "django/django": {
                        "repo": "django/django",
                        "image": "django-base:latest",
                        "repo_path": "/workspace/repo",
                        "official_compatible": False,
                        "validation_command_template": "python -m pytest {tests}",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "swebench",
            "run",
            "--backend",
            "mock",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-1",
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
    assert not (tmp_path / "run" / "trajectory.jsonl").exists()
