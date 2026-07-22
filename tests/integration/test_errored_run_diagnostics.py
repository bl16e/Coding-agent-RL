import json
from pathlib import Path

from coding_agent.agent import create_task_from_paths, run_task
from coding_agent.models import RunBudget
from coding_agent.model_backend import AgentAction, AgentActionType
from coding_agent.legacy_mock_backend import MockBackend
from coding_agent.sandbox_manager import DockerResult
from coding_agent.swebench import sandbox_run
from coding_agent.swebench.sandbox_run import prepare_official_swebench_runtime
from tests.helpers.swebench_fixtures import write_swebench_parquet
from tests.unit.fakes.test_swebench_runtime_fakes import FakeOfficialRuntimeDocker


def test_errored_run_records_diagnostics(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix it.", encoding="utf-8")
    task = create_task_from_paths(
        instance_id="example__repo-1",
        workspace=workspace,
        problem_statement_file=problem,
        allowed_test_commands=("python -m pytest",),
    )
    backend = MockBackend(
        [
            AgentAction(
                action=AgentActionType.FINAL,
                reasoning_summary="Cannot continue",
                next_intent="Stop",
                final_status="errored",
                final_message="model returned unrecoverable error",
            )
        ]
    )

    run_task(
        task=task,
        budget=RunBudget(max_steps=3, timeout_seconds=60, test_timeout_seconds=5),
        backend=backend,
        model_name="mock-model",
        output_dir=tmp_path / "run",
    )

    summary = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "errored"
    assert summary["error"] == "model returned unrecoverable error"


class FailingToolDocker(FakeOfficialRuntimeDocker):
    def exec(self, container: str, command: list[str], *, timeout_seconds=None, stdin=None) -> DockerResult:
        if command[:2] == ["python", "-c"]:
            raise RuntimeError("container read failed after agent start")
        return super().exec(container, command, timeout_seconds=timeout_seconds, stdin=stdin)


def test_official_runtime_failure_preserves_artifacts_and_cleanup_removes_active_entry(tmp_path: Path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    docker = FailingToolDocker(
        present_images={
            "sweb.base.py.x86_64:latest",
            "sweb.env.py.x86_64.2baaea72acc974f6c02079:latest",
            "sweb.eval.x86_64.django__django-11099:latest",
        }
    )
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
        backend=MockBackend([AgentAction(action=AgentActionType.READ_FILE, tool_input={"path": "README.md"})]),
        budget=RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        active_index_path=index_path,
        cleanup=True,
    )

    run_dir = tmp_path / "run"
    active = json.loads(index_path.read_text(encoding="utf-8"))
    sandbox = json.loads((run_dir / "sandbox.json").read_text(encoding="utf-8"))
    summary_payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert summary.status.value == "errored"
    for name in ("trajectory.jsonl", "trajectory.json", "summary.json", "final.patch", "prediction.jsonl", "sandbox.json"):
        assert (run_dir / name).is_file()
    assert sandbox["prepared_environment"]["status_transition"] == ["ready", "running", "error"]
    assert sandbox["cleanup"]["requested"] is True
    assert sandbox["cleanup"]["active_index_result"] == "removed"
    assert summary_payload["prepared_environment"]["status_transition"] == ["ready", "running", "error"]
    assert "django__django-11099" not in active["prepared_environments"]
    assert any(call[0] == "stop" for call in docker.calls)
    assert any(call[0] == "remove" for call in docker.calls)
