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
