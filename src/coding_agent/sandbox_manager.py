# src/coding_agent/sandbox.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from swerex.deployment.docker import DockerDeployment
from swerex.runtime.abstract import AbstractRuntime

logger = logging.getLogger(__name__)


class SandboxError(RuntimeError):
    """Raised when sandbox operations fail."""


class SandboxManager:
    """Manage a SWE-ReX DockerDeployment for a single agent run.

    Wraps SWE-ReX's async DockerDeployment behind a synchronous interface
    using a dedicated event loop::

        mgr = SandboxManager(image="...")
        runtime = mgr.start()
        try:
            # use runtime for tool execution
            ...
        finally:
            mgr.stop()
    """

    def __init__(self, *, image: str, **kwargs: Any):
        self._config = {"image": image, **kwargs}
        self._deployment: DockerDeployment | None = None
        self._runtime: AbstractRuntime | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> AbstractRuntime:
        """Start the container and return the runtime. Call once per run."""
        self._loop = asyncio.new_event_loop()
        self._deployment = DockerDeployment(**self._config)
        try:
            self._loop.run_until_complete(self._deployment.start())
        except Exception as exc:
            raise SandboxError(f"failed to start sandbox: {exc}") from exc
        self._runtime = self._deployment.runtime
        logger.info("Sandbox started: %s", self._config.get("image"))
        return self._runtime

    def stop(self) -> None:
        """Stop and clean up the container. Safe to call multiple times."""
        if self._deployment is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._deployment.stop())
            except Exception as exc:
                logger.warning("Error stopping sandbox: %s", exc)
            finally:
                self._deployment = None
                self._runtime = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    @property
    def runtime(self) -> AbstractRuntime:
        if self._runtime is None:
            raise SandboxError("sandbox not started")
        return self._runtime

# === Docker CLI (merged from old sandbox/docker_cli.py) ===

import subprocess as _subprocess
from dataclasses import dataclass as _dataclass
from typing import Callable as _Callable

_sandbox_logger = logging.getLogger("coding_agent.sandbox")


@_dataclass(frozen=True)
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


_Runner = _Callable[..., _subprocess.CompletedProcess[str]]


class DockerCli:
    def __init__(self, *, runner: _Runner = _subprocess.run) -> None:
        self._runner = runner

    def run(self, args: list[str], *, timeout_seconds: float | None = None, stdin: str | None = None, check: bool = True) -> DockerResult:
        command = ["docker", *args]
        _sandbox_logger.debug("docker command start: %s", " ".join(command))
        stdin_bytes = stdin.encode("utf-8") if stdin is not None else None
        try:
            completed = self._runner(command, text=False, input=stdin_bytes, capture_output=True, timeout=timeout_seconds, check=False)
        except _subprocess.TimeoutExpired as exc:
            _sandbox_logger.warning("docker command timed out: %s", " ".join(command))
            raise DockerCommandTimeout(f"docker command timed out: {' '.join(command)}") from exc
        stdout = completed.stdout.decode("utf-8", errors="replace") if isinstance(completed.stdout, bytes) else completed.stdout or ""
        stderr = completed.stderr.decode("utf-8", errors="replace") if isinstance(completed.stderr, bytes) else completed.stderr or ""
        result = DockerResult(stdout or "", stderr or "", int(completed.returncode))
        _sandbox_logger.debug("docker command finished rc=%s: %s", result.returncode, " ".join(command))
        if check and result.returncode != 0:
            _sandbox_logger.warning("docker command failed rc=%s: %s; %s", result.returncode, " ".join(command), (result.stderr or result.stdout).strip())
            raise DockerCommandError(args, result)
        return result

    def _inspect_exists(self, args: list[str], *, missing_markers: tuple[str, ...]) -> bool:
        result = self.run(args, check=False)
        target = args[-1]
        if result.returncode == 0:
            _sandbox_logger.info("docker inspect found: %s", target)
            return True
        detail = (result.stderr or result.stdout).strip()
        lowered = detail.lower()
        if any(marker in lowered for marker in missing_markers):
            _sandbox_logger.info("docker inspect missing: %s; %s", target, detail)
            return False
        _sandbox_logger.error("docker inspect failed for %s: %s", target, detail or f"exit code {result.returncode}")
        raise DockerCommandError(args, result)

    def image_exists(self, image: str) -> bool:
        return self._inspect_exists(["image", "inspect", image], missing_markers=("no such image", "no such object", "not found"))

    def container_exists(self, name: str) -> bool:
        return self._inspect_exists(["container", "inspect", name], missing_markers=("no such container", "no such object", "not found"))

    def create_container(self, *, name: str, image: str) -> DockerResult:
        return self.run(["create", "--name", name, image, "sleep", "infinity"])

    def start_container(self, name: str) -> DockerResult:
        return self.run(["start", name])

    def stop_container(self, name: str) -> DockerResult:
        return self.run(["stop", name], check=False)

    def remove_container(self, name: str) -> DockerResult:
        return self.run(["rm", "-f", name], check=False)

    def build_image(self, *, image: str, dockerfile: str, context: str = ".") -> DockerResult:
        return self.run(["build", "-t", image, "-f", "-", context], stdin=dockerfile)

    def exec(self, container: str, command: list[str], *, timeout_seconds: float | None = None, stdin: str | None = None, workdir: str | None = None) -> DockerResult:
        args = ["exec", "-i"]
        if workdir is not None:
            args.extend(["-w", workdir])
        args.extend([container, *command])
        return self.run(args, timeout_seconds=timeout_seconds, stdin=stdin)


# === TaskSandboxManager (merged from old sandbox/manager.py) ===

import re as _re

def _container_name(instance_id: str, run_id: str | None = None) -> str:
    safe = _re.sub(r"[^a-zA-Z0-9_.-]+", "-", instance_id).strip("-").lower()
    if run_id:
        safe_run_id = _re.sub(r"[^a-zA-Z0-9_.-]+", "-", run_id).strip("-").lower()
        return f"coding-agent-{safe}-{safe_run_id[:8]}"
    return f"coding-agent-{safe}"


class TaskSandboxManager:
    def __init__(self, *, docker: DockerCli) -> None:
        self._docker = docker

    def prepare(self, *, base_image, instance_id: str, base_commit: str, run_id: str | None = None):
        from coding_agent.models import BaseImage, TaskSandbox as _TaskSandbox
        name = _container_name(instance_id, run_id=run_id)
        self._docker.create_container(name=name, image=base_image.image)
        self._docker.start_container(name)
        self._docker.exec(name, ["git", "-C", base_image.repo_path, "checkout", base_commit])
        return _TaskSandbox(container_name=name, base_image=base_image, instance_id=instance_id, repo=base_image.repo, base_commit=base_commit, repo_path=base_image.repo_path, status="ready")

    def prepare_official_instance(self, *, repo: str, instance_id: str, base_commit: str, instance_image_key: str, repo_path: str, source_reference: str, run_id: str | None = None):
        from coding_agent.models import BaseImage as _BaseImage
        base_image = _BaseImage(repo=repo, image=instance_image_key, repo_path=repo_path, official_compatible=True, compatibility_source=source_reference)
        return self.prepare(base_image=base_image, instance_id=instance_id, base_commit=base_commit, run_id=run_id)

    def stop(self, sandbox) -> None:
        self._docker.stop_container(sandbox.container_name)
        self._docker.remove_container(sandbox.container_name)
