from coding_agent.models import BaseImage
from coding_agent.sandbox.manager import TaskSandboxManager
from coding_agent.sandbox.docker_cli import DockerResult


class RecordingDocker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def create_container(self, *, name: str, image: str) -> DockerResult:
        self.calls.append(("create", (name, image)))
        return DockerResult("", "", 0)

    def start_container(self, name: str) -> DockerResult:
        self.calls.append(("start", (name,)))
        return DockerResult("", "", 0)

    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None) -> DockerResult:
        self.calls.append(("exec", (container, tuple(command), timeout_seconds, stdin)))
        return DockerResult("", "", 0)


def test_prepare_task_sandbox_checks_out_base_commit_before_ready():
    docker = RecordingDocker()
    manager = TaskSandboxManager(docker=docker)
    base_image = BaseImage(
        repo="django/django",
        image="django-base:latest",
        repo_path="/workspace/repo",
        official_compatible=True,
    )

    sandbox = manager.prepare(
        base_image=base_image,
        instance_id="django__django-11099",
        base_commit="abc123",
    )

    assert sandbox.status == "ready"
    assert docker.calls[:3] == [
        ("create", (sandbox.container_name, "django-base:latest")),
        ("start", (sandbox.container_name,)),
        (
            "exec",
            (
                sandbox.container_name,
                ("git", "-C", "/workspace/repo", "checkout", "abc123"),
                None,
                None,
            ),
        ),
    ]
