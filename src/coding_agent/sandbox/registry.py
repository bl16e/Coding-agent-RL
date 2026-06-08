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
    """从 JSON 注册表条目恢复 BaseImage。

    repo 同时存在于 map key 和条目字段里；优先接受条目字段是为了兼容手写注册表，
    但缺失时仍可用 key 作为仓库 id。
    """
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
    """把 BaseImage 转为稳定 JSON 字段集合。"""
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
    """基于 JSON 文件的仓库到基础镜像映射。

    注册表是本地开发者显式维护的信任边界：它记录“哪个 repo 可以用哪个镜像运行”，
    但不尝试自动推断或构建镜像。
    """

    def __init__(self, *, path: Path, sandboxes: dict[str, BaseImage] | None = None) -> None:
        self.path = path
        self.sandboxes = sandboxes or {}

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path: Path) -> "SandboxRegistry":
        """解析注册表 JSON，并校验顶层结构。"""
        entries = data.get("sandboxes", {})
        if not isinstance(entries, dict):
            raise SandboxRegistryError("registry sandboxes must be an object")
        return cls(path=path, sandboxes={repo: _base_image_from_dict(repo, entry) for repo, entry in entries.items()})

    @classmethod
    def load(cls, path: str | Path) -> "SandboxRegistry":
        """读取已存在的注册表。"""
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
        """读取注册表；文件不存在时返回空注册表，供 register 命令首次创建。"""
        registry_path = Path(path)
        if not registry_path.exists():
            return cls(path=registry_path)
        return cls.load(registry_path)

    def to_dict(self) -> dict[str, Any]:
        return {"sandboxes": {repo: _base_image_to_dict(base_image) for repo, base_image in sorted(self.sandboxes.items())}}

    def save(self) -> None:
        """持久化注册表，并确保父目录存在。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        except OSError as exc:
            raise SandboxRegistryError(str(exc)) from exc

    def upsert(self, base_image: BaseImage) -> None:
        self.sandboxes[base_image.repo] = base_image

    def lookup(self, repo: str) -> BaseImage:
        """按 SWE-Bench repo 字段查找基础镜像。"""
        try:
            return self.sandboxes[repo]
        except KeyError as exc:
            raise SandboxRegistryError(f"missing repository base image for {repo}") from exc


def validate_base_image_for_run(base_image: BaseImage) -> None:
    """校验镜像是否足以用于沙箱运行。"""
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
    """注册一个已经存在的基础镜像。

    该函数只做 image inspect 和 JSON 写入，不会拉取、构建或修改镜像。这样调用方能
    明确控制官方环境来源，避免在任务运行时隐式改变依赖环境。
    """
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
    """按仓库加载基础镜像，可选执行运行前强校验。"""
    base_image = SandboxRegistry.load(path).lookup(repo)
    if require_runnable:
        validate_base_image_for_run(base_image)
    return base_image
