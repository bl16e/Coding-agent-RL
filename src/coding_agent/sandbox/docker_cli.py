from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class DockerResult:
    stdout: str
    stderr: str
    returncode: int


class DockerCommandError(RuntimeError):
    def __init__(self, args: list[str], result: DockerResult) -> None:
        self.args_list = args
        self.result = result
        message = result.stderr.strip() or result.stdout.strip() or f"docker command failed: {' '.join(args)}"
        super().__init__(message)


class DockerCommandTimeout(RuntimeError):
    pass


Runner = Callable[..., subprocess.CompletedProcess[str]]


class DockerCli:
    """Small wrapper around the official Docker CLI command surface."""

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
        command = ["docker", *args]
        try:
            completed = self._runner(
                command,
                text=True,
                input=stdin,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerCommandTimeout(f"docker command timed out: {' '.join(command)}") from exc
        result = DockerResult(completed.stdout or "", completed.stderr or "", int(completed.returncode))
        if check and result.returncode != 0:
            raise DockerCommandError(args, result)
        return result

    def image_exists(self, image: str) -> bool:
        return self.run(["image", "inspect", image], check=False).returncode == 0

    def container_exists(self, name: str) -> bool:
        return self.run(["container", "inspect", name], check=False).returncode == 0

    def create_container(self, *, name: str, image: str) -> DockerResult:
        return self.run(["create", "--name", name, image, "sleep", "infinity"])

    def start_container(self, name: str) -> DockerResult:
        return self.run(["start", name])

    def stop_container(self, name: str) -> DockerResult:
        return self.run(["stop", name], check=False)

    def remove_container(self, name: str) -> DockerResult:
        return self.run(["rm", "-f", name], check=False)

    def exec(
        self,
        container: str,
        command: list[str],
        *,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
    ) -> DockerResult:
        return self.run(["exec", "-i", container, *command], timeout_seconds=timeout_seconds, stdin=stdin)
