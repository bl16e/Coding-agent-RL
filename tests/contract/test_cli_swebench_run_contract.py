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


def test_swebench_prepare_sandbox_wires_arguments(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset.parquet"
    dataset.write_text("placeholder", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")
    captured = {}

    class TaskRecord:
        repo = "django/django"

    class Prepared:
        status = "ready"

    def fake_load_task_record(dataset_path, instance_id):
        captured["dataset"] = dataset_path
        captured["instance_id"] = instance_id
        return TaskRecord()

    def fake_load_base_image_from_registry(registry_path, repo):
        captured["registry"] = registry_path
        captured["repo"] = repo
        return object()

    def fake_prepare_swebench_sandbox(**kwargs):
        captured.update(kwargs)
        return Prepared()

    monkeypatch.setattr("coding_agent.cli.load_task_record", fake_load_task_record)
    monkeypatch.setattr("coding_agent.cli.load_base_image_from_registry", fake_load_base_image_from_registry)
    monkeypatch.setattr("coding_agent.cli.prepare_swebench_sandbox", fake_prepare_swebench_sandbox)

    exit_code = main(
        [
            "swebench",
            "prepare-sandbox",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-1",
            "--registry",
            str(registry),
            "--output-dir",
            str(tmp_path / "prepared"),
            "--replace-existing",
        ]
    )

    assert exit_code == 0
    assert captured["instance_id"] == "django__django-1"
    assert captured["repo"] == "django/django"
    assert captured["output_dir"] == Path(tmp_path / "prepared")
    assert captured["active_index_path"] == Path(".coding-agent/active-sandboxes.json")
    assert captured["replace_existing"] is True


def test_swebench_solve_sandbox_wires_arguments(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset.parquet"
    dataset.write_text("placeholder", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")
    captured = {}

    class TaskRecord:
        repo = "django/django"

    class Summary:
        status = RunStatus.SOLVED
        error = None

    def fake_load_task_record(dataset_path, instance_id):
        captured["dataset"] = dataset_path
        captured["instance_id"] = instance_id
        return TaskRecord()

    def fake_load_active_sandbox(index_path, instance_id):
        captured["index_path"] = index_path
        captured["active_instance_id"] = instance_id
        return object()

    def fake_solve_prepared_sandbox(**kwargs):
        captured.update(kwargs)
        return Summary()

    monkeypatch.setattr("coding_agent.cli.load_task_record", fake_load_task_record)
    monkeypatch.setattr("coding_agent.cli.load_active_sandbox", fake_load_active_sandbox)
    monkeypatch.setattr("coding_agent.cli.solve_prepared_sandbox", fake_solve_prepared_sandbox)

    exit_code = main(
        [
            "swebench",
            "solve-sandbox",
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
            str(tmp_path / "solve"),
            "--cleanup",
        ]
    )

    assert exit_code == 0
    assert captured["active_instance_id"] == "django__django-1"
    assert captured["index_path"] == Path(".coding-agent/active-sandboxes.json")
    assert captured["output_dir"] == Path(tmp_path / "solve")
    assert captured["cleanup"] is True


def test_swebench_prepare_sandboxes_wires_batch_arguments(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset.parquet"
    dataset.write_text("placeholder", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")
    instance_file = tmp_path / "instances.txt"
    instance_file.write_text("django__django-1\ndjango__django-2\n", encoding="utf-8")
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("coding_agent.cli.prepare_swebench_sandboxes", fake_run)

    exit_code = main(
        [
            "swebench",
            "prepare-sandboxes",
            "--dataset",
            str(dataset),
            "--instance-id-file",
            str(instance_file),
            "--registry",
            str(registry),
            "--jobs",
            "2",
            "--output-dir",
            str(tmp_path / "batch"),
            "--state",
            str(tmp_path / "state.json"),
            "--replace-existing",
        ]
    )

    assert exit_code == 0
    assert captured["dataset_path"] == str(dataset)
    assert captured["instance_ids"] == ("django__django-1", "django__django-2")
    assert captured["registry_path"] == str(registry)
    assert captured["jobs"] == 2
    assert captured["state_path"] == Path(tmp_path / "state.json")
    assert captured["replace_existing"] is True


def test_swebench_solve_sandboxes_wires_batch_arguments(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset.parquet"
    dataset.write_text("placeholder", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("coding_agent.cli.solve_swebench_sandboxes", fake_run)

    exit_code = main(
        [
            "swebench",
            "solve-sandboxes",
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
            str(tmp_path / "batch"),
            "--state",
            str(tmp_path / "state.json"),
        ]
    )

    assert exit_code == 0
    assert captured["dataset_path"] == str(dataset)
    assert captured["instance_ids"] == ("django__django-1", "django__django-2")
    assert captured["active_index_path"] == Path(".coding-agent/active-sandboxes.json")
    assert captured["jobs"] == 2
    assert captured["state_path"] == Path(tmp_path / "state.json")
