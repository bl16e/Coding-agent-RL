from pathlib import Path

from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend
from coding_agent.models import BaseImage, RunBudget
from coding_agent.sandbox.docker_cli import DockerResult
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.sandbox_run import run_swebench_task


class RecordingDocker:
    def __init__(self) -> None:
        self.checkouts: list[str] = []
        self.images: list[str] = []
        self.current_commit_by_container: dict[str, str] = {}

    def create_container(self, *, name: str, image: str) -> DockerResult:
        self.images.append(image)
        return DockerResult("", "", 0)

    def start_container(self, name: str) -> DockerResult:
        return DockerResult("", "", 0)

    def stop_container(self, name: str) -> DockerResult:
        return DockerResult("", "", 0)

    def remove_container(self, name: str) -> DockerResult:
        return DockerResult("", "", 0)

    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None) -> DockerResult:
        if command[:4] == ["git", "-C", "/workspace/repo", "rev-parse"] and command[-1] == "HEAD":
            return DockerResult(self.current_commit_by_container.get(container, ""), "", 0)
        if command[:4] == ["git", "-C", "/workspace/repo", "checkout"]:
            self.checkouts.append(command[-1])
            self.current_commit_by_container[container] = command[-1]
        return DockerResult("", "", 0)


def _record(instance_id: str, base_commit: str) -> SwebenchTaskRecord:
    return SwebenchTaskRecord.from_row(
        {
            "instance_id": instance_id,
            "repo": "django/django",
            "base_commit": base_commit,
            "problem_statement": "Fix it.",
            "FAIL_TO_PASS": ["tests/test_issue.py::test_fix"],
            "PASS_TO_PASS": [],
        }
    )


def test_one_repository_base_image_supports_two_task_runs_with_different_checkouts(tmp_path: Path):
    docker = RecordingDocker()
    base_image = BaseImage(
        repo="django/django",
        image="django-base:latest",
        repo_path="/workspace/repo",
        official_compatible=True,
        validation_command_template="python -m pytest {tests}",
    )

    for instance_id, commit in (("django__django-1", "abc123"), ("django__django-2", "def456")):
        run_swebench_task(
            task_record=_record(instance_id, commit),
            base_image=base_image,
            docker=docker,
            backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="incomplete")]),
            budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
            model_name="mock-model",
            output_dir=tmp_path / instance_id,
        )

    assert docker.images == ["django-base:latest", "django-base:latest"]
    assert docker.checkouts == ["abc123", "def456"]
