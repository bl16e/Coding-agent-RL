"""Contract tests for the official-style SWE-Bench runtime CLI surface."""

from pathlib import Path

from coding_agent.cli import main
from coding_agent.models import PreparedTaskEnvironment, PreparedEnvironmentStatus, RunStatus, RuntimeLineage
from tests.helpers.swebench_fixtures import swebench_row, write_swebench_parquet


LEGACY_SANDBOX_COMMANDS = ("prepare-sandbox", "solve-sandbox")
LEGACY_BATCH_COMMANDS = ("prepare-sandboxes", "solve-sandboxes")


def _prepared_env(tmp_path: Path) -> PreparedTaskEnvironment:
    return PreparedTaskEnvironment(
        instance_id="django__django-11099",
        repo="django/django",
        version="3.0",
        base_commit="abc123",
        container_name="task-container",
        repo_path="/testbed",
        runtime_lineage=RuntimeLineage(
            runtime_path="official_style",
            base_image_key="sweb.base.py.x86_64:latest",
            env_image_key="sweb.env.py.x86_64.2baaea72acc974f6c02079:latest",
            instance_image_key="sweb.eval.x86_64.django__django-11099:latest",
            platform="linux/x86_64",
            build_missing=False,
            reused_images=(
                "sweb.base.py.x86_64:latest",
                "sweb.env.py.x86_64.2baaea72acc974f6c02079:latest",
                "sweb.eval.x86_64.django__django-11099:latest",
            ),
            metadata_sources=("specs/003-agent-runtime-refactor/runtime-image-audit.md",),
        ),
        status=PreparedEnvironmentStatus.READY,
        sandbox_json=tmp_path / "sandbox.json",
    )


def test_swebench_prepare_requires_declared_arguments(capsys):
    exit_code = main(["swebench", "prepare"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--dataset" in captured.err
    assert "--instance-id" in captured.err
    assert "--output-dir" in captured.err
    assert "--build-missing" in captured.err


def test_swebench_prepare_rejects_registry_argument(tmp_path: Path, capsys):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")

    exit_code = main(
        [
            "swebench",
            "prepare",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--output-dir",
            str(tmp_path / "out"),
            "--registry",
            str(tmp_path / "registry.json"),
        ]
    )

    assert exit_code == 2
    assert "registry" in capsys.readouterr().err


def test_swebench_help_lists_only_prepare_and_run_for_runtime_work(capsys):
    exit_code = main(["swebench", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "prepare" in captured.out
    assert "run" in captured.out
    for command in (*LEGACY_SANDBOX_COMMANDS, *LEGACY_BATCH_COMMANDS):
        assert command not in captured.out


def test_swebench_run_rejects_registry_argument(tmp_path: Path, capsys):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")

    exit_code = main(
        [
            "swebench",
            "run",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--output-dir",
            str(tmp_path / "run"),
            "--registry",
            str(tmp_path / "registry.json"),
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--backend",
            "mock",
        ]
    )

    assert exit_code == 2
    assert "registry" in capsys.readouterr().err


def test_swebench_rejects_legacy_sandbox_runtime_commands(capsys):
    for command in LEGACY_SANDBOX_COMMANDS:
        exit_code = main(["swebench", command, "--help"])

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "unsupported" in captured.err.lower()
        assert command in captured.err
        assert "swebench prepare" in captured.err
        assert "swebench run" in captured.err


def test_swebench_rejects_legacy_batch_runtime_commands(capsys):
    for command in LEGACY_BATCH_COMMANDS:
        exit_code = main(["swebench", command, "--help"])

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "unsupported" in captured.err.lower()
        assert command in captured.err
        assert "swebench prepare" in captured.err
        assert "swebench run" in captured.err


def test_swebench_prepare_wires_build_missing_and_replace_existing(tmp_path: Path, monkeypatch):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    captured = {}

    def fake_prepare_official_swebench_runtime(**kwargs):
        captured.update(kwargs)
        return _prepared_env(tmp_path)

    monkeypatch.setattr("coding_agent.cli.prepare_official_swebench_runtime", fake_prepare_official_swebench_runtime)

    exit_code = main(
        [
            "swebench",
            "prepare",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--output-dir",
            str(tmp_path / "out"),
            "--build-missing",
            "--replace-existing",
            "--arch",
            "x86_64",
        ]
    )

    assert exit_code == 0
    assert captured["dataset_path"] == str(dataset)
    assert captured["instance_id"] == "django__django-11099"
    assert captured["output_dir"] == Path(tmp_path / "out")
    assert captured["build_missing"] is True
    assert captured["replace_existing"] is True
    assert captured["arch"] == "x86_64"


def test_swebench_prepare_reports_missing_images_before_agent_execution(tmp_path: Path, monkeypatch, capsys):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")

    def fake_prepare_official_swebench_runtime(**kwargs):
        raise ValueError("missing runtime images: sweb.env.py.x86_64.hash:latest")

    monkeypatch.setattr("coding_agent.cli.prepare_official_swebench_runtime", fake_prepare_official_swebench_runtime)

    exit_code = main(
        [
            "swebench",
            "prepare",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 2
    assert "missing runtime images" in capsys.readouterr().err


def test_swebench_prepare_rejects_missing_source_backed_repo_metadata(tmp_path: Path, capsys):
    dataset = write_swebench_parquet(
        tmp_path / "dataset.parquet",
        rows=[swebench_row(repo="django/django", version="0.0")],
    )

    exit_code = main(
        [
            "swebench",
            "prepare",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--output-dir",
            str(tmp_path / "prepare"),
        ]
    )

    assert exit_code == 2
    assert "missing source-backed metadata" in capsys.readouterr().err


def test_swebench_run_rejects_build_missing_argument(tmp_path: Path, capsys):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")

    exit_code = main(
        [
            "swebench",
            "run",
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--output-dir",
            str(tmp_path / "run"),
            "--build-missing",
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--backend",
            "mock",
        ]
    )

    assert exit_code == 2
    assert "build-missing" in capsys.readouterr().err


def test_swebench_run_contract_wires_active_index_and_cleanup(tmp_path: Path, monkeypatch):
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
            "--dataset",
            str(dataset),
            "--instance-id",
            "django__django-11099",
            "--output-dir",
            str(tmp_path / "run"),
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--include-pass-to-pass",
            "--cleanup",
            "--backend",
            "mock",
        ]
    )

    assert exit_code == 0
    assert captured["active_index_path"] == Path(".coding-agent/active-sandboxes.json")
    assert captured["cleanup"] is True
    assert captured["include_pass_to_pass"] is True
    assert "build_missing" not in captured
