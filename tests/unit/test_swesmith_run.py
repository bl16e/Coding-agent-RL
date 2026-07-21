import json
from pathlib import Path

from coding_agent.models import RunBudget, RunStatus, RunSummary
from coding_agent.swesmith.run import run_swesmith_instance, run_swesmith_subset


class FakeDocker:
    def __init__(self) -> None:
        self.exec_calls = []

    def exec(self, container_name, command):
        self.exec_calls.append((container_name, command))

        class Result:
            stdout = "diff --git a/app.py b/app.py\n"
            stderr = ""
            returncode = 0

        return Result()


def test_run_swesmith_instance_uses_container_diff_for_prediction(tmp_path: Path, monkeypatch):
    instance = {
        "instance_id": "repo__name.abcdef12.pr_1",
        "problem_statement": "Fix the issue",
        "FAIL_TO_PASS": ["tests/test_app.py::test_bug"],
    }

    class Prepared:
        instance_id = instance["instance_id"]
        container_name = "container-1"
        repo_path = "/testbed"
        profile_key = "repo__name.abcdef12"
        image_name = "swebench/swesmith.x86_64.repo__name.abcdef12:latest"

    def fake_create_official_container(row, *, reference_path):
        return Prepared()

    def fake_run_task(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "trajectory.jsonl").write_text(
            json.dumps({"action_type": "model", "reasoning_summary": "inspect"}) + "\n",
            encoding="utf-8",
        )
        return RunSummary(
            run_id="run-1",
            instance_id=instance["instance_id"],
            model_name="mock-model",
            status=RunStatus.SOLVED,
            budget=kwargs["budget"],
            artifacts={},
        )

    monkeypatch.setattr("coding_agent.swesmith.run.create_official_container", fake_create_official_container)
    monkeypatch.setattr("coding_agent.swesmith.run.run_task", fake_run_task)

    summary = run_swesmith_instance(
        instance,
        docker=FakeDocker(),
        backend=object(),
        budget=RunBudget(1, 60, 10),
        model_name="mock-model",
        output_dir=tmp_path / "run",
        reference_path=None,
    )

    prediction = json.loads((tmp_path / "run" / "prediction.jsonl").read_text(encoding="utf-8"))
    sandbox = json.loads((tmp_path / "run" / "sandbox.json").read_text(encoding="utf-8"))
    assert summary.status is RunStatus.SOLVED
    assert prediction["model_patch"].startswith("diff --git")
    assert sandbox["runtime"]["path"] == "swesmith_official"
    assert sandbox["runtime"]["profile_key"] == "repo__name.abcdef12"
    assert sandbox["runtime"]["image_name"] == "swebench/swesmith.x86_64.repo__name.abcdef12:latest"
    assert sandbox["container_name"] == "container-1"


def test_run_swesmith_subset_writes_ordered_predictions_and_summary(tmp_path: Path, monkeypatch):
    subset = tmp_path / "subset.json"
    rows = [
        {"instance_id": "repo__name.abcdef12.pr_1", "problem_statement": "Fix 1", "FAIL_TO_PASS": ["a"]},
        {"instance_id": "repo__name.abcdef12.pr_2", "problem_statement": "Fix 2", "FAIL_TO_PASS": ["b"]},
    ]
    subset.write_text(json.dumps(rows), encoding="utf-8")

    def fake_run(instance, **kwargs):
        run_dir = Path(kwargs["output_dir"])
        run_dir.mkdir(parents=True, exist_ok=True)
        patch = f"diff --git a/{instance['instance_id']} b/{instance['instance_id']}\n"
        (run_dir / "final.patch").write_text(patch, encoding="utf-8")
        (run_dir / "prediction.jsonl").write_text(
            json.dumps({"instance_id": instance["instance_id"], "model_name_or_path": "mock", "model_patch": patch}) + "\n",
            encoding="utf-8",
        )
        return RunSummary("run", instance["instance_id"], "mock", RunStatus.SOLVED, kwargs["budget"])

    monkeypatch.setattr("coding_agent.swesmith.run.run_swesmith_instance", fake_run)

    exit_code = run_swesmith_subset(
        subset_path=subset,
        docker=FakeDocker(),
        backend_factory=lambda: object(),
        budget=RunBudget(1, 60, 10),
        model_name="mock",
        output_dir=tmp_path / "batch",
        reference_path=None,
        jobs=1,
    )

    preds = [json.loads(line) for line in (tmp_path / "batch" / "preds.jsonl").read_text(encoding="utf-8").splitlines()]
    batch = json.loads((tmp_path / "batch" / "batch_summary.json").read_text(encoding="utf-8"))
    state = json.loads((tmp_path / "batch" / "batch_state.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert [row["instance_id"] for row in preds] == ["repo__name.abcdef12.pr_1", "repo__name.abcdef12.pr_2"]
    assert batch["total"] == 2
    assert state["total"] == 2
    assert state["tasks"]["repo__name.abcdef12.pr_1"]["status"] == "solved"
    assert state["tasks"]["repo__name.abcdef12.pr_1"]["run_dir"].endswith("repo__name.abcdef12.pr_1")
    assert state["tasks"]["repo__name.abcdef12.pr_1"]["last_error"] is None


def test_run_swesmith_subset_records_errored_task_in_batch_state(tmp_path: Path, monkeypatch):
    subset = tmp_path / "subset.json"
    rows = [
        {"instance_id": "repo__name.abcdef12.pr_1", "problem_statement": "Fix 1", "FAIL_TO_PASS": ["a"]},
        {"instance_id": "repo__name.abcdef12.pr_2", "problem_statement": "Fix 2", "FAIL_TO_PASS": ["b"]},
    ]
    subset.write_text(json.dumps(rows), encoding="utf-8")

    def fake_run(instance, **kwargs):
        if instance["instance_id"].endswith("pr_2"):
            raise RuntimeError("container failed to start")
        run_dir = Path(kwargs["output_dir"])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "prediction.jsonl").write_text(
            json.dumps({"instance_id": instance["instance_id"], "model_name_or_path": "mock", "model_patch": ""}) + "\n",
            encoding="utf-8",
        )
        return RunSummary("run", instance["instance_id"], "mock", RunStatus.SOLVED, kwargs["budget"])

    monkeypatch.setattr("coding_agent.swesmith.run.run_swesmith_instance", fake_run)

    exit_code = run_swesmith_subset(
        subset_path=subset,
        docker=FakeDocker(),
        backend_factory=lambda: object(),
        budget=RunBudget(1, 60, 10),
        model_name="mock",
        output_dir=tmp_path / "batch",
        reference_path=None,
        jobs=1,
    )

    state = json.loads((tmp_path / "batch" / "batch_state.json").read_text(encoding="utf-8"))
    assert exit_code == 4
    assert state["tasks"]["repo__name.abcdef12.pr_1"]["status"] == "solved"
    assert state["tasks"]["repo__name.abcdef12.pr_2"]["status"] == "errored"
    assert state["tasks"]["repo__name.abcdef12.pr_2"]["last_error"] == "container failed to start"


def test_run_swesmith_subset_parallel_preserves_order(tmp_path: Path, monkeypatch):
    """Instances run in parallel across multiple threads but output order matches input."""
    subset = tmp_path / "subset.json"
    rows = [
        {"instance_id": f"repo__name.abcdef12.pr_{i}", "problem_statement": f"Fix {i}", "FAIL_TO_PASS": ["a"]}
        for i in range(1, 9)
    ]
    subset.write_text(json.dumps(rows), encoding="utf-8")

    def fake_run(instance, **kwargs):
        run_dir = Path(kwargs["output_dir"])
        run_dir.mkdir(parents=True, exist_ok=True)
        patch = f"diff --git a/{instance['instance_id']} b/{instance['instance_id']}\n"
        (run_dir / "final.patch").write_text(patch, encoding="utf-8")
        (run_dir / "prediction.jsonl").write_text(
            json.dumps({"instance_id": instance["instance_id"], "model_name_or_path": "mock", "model_patch": patch}) + "\n",
            encoding="utf-8",
        )
        return RunSummary("run", instance["instance_id"], "mock", RunStatus.SOLVED, kwargs["budget"])

    monkeypatch.setattr("coding_agent.swesmith.run.run_swesmith_instance", fake_run)

    exit_code = run_swesmith_subset(
        subset_path=subset,
        docker=FakeDocker(),
        backend_factory=lambda: object(),
        budget=RunBudget(1, 60, 10),
        model_name="mock",
        output_dir=tmp_path / "batch",
        reference_path=None,
        jobs=4,
    )

    preds = [json.loads(line) for line in (tmp_path / "batch" / "preds.jsonl").read_text(encoding="utf-8").splitlines()]
    batch = json.loads((tmp_path / "batch" / "batch_summary.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    expected_ids = [f"repo__name.abcdef12.pr_{i}" for i in range(1, 9)]
    assert [row["instance_id"] for row in preds] == expected_ids
    assert batch["total"] == 8
    assert batch["jobs"] == 4


def test_run_swesmith_subset_sorts_by_repo(tmp_path: Path, monkeypatch):
    """Instances from different repos are reordered so same-repo instances cluster."""
    subset = tmp_path / "subset.json"
    # Deliberately interleave repos
    rows = [
        {"instance_id": "repo_b.aaaaaaaa.pr_1", "problem_statement": "Fix B1", "FAIL_TO_PASS": ["a"]},
        {"instance_id": "repo_a.aaaaaaaa.pr_1", "problem_statement": "Fix A1", "FAIL_TO_PASS": ["a"]},
        {"instance_id": "repo_b.aaaaaaaa.pr_2", "problem_statement": "Fix B2", "FAIL_TO_PASS": ["a"]},
        {"instance_id": "repo_a.aaaaaaaa.pr_2", "problem_statement": "Fix A2", "FAIL_TO_PASS": ["a"]},
    ]
    subset.write_text(json.dumps(rows), encoding="utf-8")

    seen_order: list[str] = []

    def fake_run(instance, **kwargs):
        run_dir = Path(kwargs["output_dir"])
        run_dir.mkdir(parents=True, exist_ok=True)
        seen_order.append(instance["instance_id"])
        (run_dir / "prediction.jsonl").write_text(
            json.dumps({"instance_id": instance["instance_id"], "model_name_or_path": "mock", "model_patch": ""}) + "\n",
            encoding="utf-8",
        )
        return RunSummary("run", instance["instance_id"], "mock", RunStatus.SOLVED, kwargs["budget"])

    monkeypatch.setattr("coding_agent.swesmith.run.run_swesmith_instance", fake_run)

    run_swesmith_subset(
        subset_path=subset,
        docker=FakeDocker(),
        backend_factory=lambda: object(),
        budget=RunBudget(1, 60, 10),
        model_name="mock",
        output_dir=tmp_path / "batch",
        reference_path=None,
        jobs=1,
    )

    # After sorting, all repo_a instances should come before or after all repo_b
    a_positions = [i for i, x in enumerate(seen_order) if "repo_a" in x]
    b_positions = [i for i, x in enumerate(seen_order) if "repo_b" in x]
    assert max(a_positions) < min(b_positions) or max(b_positions) < min(a_positions), \
        f"Expected repo-clustered order, got {seen_order}"
