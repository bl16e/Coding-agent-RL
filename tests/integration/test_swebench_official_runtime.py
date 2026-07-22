"""Integration tests for official-style SWE-Bench prepare/run orchestration."""

import json
import logging
from pathlib import Path

import pytest

from coding_agent.model_backend import AgentAction, AgentActionType
from coding_agent.legacy_mock_backend import MockBackend
from coding_agent.models import RunBudget
from coding_agent.sandbox_manager import DockerCommandError
from coding_agent.sandbox_manager import DockerResult
from coding_agent.swebench import sandbox_run
from coding_agent.swebench.sandbox_run import (
    SandboxedRunInputError,
    prepare_official_swebench_runtime,
)
from tests.helpers.swebench_fixtures import write_swebench_parquet
from tests.helpers.swebench_fixtures import swebench_row
from tests.unit.fakes.test_swebench_runtime_fakes import FakeOfficialRuntimeDocker


PRESENT_IMAGES = {
    "sweb.base.py.x86_64:latest",
    "sweb.env.py.x86_64.2baaea72acc974f6c02079:latest",
    "sweb.eval.x86_64.django__django-11099:latest",
}

def test_prepare_official_runtime_writes_ready_metadata_and_active_index(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FakeOfficialRuntimeDocker(present_images=set(PRESENT_IMAGES))

    prepared = prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=tmp_path / ".coding-agent" / "active-sandboxes.json",
    )

    sandbox = json.loads((tmp_path / "prepare" / "sandbox.json").read_text(encoding="utf-8"))
    active = json.loads((tmp_path / ".coding-agent" / "active-sandboxes.json").read_text(encoding="utf-8"))

    assert prepared.status.value == "ready"
    assert sandbox["runtime_path"] == "official_style"
    assert sandbox["repo"] == "django/django"
    assert sandbox["version"] == "3.0"
    assert sandbox["runtime"]["base_image_key"] == "sweb.base.py.x86_64:latest"
    assert sandbox["runtime"]["env_image_key"] == "sweb.env.py.x86_64.2baaea72acc974f6c02079:latest"
    assert sandbox["runtime"]["instance_image_key"] == "sweb.eval.x86_64.django__django-11099:latest"
    assert active["prepared_environments"]["django__django-11099"]["status"] == "ready"
    assert not any(call[0] == "build_image" for call in docker.calls)


def test_prepare_official_runtime_logs_progress(tmp_path: Path, caplog):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FakeOfficialRuntimeDocker(present_images=set(PRESENT_IMAGES))

    with caplog.at_level(logging.INFO):
        prepare_official_swebench_runtime(
            dataset_path=dataset,
            instance_id="django__django-11099",
            docker=docker,
            output_dir=tmp_path / "prepare",
            active_index_path=tmp_path / ".coding-agent" / "active-sandboxes.json",
        )

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "official runtime prepare started" in log_text
    assert "runtime image graph resolved" in log_text
    assert "prepared environment ready checks completed" in log_text
    assert "official runtime prepare completed" in log_text


def test_prepare_official_runtime_rejects_duplicate_active_entry_before_container_create(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "prepared_environments": {
                    "django__django-11099": {
                        "status": "ready",
                        "container_name": "old-container",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    docker = FakeOfficialRuntimeDocker(present_images=set(PRESENT_IMAGES))

    import pytest

    with pytest.raises(ValueError, match="already has an active prepared environment"):
        prepare_official_swebench_runtime(
            dataset_path=dataset,
            instance_id="django__django-11099",
            docker=docker,
            output_dir=tmp_path / "prepare",
            active_index_path=index_path,
        )

    assert not any(call[0] == "create" for call in docker.calls)


def test_prepare_fails_when_workspace_is_dirty(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FakeOfficialRuntimeDocker(
        present_images=set(PRESENT_IMAGES),
        exec_results={
            ("git", "-C", "/testbed", "status", "--porcelain"): DockerResult("M app.py\n", "", 0),
        },
    )

    with pytest.raises(SandboxedRunInputError, match="workspace is not clean"):
        prepare_official_swebench_runtime(
            dataset_path=dataset,
            instance_id="django__django-11099",
            docker=docker,
            output_dir=tmp_path / "prepare",
            active_index_path=tmp_path / ".coding-agent" / "active-sandboxes.json",
        )

    assert not (tmp_path / ".coding-agent" / "active-sandboxes.json").exists()


def test_run_prepared_official_runtime_writes_artifacts_and_review_metadata(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = EvalRecordingDocker(
        present_images=set(PRESENT_IMAGES),
        diff_output="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    assert hasattr(sandbox_run, "run_prepared_swebench_runtime")
    summary = sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend([]),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    run_dir = tmp_path / "run"
    sandbox = json.loads((run_dir / "sandbox.json").read_text(encoding="utf-8"))
    summary_payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    prediction = json.loads((run_dir / "prediction.jsonl").read_text(encoding="utf-8").splitlines()[0])
    active = json.loads(index_path.read_text(encoding="utf-8"))

    assert summary.status.value == "solved"
    for name in ("trajectory.jsonl", "trajectory.json", "summary.json", "final.patch", "prediction.jsonl", "sandbox.json"):
        assert (run_dir / name).is_file()
    assert prediction["model_patch"].startswith("diff --git")
    assert summary_payload["runtime"]["path"] == "official_style"
    assert summary_payload["prepared_environment"]["status_transition"] == ["ready", "running", "used"]
    assert summary_payload["validation"]["mode"] == "fail_to_pass"
    assert summary_payload["self_test_coverage"]["existing_tests"]["passed"] == 0
    assert summary_payload["artifacts"]["sandbox"].endswith("sandbox.json")
    assert sandbox["runtime"]["instance_image_key"] == "sweb.eval.x86_64.django__django-11099:latest"
    assert sandbox["prepared_environment"]["status_transition"] == ["ready", "running", "used"]
    assert active["prepared_environments"]["django__django-11099"]["status"] == "used"
    assert not any(call[0] == "build_image" for call in docker.calls)


def test_run_fails_before_agent_when_container_is_not_running(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FakeOfficialRuntimeDocker(present_images=set(PRESENT_IMAGES))
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )
    assert docker.running_containers is not None
    docker.running_containers.clear()

    with pytest.raises(SandboxedRunInputError, match="container is not ready"):
        sandbox_run.run_prepared_swebench_runtime(
            dataset_path=dataset,
            instance_id="django__django-11099",
            docker=docker,
            backend=MockBackend([]),
            budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
            model_name="mock-model",
            output_dir=tmp_path / "run",
            active_index_path=index_path,
        )

    assert not (tmp_path / "run" / "trajectory.jsonl").exists()


class EvalRecordingDocker(FakeOfficialRuntimeDocker):
    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None):
        self.calls.append(("exec", (container, tuple(command), timeout_seconds)))
        self.stdin_by_call.append(stdin)
        if command[:2] == ["git", "-C"] and "diff" in command:
            return DockerResult(
                self.diff_output,
                "",
                0,
            )
        if command[:2] == ["bash", "-lc"]:
            return DockerResult(
                "\n".join(
                    [
                        "setup text",
                        ">>>>> Start Test Output",
                        "tests/test_issue.py::test_fix PASSED",
                        "tests/test_regression.py::test_old PASSED",
                        ">>>>> End Test Output"
                    ]
                ),
                "",
                0,
            )
        self.calls.pop()
        self.stdin_by_call.pop()
        return super().exec(container, command, timeout_seconds=timeout_seconds, stdin=stdin)


def test_run_executes_final_eval_and_excludes_validation_patch_from_final_diff(tmp_path: Path):
    dataset = write_swebench_parquet(
        tmp_path / "dataset.parquet",
        rows=[
            swebench_row(
                PASS_TO_PASS=["tests/test_regression.py::test_old"],
                eval_script="python -m pytest {tests}",
                test_patch="\n".join(
                    [
                        "diff --git a/tests/test_issue.py b/tests/test_issue.py",
                        "--- a/tests/test_issue.py",
                        "+++ b/tests/test_issue.py",
                        "@@ -1 +1 @@",
                        "-old test",
                        "+new test",
                        ""
                    ]
                ),
            )
        ],
    )
    docker = EvalRecordingDocker(
        present_images=set(PRESENT_IMAGES),
        diff_output="\n".join(
            [
                "diff --git a/app.py b/app.py",
                "--- a/app.py",
                "+++ b/app.py",
                "@@ -1 +1 @@",
                "-old",
                "+new",
                "diff --git a/tests/test_issue.py b/tests/test_issue.py",
                "--- a/tests/test_issue.py",
                "+++ b/tests/test_issue.py",
                "@@ -1 +1 @@",
                "-old test",
                "+new test",
                ""
            ]
        ),
    )
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend([]),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
        include_pass_to_pass=True,
    )

    run_dir = tmp_path / "run"
    summary_payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    sandbox_payload = json.loads((run_dir / "sandbox.json").read_text(encoding="utf-8"))
    final_patch = (run_dir / "final.patch").read_text(encoding="utf-8")

    assert (run_dir / "eval.log").is_file()
    assert "tests/test_issue.py" not in final_patch
    assert "diff --git a/app.py b/app.py" in final_patch
    assert summary_payload["validation"]["mode"] == "fail_to_pass_plus_pass_to_pass"
    assert summary_payload["validation"]["eval_report"]["resolved"] is True
    assert sandbox_payload["validation"]["eval_report"]["pass_to_pass_success"] == ["tests/test_regression.py::test_old"]
    assert not any(call[0] == "exec" and "git -C /testbed apply --whitespace=nowarn -" in call[1][1][-1] for call in docker.calls)
    assert not any(call[0] == "exec" and "git -C /testbed apply -R --whitespace=nowarn -" in call[1][1][-1] for call in docker.calls)
    assert any(call[0] == "exec" and call[1][1][:2] == ("bash", "-lc") for call in docker.calls)
    assert not any(call[0] == "exec" and call[1][1][:2] == ("sh", "-lc") and "pytest" in call[1][1][-1] for call in docker.calls)


class OfficialEvalScriptDocker(EvalRecordingDocker):
    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None):
        if command[:2] == ["sh", "-lc"] and command[-1].startswith("git -C /testbed apply"):
            raise AssertionError("official eval_script already applies and reverts test_patch")
        return super().exec(container, command, timeout_seconds=timeout_seconds, stdin=stdin)


class PromptCapturingBackend:
    def __init__(self) -> None:
        self.first_messages = None

    def next_action(self, messages):
        if self.first_messages is None:
            self.first_messages = messages
        return 


def test_official_eval_script_is_not_visible_to_agent_prompt(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = EvalRecordingDocker(present_images=set(PRESENT_IMAGES))
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )
    backend = PromptCapturingBackend()

    sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=backend,
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    prompt = backend.first_messages[0]["content"]
    assert "git apply" not in prompt
    assert "EOF_" not in prompt
    assert "Final benchmark validation is run automatically" in prompt
    assert "python -c" in prompt


def test_final_eval_does_not_apply_test_patch_outside_official_eval_script(tmp_path: Path):
    dataset = write_swebench_parquet(
        tmp_path / "dataset.parquet",
        rows=[
            swebench_row(
                eval_script="\n".join(
                    [
                        "set -euxo pipefail",
                        "cd /testbed",
                        "git apply -v - <<'EOF_PATCH'",
                        "diff --git a/tests/test_issue.py b/tests/test_issue.py",
                        "--- a/tests/test_issue.py",
                        "+++ b/tests/test_issue.py",
                        "@@ -1 +1 @@",
                        "-old test",
                        "+new test",
                        "EOF_PATCH",
                        "python -m pytest tests/test_issue.py::test_fix",
                        "git checkout abc123 tests/test_issue.py"
                    ]
                ),
                test_patch="\n".join(
                    [
                        "diff --git a/tests/test_issue.py b/tests/test_issue.py",
                        "--- a/tests/test_issue.py",
                        "+++ b/tests/test_issue.py",
                        "@@ -1 +1 @@",
                        "-old test",
                        "+new test",
                        ""
                    ]
                ),
            )
        ],
    )
    docker = OfficialEvalScriptDocker(
        present_images=set(PRESENT_IMAGES),
        diff_output="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend([]),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    assert (tmp_path / "run" / "final.patch").read_text(encoding="utf-8").startswith("diff --git")


def test_official_eval_resolution_overrides_agent_incomplete_status(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = EvalRecordingDocker(
        present_images=set(PRESENT_IMAGES),
        diff_output="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    summary = sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend(
            [
                AgentAction(action=AgentActionType.RUN_TESTS, tool_input={"command": "not allowed"}),
                
            ]
        ),
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    summary_payload = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary.status.value == "solved"
    assert summary_payload["status"] == "solved"
    assert summary_payload["agent_status"] == "incomplete"
    assert "unresolved tool failure" in summary_payload["agent_error"]
    assert summary_payload["validation"]["eval_report"]["resolved"] is True


class FailingEvalDocker(EvalRecordingDocker):
    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None):
        if command[:2] == ["bash", "-lc"]:
            return DockerResult(
                "\n".join(
                    [
                        ">>>>> Start Test Output",
                        "tests/test_issue.py::test_fix FAILED",
                        ">>>>> End Test Output"
                    ]
                ),
                "",
                0,
            )
        return super().exec(container, command, timeout_seconds=timeout_seconds, stdin=stdin)


class RaisingFailingEvalDocker(EvalRecordingDocker):
    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None):
        if command[:2] == ["bash", "-lc"]:
            raise DockerCommandError(
                ["exec", container, *command],
                DockerResult(
                    "\n".join(
                        [
                            ">>>>> Start Test Output",
                            "tests/test_issue.py::test_fix FAILED",
                            ">>>>> End Test Output",
                        ]
                    ),
                    "",
                    1,
                ),
            )
        return super().exec(container, command, timeout_seconds=timeout_seconds, stdin=stdin)


def test_agent_solved_does_not_override_failed_official_eval(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FailingEvalDocker(
        present_images=set(PRESENT_IMAGES),
        diff_output="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend([]),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    payload = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert payload["status"] != "solved"
    assert payload["agent_status"] == "solved"
    assert payload["validation"]["eval_report"]["resolved"] is False


def test_official_eval_command_error_still_overrides_agent_solved_summary(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = RaisingFailingEvalDocker(
        present_images=set(PRESENT_IMAGES),
        diff_output="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    summary = sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend([]),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
    )

    payload = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    eval_log = (tmp_path / "run" / "eval.log").read_text(encoding="utf-8")
    assert summary.status.value == "incomplete"
    assert payload["status"] == "incomplete"
    assert payload["agent_status"] == "solved"
    assert payload["validation"]["eval_report"]["resolved"] is False
    assert "tests/test_issue.py::test_fix FAILED" in eval_log


def test_prepare_then_run_with_cleanup_removes_active_index_entry(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FakeOfficialRuntimeDocker(present_images=set(PRESENT_IMAGES))
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )

    assert hasattr(sandbox_run, "run_prepared_swebench_runtime")
    sandbox_run.run_prepared_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        backend=MockBackend([]),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
        cleanup=True,
    )

    active = json.loads(index_path.read_text(encoding="utf-8"))
    sandbox = json.loads((tmp_path / "run" / "sandbox.json").read_text(encoding="utf-8"))

    assert "django__django-11099" not in active["prepared_environments"]
    assert sandbox["cleanup"]["requested"] is True
    assert sandbox["cleanup"]["active_index_result"] == "removed"
    assert any(call[0] == "stop" for call in docker.calls)
    assert any(call[0] == "remove" for call in docker.calls)


@pytest.mark.parametrize("status", ["used", "stopped", "error", "running"])
def test_run_rejects_non_ready_active_prepared_environment_before_agent_start(tmp_path: Path, status: str):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    docker = FakeOfficialRuntimeDocker(present_images=set(PRESENT_IMAGES))
    prepare_official_swebench_runtime(
        dataset_path=dataset,
        instance_id="django__django-11099",
        docker=docker,
        output_dir=tmp_path / "prepare",
        active_index_path=index_path,
    )
    active = json.loads(index_path.read_text(encoding="utf-8"))
    active["prepared_environments"]["django__django-11099"]["status"] = status
    index_path.write_text(json.dumps(active), encoding="utf-8")

    with pytest.raises(Exception, match="prepare --replace-existing"):
        sandbox_run.run_prepared_swebench_runtime(
            dataset_path=dataset,
            instance_id="django__django-11099",
            docker=docker,
            backend=MockBackend([]),
            budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
            model_name="mock-model",
            output_dir=tmp_path / "run",
            active_index_path=index_path,
        )

    assert not (tmp_path / "run" / "trajectory.jsonl").exists()
