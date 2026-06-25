from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class DockerResult:
    """Docker CLI 执行结果的轻量封装。"""

    stdout: str
    stderr: str
    returncode: int


class DockerCommandError(RuntimeError):
    """Docker 命令返回非零退出码时抛出。"""

    def __init__(self, args: list[str], result: DockerResult) -> None:
        self.args_list = args
        self.result = result
        message = result.stderr.strip() or result.stdout.strip() or f"docker command failed: {' '.join(args)}"
        super().__init__(message)


class DockerCommandTimeout(RuntimeError):
    """Docker 命令超过调用方预算时抛出。"""

    pass


Runner = Callable[..., subprocess.CompletedProcess[str]]


class DockerCli:
    """官方 Docker CLI 的小型包装器。

    这里不直接依赖 Docker SDK，原因是当前功能只需要少量稳定命令，并且 CLI 在开发机
    和 CI 上更容易 mock。所有 Docker 子进程细节都集中在这里，避免散落到 agent loop。
    """

    def __init__(self, *, runner: Runner = subprocess.run) -> None:
        self._runner = runner

    def run(
        self,
        args: list[str],
        *,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        check: bool = True,
    ) -> DockerResult:
        """执行一条 docker 子命令并返回标准输出、标准错误和退出码。"""
        command = ["docker", *args]
        stdin_bytes = stdin.encode("utf-8") if stdin is not None else None
        try:
            completed = self._runner(
                command,
                text=False,
                input=stdin_bytes,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerCommandTimeout(f"docker command timed out: {' '.join(command)}") from exc
        stdout = completed.stdout.decode("utf-8", errors="replace") if isinstance(completed.stdout, bytes) else completed.stdout or ""
        stderr = completed.stderr.decode("utf-8", errors="replace") if isinstance(completed.stderr, bytes) else completed.stderr or ""
        result = DockerResult(stdout or "", stderr or "", int(completed.returncode))
        if check and result.returncode != 0:
            raise DockerCommandError(args, result)
        return result

    def image_exists(self, image: str) -> bool:
        """检查镜像是否存在；用于注册阶段快速失败。"""
        return self.run(["image", "inspect", image], check=False).returncode == 0

    def container_exists(self, name: str) -> bool:
        """检查容器是否存在，供测试或未来恢复逻辑使用。"""
        return self.run(["container", "inspect", name], check=False).returncode == 0

    def create_container(self, *, name: str, image: str) -> DockerResult:
        """创建长驻任务容器。

        sleep infinity 让容器保持运行，后续仓库工具通过 docker exec 进入同一个容器，
        从而保留文件修改和测试环境状态。
        """
        return self.run(["create", "--name", name, image, "sleep", "infinity"])

    def start_container(self, name: str) -> DockerResult:
        return self.run(["start", name])

    def stop_container(self, name: str) -> DockerResult:
        return self.run(["stop", name], check=False)

    def remove_container(self, name: str) -> DockerResult:
        return self.run(["rm", "-f", name], check=False)

    def build_image(self, *, image: str, dockerfile: str, context: str = ".") -> DockerResult:
        return self.run(["build", "-t", image, "-f", "-", context], stdin=dockerfile)

    def exec(
        self,
        container: str,
        command: list[str],
        *,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
    ) -> DockerResult:
        """在任务容器中执行命令。"""
        return self.run(["exec", "-i", container, *command], timeout_seconds=timeout_seconds, stdin=stdin)
