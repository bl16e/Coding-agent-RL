import json
from pathlib import Path

import pytest

from coding_agent.model_backends.base import AgentAction, AgentActionType
from coding_agent.model_backends.mock import MockBackend
from coding_agent.models import BaseImage, RunBudget, RunStatus
from coding_agent.sandbox.docker_cli import DockerResult
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.sandbox_run import SandboxedRunInputError, run_swebench_tasks
from coding_agent.swebench.sandbox_run import prepare_swebench_sandboxes, solve_swebench_sandboxes
from coding_agent.swebench.sandbox_run import run_official_swebench_batch
from tests.helpers.swebench_fixtures import swebench_row, write_swebench_parquet


class FakeDocker:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.current_commit_by_container: dict[str, str] = {}

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
        if command[:4] == ["git", "-C", "/workspace/repo", "checkout"]:
            self.current_commit_by_container[container] = command[-1]
        if command[:4] == ["git", "-C", "/workspace/repo", "rev-parse"] and command[-1] == "HEAD":
            return DockerResult(self.current_commit_by_container.get(container, ""), "", 0)
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


def test_prepare_sandboxes_writes_locked_state_and_active_index_without_cleanup(tmp_path: Path):
    docker = FakeDocker()
    output_dir = tmp_path / "batch"
    state_path = output_dir / "state.json"
    active_index = tmp_path / ".coding-agent" / "active-sandboxes.json"

    exit_code = prepare_swebench_sandboxes(
        task_records=[
            _task_record("django__django-11099", "abc123"),
            _task_record("django__django-11100", "def456"),
        ],
        base_images={"django/django": _base_image()},
        docker=docker,
        output_dir=output_dir,
        state_path=state_path,
        active_index_path=active_index,
        jobs=2,
    )

    assert exit_code == 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["total"] == 2
    assert state["statuses"] == {"ready": 2}
    assert state["tasks"]["django__django-11099"]["status"] == "ready"
    assert state["tasks"]["django__django-11099"]["prepare_dir"] == str(output_dir / "django__django-11099" / "prepare")
    assert state["tasks"]["django__django-11100"]["status"] == "ready"
    index = json.loads(active_index.read_text(encoding="utf-8"))
    assert set(index["sandboxes"]) == {"django__django-11099", "django__django-11100"}
    assert not any(call[0] in {"stop", "remove"} for call in docker.calls)


def test_solve_sandboxes_uses_state_to_skip_solved_and_update_remaining_task(tmp_path: Path):
    docker = FakeDocker()
    output_dir = tmp_path / "batch"
    state_path = output_dir / "state.json"
    active_index = tmp_path / ".coding-agent" / "active-sandboxes.json"
    records = [
        _task_record("django__django-11099", "abc123"),
        _task_record("django__django-11100", "def456"),
    ]
    prepare_swebench_sandboxes(
        task_records=records,
        base_images={"django/django": _base_image()},
        docker=docker,
        output_dir=output_dir,
        state_path=state_path,
        active_index_path=active_index,
        jobs=2,
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"]["django__django-11099"]["status"] = "solved"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    docker.calls.clear()

    exit_code = solve_swebench_sandboxes(
        task_records=records,
        docker=docker,
        backend_factory=_backend_factory,
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=output_dir,
        state_path=state_path,
        active_index_path=active_index,
        jobs=2,
    )

    assert exit_code == 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["tasks"]["django__django-11099"]["status"] == "solved"
    assert state["tasks"]["django__django-11100"]["status"] == "incomplete"
    assert state["tasks"]["django__django-11100"]["solve_dir"] == str(output_dir / "django__django-11100" / "solve")
    assert (output_dir / "django__django-11100" / "solve" / "summary.json").is_file()
    assert not (output_dir / "django__django-11099" / "solve").exists()
    created_names = [call[1] for call in docker.calls if call[0] == "create"]
    assert created_names == []


def test_official_batch_run_merges_multiple_datasets_and_writes_aggregate_outputs(tmp_path: Path, monkeypatch):
    dev_dataset = write_swebench_parquet(
        tmp_path / "dev.parquet",
        rows=[swebench_row(instance_id="django__django-11099", base_commit="abc123")],
    )
    test_dataset = write_swebench_parquet(
        tmp_path / "test.parquet",
        rows=[swebench_row(instance_id="django__django-11100", base_commit="def456")],
    )
    calls: list[tuple[str, str, Path]] = []

    def fake_prepare_official_swebench_runtime(**kwargs):
        calls.append(("prepare", kwargs["instance_id"], kwargs["output_dir"]))

    class Summary:
        status = RunStatus.INCOMPLETE
        error = None

    def fake_run_prepared_swebench_runtime(**kwargs):
        calls.append(("run", kwargs["instance_id"], kwargs["output_dir"]))
        run_dir = Path(kwargs["output_dir"])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "prediction.jsonl").write_text(
            json.dumps(
                {
                    "instance_id": kwargs["instance_id"],
                    "model_name_or_path": kwargs["model_name"],
                    "model_patch": "",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return Summary()

    monkeypatch.setattr("coding_agent.swebench.sandbox_run.prepare_official_swebench_runtime", fake_prepare_official_swebench_runtime)
    monkeypatch.setattr("coding_agent.swebench.sandbox_run.run_prepared_swebench_runtime", fake_run_prepared_swebench_runtime)

    exit_code = run_official_swebench_batch(
        dataset_paths=(dev_dataset, test_dataset),
        docker=FakeDocker(),
        backend_factory=_backend_factory,
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        model_name="mock-model",
        output_dir=tmp_path / "official-batch",
        jobs=1,
        build_missing=True,
        replace_existing=True,
        resume=False,
    )

    assert exit_code == 0
    assert calls == [
        ("prepare", "django__django-11099", tmp_path / "official-batch" / "django__django-11099" / "prepare"),
        ("run", "django__django-11099", tmp_path / "official-batch" / "django__django-11099" / "run"),
        ("prepare", "django__django-11100", tmp_path / "official-batch" / "django__django-11100" / "prepare"),
        ("run", "django__django-11100", tmp_path / "official-batch" / "django__django-11100" / "run"),
    ]
    summary = json.loads((tmp_path / "official-batch" / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["total"] == 2
    assert summary["statuses"] == {"incomplete": 2}
    assert set(summary["datasets"]) == {str(dev_dataset), str(test_dataset)}
    predictions = (tmp_path / "official-batch" / "prediction.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["instance_id"] for line in predictions] == [
        "django__django-11099",
        "django__django-11100",
    ]
