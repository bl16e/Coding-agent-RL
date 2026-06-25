from pathlib import Path

from coding_agent.cli import main
from coding_agent.models import RunStatus
from tests.helpers.swebench_fixtures import write_swebench_parquet


def test_swebench_run_requires_declared_arguments(capsys):
    exit_code = main(["swebench", "run"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--dataset" in captured.err
    assert "--instance-id" in captured.err
    assert "--output-dir" in captured.err
    assert "--registry" not in captured.err


def test_swebench_run_rejects_registry_argument(tmp_path: Path, capsys):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")

    exit_code = main(
        [
            "swebench",
            "run",
            "--backend",
            "mock",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--registry",
            str(tmp_path / "registry.json"),
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
    assert "registry" in capsys.readouterr().err


def test_swebench_run_wires_official_prepared_runtime_dispatch(tmp_path: Path, monkeypatch):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    captured = {}

    class Summary:
        status = RunStatus.INCOMPLETE
        error = None

    def fake_run_prepared_swebench_runtime(**kwargs):
        captured.update(kwargs)
        return Summary()

    monkeypatch.setattr("coding_agent.cli.run_prepared_swebench_runtime", fake_run_prepared_swebench_runtime, raising=False)

    exit_code = main(
        [
            "swebench",
            "run",
            "--backend",
            "mock",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--include-pass-to-pass",
            "--cleanup",
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
    assert captured["dataset_path"] == str(dataset)
    assert captured["instance_id"] == "django__django-11099"
    assert captured["output_dir"] == Path(tmp_path / "run")
    assert captured["include_pass_to_pass"] is True
    assert captured["cleanup"] is True
    assert captured["active_index_path"] == Path(".coding-agent/active-sandboxes.json")


def test_swebench_run_does_not_expose_batch_arguments(tmp_path: Path, capsys):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")

    exit_code = main(
        [
            "swebench",
            "run",
            "--backend",
            "mock",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
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

    assert exit_code == 2
    assert "jobs" in capsys.readouterr().err
