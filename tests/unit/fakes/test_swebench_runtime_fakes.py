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
    diff_output: str = ""
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    stdin_by_call: list[str | None] = field(default_factory=list)

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
        return DockerResult("", "", 0)

    def stop_container(self, name: str) -> DockerResult:
        self.calls.append(("stop", (name,)))
        return DockerResult("", "", 0)

    def remove_container(self, name: str) -> DockerResult:
        self.calls.append(("remove", (name,)))
        self.present_containers.discard(name)
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
        if command[:2] == ["git", "-C"] and "diff" in command:
            return DockerResult(self.diff_output, "", 0)
        return DockerResult("", "", 0)
