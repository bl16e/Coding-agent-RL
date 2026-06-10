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

    def stop_container(self, name: str) -> DockerResult:
        self.calls.append(("stop", (name,)))
        return DockerResult("", "", 0)

    def remove_container(self, name: str) -> DockerResult:
        self.calls.append(("remove", (name,)))
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


def test_stop_removes_task_container_name_for_next_run():
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

    manager.stop(sandbox)

    assert docker.calls[-2:] == [
        ("stop", (sandbox.container_name,)),
        ("remove", (sandbox.container_name,)),
    ]


def test_prepare_appends_short_run_id_to_container_name():
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
        run_id="12345678-90ab-cdef-1234-567890abcdef",
    )

    assert sandbox.container_name == "coding-agent-django__django-11099-12345678"
