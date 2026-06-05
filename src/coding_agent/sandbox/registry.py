from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from coding_agent.models import BaseImage, utc_now
from coding_agent.sandbox.docker_cli import DockerCli


class SandboxRegistryError(ValueError):
    """Raised for registry persistence or validation failures."""


def _base_image_from_dict(repo: str, entry: dict[str, Any]) -> BaseImage:
    try:
        return BaseImage(
            repo=str(entry.get("repo", repo)),
            image=str(entry["image"]),
            repo_path=str(entry["repo_path"]),
            official_compatible=bool(entry.get("official_compatible", False)),
            compatibility_source=entry.get("compatibility_source"),
            validation_command_template=entry.get("validation_command_template"),
            registered_at=None,
        )
    except KeyError as exc:
        raise SandboxRegistryError(f"registry entry for {repo} is missing {exc.args[0]}") from exc


def _base_image_to_dict(base_image: BaseImage) -> dict[str, Any]:
    return {
        "repo": base_image.repo,
        "image": base_image.image,
        "repo_path": base_image.repo_path,
        "official_compatible": base_image.official_compatible,
        "compatibility_source": base_image.compatibility_source,
        "validation_command_template": base_image.validation_command_template,
        "registered_at": base_image.registered_at.isoformat() if base_image.registered_at else None,
    }


class SandboxRegistry:
    """JSON-backed mapping from repository id to prepared base image."""

    def __init__(self, *, path: Path, sandboxes: dict[str, BaseImage] | None = None) -> None:
        self.path = path
        self.sandboxes = sandboxes or {}

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path: Path) -> "SandboxRegistry":
        entries = data.get("sandboxes", {})
        if not isinstance(entries, dict):
            raise SandboxRegistryError("registry sandboxes must be an object")
        return cls(path=path, sandboxes={repo: _base_image_from_dict(repo, entry) for repo, entry in entries.items()})

    @classmethod
    def load(cls, path: str | Path) -> "SandboxRegistry":
        registry_path = Path(path)
        if not registry_path.is_file():
            raise SandboxRegistryError(f"registry does not exist: {registry_path}")
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SandboxRegistryError(f"registry is unreadable: {registry_path}") from exc
        return cls.from_dict(data, path=registry_path)

    @classmethod
    def load_or_empty(cls, path: str | Path) -> "SandboxRegistry":
        registry_path = Path(path)
        if not registry_path.exists():
            return cls(path=registry_path)
        return cls.load(registry_path)

    def to_dict(self) -> dict[str, Any]:
        return {"sandboxes": {repo: _base_image_to_dict(base_image) for repo, base_image in sorted(self.sandboxes.items())}}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        except OSError as exc:
            raise SandboxRegistryError(str(exc)) from exc

    def upsert(self, base_image: BaseImage) -> None:
        self.sandboxes[base_image.repo] = base_image

    def lookup(self, repo: str) -> BaseImage:
        try:
            return self.sandboxes[repo]
        except KeyError as exc:
            raise SandboxRegistryError(f"missing repository base image for {repo}") from exc


def validate_base_image_for_run(base_image: BaseImage) -> None:
    if not base_image.official_compatible:
        raise SandboxRegistryError("base image must be marked official_compatible")
    if not base_image.validation_command_template:
        raise SandboxRegistryError("validation command source is required")


def register_base_image(
    path: str | Path,
    *,
    docker: DockerCli,
    repo: str,
    image: str,
    repo_path: str,
    official_compatible: bool = False,
    compatibility_source: str | None = None,
    validation_command_template: str | None = None,
) -> BaseImage:
    if not docker.image_exists(image):
        raise SandboxRegistryError(f"image not found: {image}")
    registry = SandboxRegistry.load_or_empty(path)
    base_image = BaseImage(
        repo=repo,
        image=image,
        repo_path=repo_path,
        official_compatible=official_compatible,
        compatibility_source=compatibility_source,
        validation_command_template=validation_command_template,
        registered_at=utc_now(),
    )
    registry.upsert(base_image)
    registry.save()
    return base_image


def load_base_image_from_registry(path: str | Path, repo: str, *, require_runnable: bool = False) -> BaseImage:
    base_image = SandboxRegistry.load(path).lookup(repo)
    if require_runnable:
        validate_base_image_for_run(base_image)
    return base_image
