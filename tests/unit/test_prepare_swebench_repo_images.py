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


def _write_dataset(path: Path, repos: list[str]) -> None:
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    table = pyarrow.table({"repo": repos, "instance_id": [f"task-{index}" for index, _ in enumerate(repos)]})
    parquet.write_table(table, path)


def test_load_unique_repos_merges_parquet_files_in_sorted_order(tmp_path: Path):
    module = _load_module()
    dev = tmp_path / "dev.parquet"
    test = tmp_path / "test.parquet"
    _write_dataset(dev, ["django/django", "psf/requests"])
    _write_dataset(test, ["django/django", "pytest-dev/pytest"])

    repos = module.load_unique_repos([dev, test])

    assert repos == ("django/django", "psf/requests", "pytest-dev/pytest")


def test_image_name_for_repo_replaces_owner_separator():
    module = _load_module()

    image = module.image_name_for_repo("django/django", "coding-agent-swebench-repo")

    assert image == "coding-agent-swebench-repo-django-django:latest"


def test_inspect_image_reports_existing_and_missing():
    module = _load_module()
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0 if "present:latest" in command else 1, "", "")

    assert module.image_exists("present:latest", runner=runner) is True
    assert module.image_exists("missing:latest", runner=runner) is False
    assert calls == [
        ["docker", "image", "inspect", "present:latest"],
        ["docker", "image", "inspect", "missing:latest"],
    ]


def test_check_only_does_not_build_missing_images(tmp_path: Path):
    module = _load_module()
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "missing")

    results = module.prepare_repo_images(
        ["django/django"],
        manifest_path=tmp_path / "manifest.json",
        runner=runner,
        build_missing=False,
    )

    assert [result.status for result in results] == ["missing"]
    assert len(calls) == 1
    assert calls[0][:3] == ["docker", "image", "inspect"]


def test_force_rebuild_builds_existing_images(tmp_path: Path):
    module = _load_module()
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    results = module.prepare_repo_images(
        ["django/django"],
        manifest_path=tmp_path / "manifest.json",
        runner=runner,
        force_rebuild=True,
    )

    assert [result.status for result in results] == ["built"]
    assert any(call[:2] == ["docker", "build"] for call in calls)


def test_manifest_records_repo_base_image_fields(tmp_path: Path):
    module = _load_module()

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "", "")

    manifest_path = tmp_path / ".coding-agent" / "repo-base-images.json"

    module.prepare_repo_images(
        ["django/django"],
        manifest_path=manifest_path,
        runner=runner,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["images"][0]["repo"] == "django/django"
    assert manifest["images"][0]["image"] == "coding-agent-swebench-repo-django-django:latest"
    assert manifest["images"][0]["repo_path"] == "/workspace/repo"
    assert manifest["images"][0]["status"] == "existing"
    assert "built_at" in manifest["images"][0]
