from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import AbstractSet

from coding_agent.models import AdaptedTestSpec


class MissingRuntimeImagesError(ValueError):
    """Raised when required runtime images are absent and builds are not allowed."""


@dataclass(frozen=True)
class ImageGraphPlan:
    ordered_image_keys: tuple[str, str, str]
    reused_images: tuple[str, ...]
    missing_images: tuple[str, ...]
    build_missing: bool


AUDIT_SOURCE_REFERENCE = "specs/003-agent-runtime-refactor/runtime-image-audit.md"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _audit_path() -> Path:
    return _project_root() / AUDIT_SOURCE_REFERENCE


def _parse_env_image_keys(audit_text: str) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for line in audit_text.splitlines():
        match = re.match(r"\| `(sweb\.env\.[^`]+)` \| \d+ \| (.+) \|", line)
        if not match:
            continue
        image_key = match.group(1)
        coverage = match.group(2)
        for repo, version in re.findall(r"`([^`@]+)@([^`]+)`", coverage):
            result[(repo, version)] = image_key
    return result


def audit_env_image_key(repo: str, version: str, *, audit_path: Path | None = None) -> str:
    path = audit_path or _audit_path()
    if not path.is_file():
        raise MissingRuntimeImagesError(f"runtime image audit is missing: {path}")
    mapping = _parse_env_image_keys(path.read_text(encoding="utf-8"))
    try:
        return mapping[(repo, version)]
    except KeyError as exc:
        raise MissingRuntimeImagesError(f"missing env image key for {repo}@{version}") from exc


def derive_base_image_key(*, language: str, arch: str = "x86_64") -> str:
    return f"sweb.base.{language}.{arch}:latest"


def derive_instance_image_key(*, instance_id: str, arch: str = "x86_64") -> str:
    return f"sweb.eval.{arch}.{instance_id.lower()}:latest"


def plan_image_graph(
    testspec: AdaptedTestSpec,
    *,
    existing_images: AbstractSet[str],
    build_missing: bool,
) -> ImageGraphPlan:
    ordered = (testspec.base_image_key, testspec.env_image_key, testspec.instance_image_key)
    reused = tuple(image for image in ordered if image in existing_images)
    missing = tuple(image for image in ordered if image not in existing_images)
    if missing and not build_missing:
        raise MissingRuntimeImagesError("missing runtime images: " + ", ".join(missing))
    return ImageGraphPlan(
        ordered_image_keys=ordered,
        reused_images=reused,
        missing_images=missing,
        build_missing=build_missing,
    )


def inspect_image_graph(testspec: AdaptedTestSpec, *, docker, build_missing: bool) -> ImageGraphPlan:
    existing = {image for image in (testspec.base_image_key, testspec.env_image_key, testspec.instance_image_key) if docker.image_exists(image)}
    return plan_image_graph(testspec, existing_images=existing, build_missing=build_missing)


def build_missing_images(testspec: AdaptedTestSpec, *, docker, plan: ImageGraphPlan) -> tuple[str, ...]:
    built: list[str] = []
    dockerfiles = {
        testspec.base_image_key: "base Dockerfile",
        testspec.env_image_key: "env Dockerfile",
        testspec.instance_image_key: "instance Dockerfile",
    }
    for image in plan.ordered_image_keys:
        if image not in plan.missing_images:
            continue
        docker.build_image(image=image, dockerfile=dockerfiles[image], context=".")
        built.append(image)
    return tuple(built)
