from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "prepare_swebench_repo_images.py"
    spec = importlib.util.spec_from_file_location("prepare_swebench_repo_images", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_dataset(path: Path) -> None:
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    table = pyarrow.table(
        {
            "repo": ["django/django", "psf/requests"],
            "instance_id": ["django__django-1", "psf__requests-1"],
        }
    )
    parquet.write_table(table, path)


def test_cli_dry_run_prints_build_commands_without_calling_docker(tmp_path: Path, capsys):
    module = _load_module()
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)

    def runner(command, **kwargs):
        raise AssertionError("dry-run must not call docker")

    exit_code = module.main(
        [
            "--dataset",
            str(dataset),
            "--repo",
            "django/django",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--dry-run",
        ],
        runner=runner,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "docker build --build-arg REPO=django/django" in captured.out
    assert "psf/requests" not in captured.out


def test_cli_check_only_dry_run_prints_inspect_commands(tmp_path: Path, capsys):
    module = _load_module()
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)

    def runner(command, **kwargs):
        raise AssertionError("dry-run must not call docker")

    exit_code = module.main(
        [
            "--dataset",
            str(dataset),
            "--repo",
            "django/django",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--check-only",
            "--dry-run",
        ],
        runner=runner,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "docker image inspect coding-agent-swebench-repo-django-django:latest" in captured.out
    assert "docker build" not in captured.out


def test_cli_returns_four_when_a_build_fails(tmp_path: Path, capsys):
    module = _load_module()
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)

    def runner(command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 1, "", "missing")
        return subprocess.CompletedProcess(command, 7, "", "build failed")

    exit_code = module.main(
        [
            "--dataset",
            str(dataset),
            "--repo",
            "django/django",
            "--manifest",
            str(tmp_path / "manifest.json"),
        ],
        runner=runner,
    )

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "failed: django/django" in captured.out


def test_cli_creates_manifest_parent_directory(tmp_path: Path):
    module = _load_module()
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)
    manifest = tmp_path / "nested" / ".coding-agent" / "repo-base-images.json"

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "", "")

    exit_code = module.main(
        [
            "--dataset",
            str(dataset),
            "--repo",
            "django/django",
            "--manifest",
            str(manifest),
            "--check-only",
        ],
        runner=runner,
    )

    assert exit_code == 0
    assert json.loads(manifest.read_text(encoding="utf-8"))["images"][0]["repo"] == "django/django"
