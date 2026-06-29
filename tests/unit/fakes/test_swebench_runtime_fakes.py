"""Shared fake Docker helpers for official-style SWE-Bench runtime tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from coding_agent.sandbox.docker_cli import DockerResult


@dataclass
class FakeOfficialRuntimeDocker:
    """Recording fake for Docker operations used by runtime tests."""

    present_images: set[str] = field(default_factory=set)
    present_containers: set[str] = field(default_factory=set)
    running_containers: set[str] | None = None
    exec_results: dict[tuple[str, ...], DockerResult] = field(default_factory=dict)
    diff_output: str = ""
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    stdin_by_call: list[str | None] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.running_containers is None:
            self.running_containers = set(self.present_containers)

    def image_exists(self, image: str) -> bool:
        self.calls.append(("image_exists", (image,)))
        return image in self.present_images

    def container_exists(self, name: str) -> bool:
        self.calls.append(("container_exists", (name,)))
        return name in self.present_containers

    def create_container(self, *, name: str, image: str) -> DockerResult:
        self.calls.append(("create", (name, image)))
        self.present_containers.add(name)
        return DockerResult("", "", 0)

    def start_container(self, name: str) -> DockerResult:
        self.calls.append(("start", (name,)))
        self.present_containers.add(name)
        assert self.running_containers is not None
        self.running_containers.add(name)
        return DockerResult("", "", 0)

    def stop_container(self, name: str) -> DockerResult:
        self.calls.append(("stop", (name,)))
        assert self.running_containers is not None
        self.running_containers.discard(name)
        return DockerResult("", "", 0)

    def remove_container(self, name: str) -> DockerResult:
        self.calls.append(("remove", (name,)))
        self.present_containers.discard(name)
        assert self.running_containers is not None
        self.running_containers.discard(name)
        return DockerResult("", "", 0)

    def build_image(self, *, image: str, dockerfile: str, context: str = ".") -> DockerResult:
        self.calls.append(("build_image", (image, dockerfile, context)))
        self.present_images.add(image)
        return DockerResult("", "", 0)

    def exec(
        self,
        container: str,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        stdin: str | None = None,
    ) -> DockerResult:
        self.calls.append(("exec", (container, tuple(command), timeout_seconds)))
        self.stdin_by_call.append(stdin)
        assert self.running_containers is not None
        if container not in self.running_containers:
            raise RuntimeError(f"container is not running: {container}")
        configured = self.exec_results.get(tuple(command))
        if configured is not None:
            return configured
        if command == ["true"]:
            return DockerResult("", "", 0)
        if command[:2] == ["git", "-C"] and command[-2:] == ["rev-parse", "HEAD"]:
            return DockerResult("abc123\n", "", 0)
        if command[:2] == ["git", "-C"] and command[-2:] == ["status", "--porcelain"]:
            return DockerResult("", "", 0)
        if command[:2] == ["git", "-C"] and "diff" in command:
            return DockerResult(self.diff_output, "", 0)
        return DockerResult("", "", 0)
