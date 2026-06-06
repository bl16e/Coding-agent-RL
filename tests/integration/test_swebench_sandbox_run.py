import json
from pathlib import Path

from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend
from coding_agent.models import BaseImage, RunBudget
from coding_agent.sandbox.docker_cli import DockerResult
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.sandbox_run import run_swebench_task


class FakeDocker:
    def __init__(self, *, fail_on_exec_after_start: bool = False) -> None:
        self.fail_on_exec_after_start = fail_on_exec_after_start
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
        if command[:3] == ["git", "-C", "/workspace/repo"]:
            return DockerResult("", "", 0)
        if self.fail_on_exec_after_start:
            raise RuntimeError("container disappeared")
        if "read_text" in " ".join(command):
            return DockerResult("hello\n", "", 0)
        return DockerResult("", "", 0)


def _task_record() -> SwebenchTaskRecord:
    return SwebenchTaskRecord.from_row(
        {
            "instance_id": "django__django-11099",
            "repo": "django/django",
            "base_commit": "abc123",
            "problem_statement": "Read README.",
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


def test_sandboxed_run_writes_standard_artifacts_and_sandbox_metadata(tmp_path: Path):
    docker = FakeDocker()
    summary = run_swebench_task(
        task_record=_task_record(),
        base_image=_base_image(),
        docker=docker,
        backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="incomplete")]),
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    run_dir = tmp_path / "run"
    sandbox = json.loads((run_dir / "sandbox.json").read_text(encoding="utf-8"))
    summary_json = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert summary.instance_id == "django__django-11099"
    assert (run_dir / "trajectory.jsonl").is_file()
    assert (run_dir / "final.patch").is_file()
    assert (run_dir / "prediction.jsonl").is_file()
    assert sandbox["base_image"]["official_compatible"] is True
    assert sandbox["validation"]["command_source"] == "registered_template"
    assert summary_json["sandbox"]["task_sandbox"]["base_commit"] == "abc123"
    assert docker.calls[-2:] == [
        ("stop", "coding-agent-django__django-11099"),
        ("remove", "coding-agent-django__django-11099"),
    ]


def test_sandboxed_run_preserves_partial_artifacts_after_post_start_runtime_failure(tmp_path: Path):
    exit_summary = run_swebench_task(
        task_record=_task_record(),
        base_image=_base_image(),
        docker=FakeDocker(fail_on_exec_after_start=True),
        backend=MockBackend(
            [
                AgentAction(
                    action=AgentActionType.READ_FILE,
                    tool_input={"path": "README.md"},
                    reasoning_summary="Need file",
                )
            ]
        ),
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    run_dir = tmp_path / "run"
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    sandbox = json.loads((run_dir / "sandbox.json").read_text(encoding="utf-8"))

    assert exit_summary.error == "container disappeared"
    assert (run_dir / "trajectory.jsonl").read_text(encoding="utf-8").strip()
    assert (run_dir / "final.patch").is_file()
    assert (run_dir / "prediction.jsonl").is_file()
    assert summary["status"] == "errored"
    assert sandbox["status"] == "error"
