import json
from pathlib import Path

from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend
from coding_agent.models import BaseImage, RunBudget
from coding_agent.sandbox.docker_cli import DockerResult
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.sandbox_run import SandboxedRunInputError, run_swebench_task


class RecordingDocker:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def create_container(self, *, name: str, image: str) -> DockerResult:
        return DockerResult("", "", 0)

    def start_container(self, name: str) -> DockerResult:
        return DockerResult("", "", 0)

    def stop_container(self, name: str) -> DockerResult:
        return DockerResult("", "", 0)

    def remove_container(self, name: str) -> DockerResult:
        return DockerResult("", "", 0)

    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None) -> DockerResult:
        self.commands.append(tuple(command))
        return DockerResult("ok", "", 0)


def _task(**overrides) -> SwebenchTaskRecord:
    row = {
        "instance_id": "django__django-1",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "Run validation.",
        "FAIL_TO_PASS": ["tests/test_issue.py::test_fix"],
        "PASS_TO_PASS": ["tests/test_regression.py::test_old"],
    }
    row.update(overrides)
    return SwebenchTaskRecord.from_row(row)


def _base_image(template: str | None = "python -m pytest {tests}") -> BaseImage:
    return BaseImage(
        repo="django/django",
        image="django-base:latest",
        repo_path="/workspace/repo",
        official_compatible=True,
        validation_command_template=template,
    )


def test_rejected_container_test_command_is_recorded_in_trajectory(tmp_path: Path):
    run_swebench_task(
        task_record=_task(),
        base_image=_base_image(),
        docker=RecordingDocker(),
        backend=MockBackend(
            [
                AgentAction(
                    action=AgentActionType.RUN_TESTS,
                    tool_input={"command": "python -m pytest"},
                    reasoning_summary="Try broad tests",
                )
            ]
        ),
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    lines = (tmp_path / "run" / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
    rejected = [json.loads(line) for line in lines if "command is not allowed" in line]
    assert rejected
    assert rejected[0]["outcome"] == "rejected"


def test_missing_validation_command_source_fails_before_model_execution(tmp_path: Path):
    try:
        run_swebench_task(
            task_record=_task(),
            base_image=_base_image(template=None),
            docker=RecordingDocker(),
            backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="incomplete")]),
            budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
            model_name="mock-model",
            output_dir=tmp_path / "run",
        )
    except SandboxedRunInputError as exc:
        assert "validation command source" in str(exc)
    else:
        raise AssertionError("expected SandboxedRunInputError")

    assert not (tmp_path / "run" / "trajectory.jsonl").exists()
