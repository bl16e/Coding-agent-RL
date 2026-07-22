import subprocess

import pytest

from coding_agent.sandbox_manager import DockerCli, DockerCommandError, DockerCommandTimeout, DockerResult


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


def test_docker_cli_sends_stdin_as_utf8_bytes():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b"ok\n", b"")

    cli = DockerCli(runner=runner)

    result = cli.run(["exec", "-i", "container", "cat"], stdin="Ўъ\n")

    assert result.stdout == "ok\n"
    assert calls[0][1]["input"] == "Ўъ\n".encode("utf-8")
    assert calls[0][1]["text"] is False


def test_docker_cli_inspect_helpers_return_booleans():
    seen = []

    def runner(command, **kwargs):
        seen.append(command)
        code = 0 if "present:latest" in command or "container-1" in command else 1
        detail = (
            "Error response from daemon: No such image: missing:latest"
            if "image" in command
            else "Error response from daemon: No such container: missing-container"
        )
        return subprocess.CompletedProcess(command, code, "", detail)

    cli = DockerCli(runner=runner)

    assert cli.image_exists("present:latest") is True
    assert cli.image_exists("missing:latest") is False
    assert cli.container_exists("container-1") is True


def test_docker_cli_image_exists_raises_for_docker_access_errors():
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "permission denied while trying to connect to the docker API at npipe:////./pipe/docker_engine",
        )

    cli = DockerCli(runner=runner)

    with pytest.raises(DockerCommandError, match="permission denied"):
        cli.image_exists("present:latest")


def test_docker_cli_image_exists_returns_false_only_for_missing_images():
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "Error response from daemon: No such image: missing:latest",
        )

    cli = DockerCli(runner=runner)

    assert cli.image_exists("missing:latest") is False


def test_docker_cli_exec_can_set_workdir():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    cli = DockerCli(runner=runner)

    cli.exec("container", ["python", "-c", "print('ok')"], workdir="/testbed")

    assert calls[0] == [
        "docker",
        "exec",
        "-i",
        "-w",
        "/testbed",
        "container",
        "python",
        "-c",
        "print('ok')",
    ]
