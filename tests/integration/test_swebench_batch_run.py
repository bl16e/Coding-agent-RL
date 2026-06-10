import json
from pathlib import Path

import pytest

from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend
from coding_agent.models import BaseImage, RunBudget
from coding_agent.sandbox.docker_cli import DockerResult
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.sandbox_run import SandboxedRunInputError, run_swebench_tasks


class FakeDocker:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_container(self, *, name: str, image: str) -> DockerResult:
        self.calls.append(("create", name, image))
        return DockerResult("", "", 0)

    def start_container(self, name: str) -> DockerResult:
        self.calls.append(("start", name))
        return DockerResult("", "", 0)

    def stop_container(self, name: str) -> DockerResult:
        self.calls.append(("stop", name))
        return DockerResult("", "", 0)

    def remove_container(self, name: str) -> DockerResult:
        self.calls.append(("remove", name))
        return DockerResult("", "", 0)

    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None) -> DockerResult:
        self.calls.append(("exec", container, tuple(command)))
        return DockerResult("", "", 0)


def _task_record(instance_id: str, base_commit: str) -> SwebenchTaskRecord:
    return SwebenchTaskRecord.from_row(
        {
            "instance_id": instance_id,
            "repo": "django/django",
            "base_commit": base_commit,
            "problem_statement": f"Fix {instance_id}.",
            "FAIL_TO_PASS": ["tests/test_issue.py::test_fix"],
            "PASS_TO_PASS": [],
        }
    )


def _base_image() -> BaseImage:
    return BaseImage(
        repo="django/django",
        image="django-base:latest",
        repo_path="/workspace/repo",
        official_compatible=True,
        validation_command_template="python -m pytest {tests}",
    )


def _backend_factory():
    return MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="incomplete")])


def test_batch_run_writes_per_instance_artifacts_and_aggregate_outputs(tmp_path: Path):
    docker = FakeDocker()
    output_dir = tmp_path / "batch"

    exit_code = run_swebench_tasks(
        task_records=[
            _task_record("django__django-11099", "abc123"),
            _task_record("django__django-11100", "def456"),
        ],
        base_images={"django/django": _base_image()},
        docker=docker,
        backend_factory=_backend_factory,
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=output_dir,
        jobs=2,
    )

    assert exit_code == 0
    assert (output_dir / "django__django-11099" / "summary.json").is_file()
    assert (output_dir / "django__django-11100" / "summary.json").is_file()
    assert (output_dir / "batch_summary.json").is_file()
    prediction_lines = (output_dir / "prediction.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(prediction_lines) == 2
    assert [json.loads(line)["instance_id"] for line in prediction_lines] == [
        "django__django-11099",
        "django__django-11100",
    ]
    summary = json.loads((output_dir / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["total"] == 2
    assert summary["statuses"]["incomplete"] == 2

    created_names = [call[1] for call in docker.calls if call[0] == "create"]
    assert len(created_names) == 2
    assert len(set(created_names)) == 2
    assert all(name.startswith("coding-agent-django__django-") for name in created_names)


def test_batch_run_rejects_duplicate_direct_task_records_before_starting_sandboxes(tmp_path: Path):
    docker = FakeDocker()

    with pytest.raises(SandboxedRunInputError, match="duplicate"):
        run_swebench_tasks(
            task_records=[
                _task_record("django__django-11099", "abc123"),
                _task_record("django__django-11099", "abc123"),
            ],
            base_images={"django/django": _base_image()},
            docker=docker,
            backend_factory=_backend_factory,
            budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
            model_name="mock-model",
            output_dir=tmp_path / "batch",
            jobs=2,
        )

    assert docker.calls == []
