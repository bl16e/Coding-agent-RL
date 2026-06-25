from __future__ import annotations

import re

from coding_agent.models import BaseImage, TaskSandbox
from coding_agent.sandbox.docker_cli import DockerCli


def _container_name(instance_id: str, run_id: str | None = None) -> str:
    """把 SWE-Bench instance_id 转成 Docker 容器名安全字符串。"""
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", instance_id).strip("-").lower()
    if run_id:
        safe_run_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", run_id).strip("-").lower()
        return f"coding-agent-{safe}-{safe_run_id[:8]}"
    return f"coding-agent-{safe}"


class TaskSandboxManager:
    """创建任务容器，并把仓库重置到 SWE-Bench base commit。"""

    def __init__(self, *, docker: DockerCli) -> None:
        self._docker = docker

    def prepare(
        self,
        *,
        base_image: BaseImage,
        instance_id: str,
        base_commit: str,
        run_id: str | None = None,
    ) -> TaskSandbox:
        """准备一个可执行任务的容器。

        每次任务运行都重新 checkout base_commit，保证模型看到的是数据集声明的起点，
        而不是镜像里可能残留的分支或上一次实验状态。
        """
        name = _container_name(instance_id, run_id=run_id)
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

    def prepare_official_instance(
        self,
        *,
        repo: str,
        instance_id: str,
        base_commit: str,
        instance_image_key: str,
        repo_path: str,
        source_reference: str,
        run_id: str | None = None,
    ) -> TaskSandbox:
        """Prepare a task container from an official-style instance image."""
        base_image = BaseImage(
            repo=repo,
            image=instance_image_key,
            repo_path=repo_path,
            official_compatible=True,
            compatibility_source=source_reference,
        )
        return self.prepare(
            base_image=base_image,
            instance_id=instance_id,
            base_commit=base_commit,
            run_id=run_id,
        )

    def stop(self, sandbox: TaskSandbox) -> None:
        """停止并删除任务容器。

        stop/rm 在 DockerCli 中使用 check=False，清理阶段即使容器已退出也不会覆盖
        原始运行结果。
        """
        self._docker.stop_container(sandbox.container_name)
        self._docker.remove_container(sandbox.container_name)
