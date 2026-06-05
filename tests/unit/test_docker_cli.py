import subprocess

import pytest

from coding_agent.sandbox.docker_cli import DockerCli, DockerCommandError, DockerCommandTimeout, DockerResult


def test_docker_cli_returns_stdout_for_successful_command():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    cli = DockerCli(runner=runner)

    result = cli.run(["image", "inspect", "example:latest"], timeout_seconds=5)

    assert result == DockerResult(stdout="ok\n", stderr="", returncode=0)
    assert calls[0][0] == ["docker", "image", "inspect", "example:latest"]


def test_docker_cli_maps_nonzero_exit_to_error():
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "not found")

    cli = DockerCli(runner=runner)

    with pytest.raises(DockerCommandError, match="not found"):
        cli.run(["image", "inspect", "missing:latest"])


def test_docker_cli_maps_timeout_to_timeout_error():
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1, output="partial", stderr="slow")

    cli = DockerCli(runner=runner)

    with pytest.raises(DockerCommandTimeout, match="timed out"):
        cli.run(["exec", "container", "pytest"], timeout_seconds=1)


def test_docker_cli_inspect_helpers_return_booleans():
    seen = []

    def runner(command, **kwargs):
        seen.append(command)
        code = 0 if "present:latest" in command or "container-1" in command else 1
        return subprocess.CompletedProcess(command, code, "", "missing")

    cli = DockerCli(runner=runner)

    assert cli.image_exists("present:latest") is True
    assert cli.image_exists("missing:latest") is False
    assert cli.container_exists("container-1") is True
