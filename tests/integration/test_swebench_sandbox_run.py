import json
from pathlib import Path

import pytest

from coding_agent.agent import ArtifactPersistenceError
from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend
from coding_agent.models import BaseImage, RunBudget
from coding_agent.sandbox.docker_cli import DockerResult
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.sandbox_run import (
    load_active_sandbox,
    prepare_swebench_sandbox,
    run_swebench_task,
    save_active_sandbox,
    solve_prepared_sandbox,
)


class FakeDocker:
    def __init__(self, *, fail_on_exec_after_start: bool = False) -> None:
        self.fail_on_exec_after_start = fail_on_exec_after_start
        self.calls: list[tuple] = []
        self.stdin_by_call: list[str | None] = []
        self.diff_output = (
            "diff --git a/README.md b/README.md\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

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
        self.stdin_by_call.append(stdin)
        if command[:4] == ["git", "-C", "/workspace/repo", "rev-parse"]:
            return DockerResult("abc123\n", "", 0)
        if command[:4] == ["git", "-C", "/workspace/repo", "status"]:
            return DockerResult("", "", 0)
        if command[:4] == ["git", "-C", "/workspace/repo", "diff"] and "--cached" not in command:
            return DockerResult(self.diff_output, "", 0)
        if "--collect-only" in " ".join(command):
            return DockerResult("", "", 0)
        if command[:3] == ["docker-ready-sentinel"]:
            return DockerResult("ready\n", "", 0)
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


def _task_record_with_test_patch() -> SwebenchTaskRecord:
    return SwebenchTaskRecord.from_row(
        {
            "instance_id": "django__django-11101",
            "repo": "django/django",
            "base_commit": "abc123",
            "problem_statement": "Read README.",
            "FAIL_TO_PASS": ["tests/test_issue.py::test_fix"],
            "PASS_TO_PASS": [],
            "test_patch": "diff --git a/tests/test_issue.py b/tests/test_issue.py\n",
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
        ("stop", sandbox["container_name"]),
        ("remove", sandbox["container_name"]),
    ]
    assert sandbox["container_name"].startswith("coding-agent-django__django-11099-")


def test_sandboxed_run_exports_container_patch_to_artifacts(tmp_path: Path):
    docker = FakeDocker()
    run_dir = tmp_path / "run"

    run_swebench_task(
        task_record=_task_record(),
        base_image=_base_image(),
        docker=docker,
        backend=MockBackend(
            [
                AgentAction(
                    action=AgentActionType.APPLY_PATCH,
                    tool_input={
                        "type": "update",
                        "path": "README.md",
                        "old_string": "old",
                        "new_string": "new",
                    },
                ),
                AgentAction(action=AgentActionType.FINAL, final_status="solved"),
            ]
        ),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=run_dir,
    )

    final_patch = (run_dir / "final.patch").read_text(encoding="utf-8")
    final_patch_bytes = (run_dir / "final.patch").read_bytes()
    prediction = json.loads((run_dir / "prediction.jsonl").read_text(encoding="utf-8"))
    trajectory_summary = json.loads((run_dir / "trajectory.json").read_text(encoding="utf-8"))

    assert final_patch == docker.diff_output
    assert b"\r" not in final_patch_bytes
    assert prediction["model_patch"] == docker.diff_output
    assert trajectory_summary["final_diff"] == docker.diff_output


def test_sandboxed_run_applies_test_patch_without_exporting_it(tmp_path: Path):
    docker = FakeDocker()
    run_dir = tmp_path / "run"

    run_swebench_task(
        task_record=_task_record_with_test_patch(),
        base_image=_base_image(),
        docker=docker,
        backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="solved")]),
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=run_dir,
    )

    commands = [call[2] for call in docker.calls if call[0] == "exec"]

    assert (
        "sh",
        "-lc",
        "tr -d '\\r' | git -C /workspace/repo apply --whitespace=nowarn -",
    ) in commands
    assert ("git", "-C", "/workspace/repo", "add", "-A") in commands
    assert ("git", "-C", "/workspace/repo", "diff", "--binary") in commands
    assert ("git", "-C", "/workspace/repo", "diff", "--binary", "HEAD") not in commands
    assert "diff --git a/tests/test_issue.py b/tests/test_issue.py\n" in docker.stdin_by_call
    assert (run_dir / "final.patch").read_text(encoding="utf-8") == docker.diff_output


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


def test_sandboxed_run_cleans_up_after_artifact_persistence_error(tmp_path: Path, monkeypatch):
    docker = FakeDocker()

    def fake_run_task(**kwargs):
        raise ArtifactPersistenceError("disk full")

    monkeypatch.setattr("coding_agent.swebench.sandbox_run.run_task", fake_run_task)

    with pytest.raises(ArtifactPersistenceError, match="disk full"):
        run_swebench_task(
            task_record=_task_record(),
            base_image=_base_image(),
            docker=docker,
            backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="incomplete")]),
            budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
            model_name="mock-model",
            output_dir=tmp_path / "run",
        )

    container_name = next(call[1] for call in docker.calls if call[0] == "create")
    assert docker.calls[-2:] == [
        ("stop", container_name),
        ("remove", container_name),
    ]


def test_active_sandbox_index_save_load_and_duplicate_policy(tmp_path: Path):
    sandbox = prepare_swebench_sandbox(
        task_record=_task_record_with_test_patch(),
        base_image=_base_image(),
        docker=FakeDocker(),
        output_dir=tmp_path / "prepared",
    ).sandbox
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    sandbox_json_path = tmp_path / "prepared" / "sandbox.json"

    save_active_sandbox(index_path, sandbox, sandbox_json_path)

    loaded = load_active_sandbox(index_path, sandbox.instance_id)
    assert loaded.container_name == sandbox.container_name
    assert loaded.base_commit == "abc123"

    with pytest.raises(ValueError, match="already has an active sandbox"):
        save_active_sandbox(index_path, sandbox, sandbox_json_path)

    save_active_sandbox(index_path, sandbox, sandbox_json_path, replace_existing=True)


def test_prepare_sandbox_stages_test_patch_writes_ready_artifacts_and_keeps_container(tmp_path: Path):
    docker = FakeDocker()

    prepared = prepare_swebench_sandbox(
        task_record=_task_record_with_test_patch(),
        base_image=_base_image(),
        docker=docker,
        output_dir=tmp_path / "prepared",
    )

    sandbox_json = json.loads((tmp_path / "prepared" / "sandbox.json").read_text(encoding="utf-8"))
    commands = [call[2] for call in docker.calls if call[0] == "exec"]

    assert prepared.status == "ready"
    assert sandbox_json["status"] == "ready"
    assert sandbox_json["test_patch_applied"] is True
    assert sandbox_json["test_patch_staged"] is True
    assert sandbox_json["ready_checks"]["head_match"]["ok"] is True
    assert (
        "sh",
        "-lc",
        "tr -d '\\r' | git -C /workspace/repo apply --whitespace=nowarn -",
    ) in commands
    assert ("git", "-C", "/workspace/repo", "add", "-A") in commands
    assert not any(call[0] in {"stop", "remove"} for call in docker.calls)


def test_prepare_sandbox_rejects_duplicate_active_index_before_create(tmp_path: Path):
    docker = FakeDocker()
    prepared = prepare_swebench_sandbox(
        task_record=_task_record(),
        base_image=_base_image(),
        docker=docker,
        output_dir=tmp_path / "prepared",
        active_index_path=tmp_path / ".coding-agent" / "active-sandboxes.json",
    )
    docker.calls.clear()

    with pytest.raises(ValueError, match="already has an active sandbox"):
        prepare_swebench_sandbox(
            task_record=_task_record(),
            base_image=_base_image(),
            docker=docker,
            output_dir=tmp_path / "prepared-2",
            active_index_path=tmp_path / ".coding-agent" / "active-sandboxes.json",
        )

    assert prepared.sandbox.instance_id == _task_record().instance_id
    assert not any(call[0] == "create" for call in docker.calls)


def test_solve_prepared_sandbox_reuses_active_container_and_keeps_it_by_default(tmp_path: Path):
    docker = FakeDocker()
    prepared = prepare_swebench_sandbox(
        task_record=_task_record_with_test_patch(),
        base_image=_base_image(),
        docker=docker,
        output_dir=tmp_path / "prepared",
    )
    docker.calls.clear()
    docker.stdin_by_call.clear()

    solve_prepared_sandbox(
        task_record=_task_record_with_test_patch(),
        sandbox=prepared.sandbox,
        docker=docker,
        backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="solved")]),
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "solve",
    )

    commands = [call[2] for call in docker.calls if call[0] == "exec"]
    assert not any(call[0] in {"create", "start", "stop", "remove"} for call in docker.calls)
    assert ("git", "-C", "/workspace/repo", "checkout", "abc123") not in commands
    assert ("git", "-C", "/workspace/repo", "add", "-A") not in commands
    assert ("git", "-C", "/workspace/repo", "diff", "--binary") in commands
    assert (tmp_path / "solve" / "final.patch").read_text(encoding="utf-8") == docker.diff_output


def test_solve_prepared_sandbox_cleanup_removes_container(tmp_path: Path):
    docker = FakeDocker()
    prepared = prepare_swebench_sandbox(
        task_record=_task_record(),
        base_image=_base_image(),
        docker=docker,
        output_dir=tmp_path / "prepared",
    )
    docker.calls.clear()

    solve_prepared_sandbox(
        task_record=_task_record(),
        sandbox=prepared.sandbox,
        docker=docker,
        backend=MockBackend([AgentAction(action=AgentActionType.FINAL, final_status="incomplete")]),
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "solve",
        cleanup=True,
    )

    assert docker.calls[-2:] == [
        ("stop", prepared.sandbox.container_name),
        ("remove", prepared.sandbox.container_name),
    ]
