import json
from pathlib import Path

import pytest

from coding_agent.sandbox_registry import (
    SandboxRegistry,
    SandboxRegistryError,
    load_base_image_from_registry,
    register_base_image,
    validate_base_image_for_run,
)


class FakeDocker:
    def __init__(self, existing_images: set[str] | None = None) -> None:
        self.existing_images = existing_images or set()

    def image_exists(self, image: str) -> bool:
        return image in self.existing_images


def test_registry_save_load_and_update_behavior(tmp_path: Path):
    path = tmp_path / "sandboxes.json"

    first = register_base_image(
        path,
        docker=FakeDocker({"django-base:v1", "django-base:v2"}),
        repo="django/django",
        image="django-base:v1",
        repo_path="/workspace/repo",
        official_compatible=True,
        validation_command_template="python -m pytest {tests}",
    )
    second = register_base_image(
        path,
        docker=FakeDocker({"django-base:v1", "django-base:v2"}),
        repo="django/django",
        image="django-base:v2",
        repo_path="/workspace/repo",
        official_compatible=True,
        compatibility_source="official",
        validation_command_template="python -m pytest {tests}",
    )

    loaded = SandboxRegistry.load(path)
    assert first.repo == "django/django"
    assert second.image == "django-base:v2"
    assert loaded.lookup("django/django").compatibility_source == "official"


def test_register_rejects_missing_image(tmp_path: Path):
    with pytest.raises(SandboxRegistryError, match="image not found"):
        register_base_image(
            tmp_path / "sandboxes.json",
            docker=FakeDocker(),
            repo="django/django",
            image="missing:latest",
            repo_path="/workspace/repo",
        )


def test_lookup_reports_missing_registry_and_missing_repo(tmp_path: Path):
    with pytest.raises(SandboxRegistryError, match="registry"):
        load_base_image_from_registry(tmp_path / "missing.json", "django/django")

    path = tmp_path / "sandboxes.json"
    path.write_text(json.dumps({"sandboxes": {}}), encoding="utf-8")
    with pytest.raises(SandboxRegistryError, match="missing repository base image"):
        load_base_image_from_registry(path, "django/django")


def test_validate_base_image_for_run_requires_official_marker_and_template():
    unmarked = load_base_image_from_registry_dict(
        {
            "repo": "django/django",
            "image": "django-base:latest",
            "repo_path": "/workspace/repo",
            "official_compatible": False,
            "validation_command_template": "python -m pytest {tests}",
        }
    )
    missing_template = load_base_image_from_registry_dict(
        {
            "repo": "django/django",
            "image": "django-base:latest",
            "repo_path": "/workspace/repo",
            "official_compatible": True,
        }
    )

    with pytest.raises(SandboxRegistryError, match="official_compatible"):
        validate_base_image_for_run(unmarked)
    with pytest.raises(SandboxRegistryError, match="validation command source"):
        validate_base_image_for_run(missing_template)


def load_base_image_from_registry_dict(entry: dict):
    path = Path(__file__).parent / "_tmp_registry_not_used.json"
    return SandboxRegistry.from_dict({"sandboxes": {"django/django": entry}}, path=path).lookup("django/django")
