from __future__ import annotations

import re

from coding_agent.models import BaseImage, TaskSandbox
from coding_agent.sandbox.docker_cli import DockerCli


def _container_name(instance_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", instance_id).strip("-").lower()
    return f"coding-agent-{safe}"


class TaskSandboxManager:
    """Create a task container and reset it to the SWE-Bench base commit."""

    def __init__(self, *, docker: DockerCli) -> None:
        self._docker = docker

    def prepare(self, *, base_image: BaseImage, instance_id: str, base_commit: str) -> TaskSandbox:
        name = _container_name(instance_id)
        self._docker.create_container(name=name, image=base_image.image)
        self._docker.start_container(name)
        self._docker.exec(name, ["git", "-C", base_image.repo_path, "checkout", base_commit])
        return TaskSandbox(
            container_name=name,
            base_image=base_image,
            instance_id=instance_id,
            repo=base_image.repo,
            base_commit=base_commit,
            repo_path=base_image.repo_path,
            status="ready",
        )

    def stop(self, sandbox: TaskSandbox) -> None:
        self._docker.stop_container(sandbox.container_name)
