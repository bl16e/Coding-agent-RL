import json
from pathlib import Path

from coding_agent.cli import main
from coding_agent.models import RunStatus


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


def test_swebench_run_wires_include_pass_to_pass_flag(tmp_path: Path, monkeypatch):
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    dataset = tmp_path / "dataset.parquet"
    parquet.write_table(
        pyarrow.table(
            {
                "instance_id": ["django__django-1"],
                "repo": ["django/django"],
                "base_commit": ["abc123"],
                "problem_statement": ["Fix it."],
                "FAIL_TO_PASS": [["tests/test_issue.py::test_fix"]],
                "PASS_TO_PASS": [["tests/test_regression.py::test_old"]],
            }
        ),
        dataset,
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "sandboxes": {
                    "django/django": {
                        "repo": "django/django",
                        "image": "django-base:latest",
                        "repo_path": "/workspace/repo",
                        "official_compatible": True,
                        "validation_command_template": "python -m pytest {tests}",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_run_swebench_task(**kwargs):
        captured["include_pass_to_pass"] = kwargs["include_pass_to_pass"]

        class Summary:
            status = RunStatus.INCOMPLETE
            error = None

        return Summary()

    monkeypatch.setattr("coding_agent.cli.run_swebench_task", fake_run_swebench_task)

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
            "--include-pass-to-pass",
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

    assert exit_code == 0
    assert captured["include_pass_to_pass"] is True


def test_swebench_run_accepts_repeated_instance_ids_and_jobs(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset.parquet"
    dataset.write_text("placeholder", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")
    captured = {}

    def fake_run_swebench_tasks(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("coding_agent.cli.run_swebench_tasks", fake_run_swebench_tasks)

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
            "--instance-id",
            "django__django-2",
            "--registry",
            str(registry),
            "--jobs",
            "2",
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

    assert exit_code == 0
    assert captured["instance_ids"] == ("django__django-1", "django__django-2")
    assert captured["jobs"] == 2


def test_swebench_run_reads_instance_id_file(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset.parquet"
    dataset.write_text("placeholder", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")
    instance_file = tmp_path / "instances.txt"
    instance_file.write_text("# batch\n\ndjango__django-1\ndjango__django-2\n", encoding="utf-8")
    captured = {}

    def fake_run_swebench_tasks(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("coding_agent.cli.run_swebench_tasks", fake_run_swebench_tasks)

    exit_code = main(
        [
            "swebench",
            "run",
            "--backend",
            "mock",
            "--dataset",
            str(dataset),
            "--instance-id-file",
            str(instance_file),
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

    assert exit_code == 0
    assert captured["instance_ids"] == ("django__django-1", "django__django-2")
