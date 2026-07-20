# SWE-smith Current-Agent SFT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a SWE-smith official-runtime pipeline that runs SWE-smith generated tasks with the current `coding_agent`, evaluates with SWE-smith semantics, and exports only resolved trajectories for SFT.

**Architecture:** Add an isolated `coding_agent.swesmith` package that bridges SWE-smith official profiles/eval with the existing `run_task` and `ContainerToolExecutor` extension points. Keep SWE-smith dataset/runtime/eval/export code separate from the existing `coding_agent.swebench` runtime and do not copy SWE-smith profile metadata into local SWE-Bench metadata.

**Tech Stack:** Python 3.11, argparse, standard-library JSON/subprocess/pathlib, existing `coding_agent` agent/runtime modules, SWE-smith reference checkout imported through explicit path/PYTHONPATH, pytest with fake SWE-smith and fake Docker boundaries.

---

## File Structure

- Create `src/coding_agent/swesmith/__init__.py`: package marker and public exception exports.
- Create `src/coding_agent/swesmith/dataset.py`: local subset loading, validation, optional HF subset creation helper.
- Create `src/coding_agent/swesmith/runtime.py`: SWE-smith import path handling, official profile lookup, official container creation adapter.
- Create `src/coding_agent/swesmith/run.py`: one-instance and subset solving orchestration using current `coding_agent`.
- Create `src/coding_agent/swesmith/evaluate.py`: official SWE-smith eval subprocess wrapper and report readers.
- Create `src/coding_agent/swesmith/export_sft.py`: resolved-only trajectory-to-SFT exporter.
- Modify `src/coding_agent/cli.py`: add `coding-agent swesmith ...` CLI group and command handlers.
- Create `tests/unit/test_swesmith_dataset.py`.
- Create `tests/unit/test_swesmith_runtime.py`.
- Create `tests/unit/test_swesmith_run.py`.
- Create `tests/unit/test_swesmith_evaluate.py`.
- Create `tests/unit/test_swesmith_export_sft.py`.
- Create `tests/contract/test_cli_swesmith_contract.py`.
- Create `tests/integration/test_swesmith_pipeline_fake.py`.

## Task 1: Dataset Loader And Subset Writer

**Files:**
- Create: `src/coding_agent/swesmith/__init__.py`
- Create: `src/coding_agent/swesmith/dataset.py`
- Test: `tests/unit/test_swesmith_dataset.py`

- [ ] **Step 1: Write failing dataset tests**

```python
# tests/unit/test_swesmith_dataset.py
import json
from pathlib import Path

import pytest

from coding_agent.swesmith.dataset import (
    SwesmithDatasetError,
    create_subset_file,
    load_subset,
    validate_instance,
)


def _instance(instance_id: str = "pandas-dev__pandas.95280573.pr_53652") -> dict:
    return {
        "instance_id": instance_id,
        "repo": "pandas-dev__pandas.95280573",
        "problem_statement": "Fix the bug",
        "FAIL_TO_PASS": ["tests/test_frame.py::test_bug"],
        "PASS_TO_PASS": ["tests/test_frame.py::test_existing"],
        "patch": "diff --git a/pandas/core/frame.py b/pandas/core/frame.py\n",
    }


def test_validate_instance_requires_official_fields():
    with pytest.raises(SwesmithDatasetError, match="problem_statement is required"):
        validate_instance({"instance_id": "x"})


def test_load_subset_reads_json_array(tmp_path: Path):
    path = tmp_path / "subset.json"
    path.write_text(json.dumps([_instance()]), encoding="utf-8")

    rows = load_subset(path)

    assert len(rows) == 1
    assert rows[0]["instance_id"] == "pandas-dev__pandas.95280573.pr_53652"


def test_load_subset_reads_jsonl(tmp_path: Path):
    path = tmp_path / "subset.jsonl"
    path.write_text(json.dumps(_instance()) + "\n", encoding="utf-8")

    rows = load_subset(path)

    assert [row["problem_statement"] for row in rows] == ["Fix the bug"]


def test_load_subset_rejects_empty_subset(tmp_path: Path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(SwesmithDatasetError, match="subset must contain at least one instance"):
        load_subset(path)


def test_create_subset_file_filters_pr_and_fail_to_pass_count(tmp_path: Path):
    output = tmp_path / "subset.json"
    source = [
        _instance("repo__name.abcdef12.pr_1"),
        {**_instance("repo__name.abcdef12.issue_2"), "FAIL_TO_PASS": ["a", "b"]},
        {**_instance("repo__name.abcdef12.pr_3"), "FAIL_TO_PASS": ["a", "b", "c", "d", "e", "f"]},
    ]

    selected = create_subset_file(
        output,
        instances=source,
        require_pr=True,
        min_fail_to_pass=1,
        max_fail_to_pass=5,
    )

    assert [item["instance_id"] for item in selected] == ["repo__name.abcdef12.pr_1"]
    assert json.loads(output.read_text(encoding="utf-8")) == selected
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_swesmith_dataset.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.swesmith'`.

- [ ] **Step 3: Add package marker**

```python
# src/coding_agent/swesmith/__init__.py
from __future__ import annotations

from coding_agent.swesmith.dataset import SwesmithDatasetError

__all__ = ["SwesmithDatasetError"]
```

- [ ] **Step 4: Implement dataset loader**

```python
# src/coding_agent/swesmith/dataset.py
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class SwesmithDatasetError(ValueError):
    """Raised when SWE-smith subset input is invalid."""


REQUIRED_FIELDS = ("instance_id", "problem_statement", "FAIL_TO_PASS")


def validate_instance(instance: dict[str, Any]) -> dict[str, Any]:
    for field in REQUIRED_FIELDS:
        if not instance.get(field):
            raise SwesmithDatasetError(f"{field} is required")
    if not isinstance(instance["FAIL_TO_PASS"], list):
        raise SwesmithDatasetError("FAIL_TO_PASS must be a list")
    if "PASS_TO_PASS" in instance and not isinstance(instance["PASS_TO_PASS"], list):
        raise SwesmithDatasetError("PASS_TO_PASS must be a list")
    return dict(instance)


def _load_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SwesmithDatasetError("json subset must be an array")
    return [validate_instance(item) for item in payload]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise SwesmithDatasetError(f"jsonl line {line_number} must be an object")
        rows.append(validate_instance(payload))
    return rows


def load_subset(path: str | Path) -> list[dict[str, Any]]:
    subset_path = Path(path)
    if not subset_path.is_file():
        raise SwesmithDatasetError(f"subset file does not exist: {subset_path}")
    if subset_path.suffix == ".jsonl":
        rows = _load_jsonl(subset_path)
    elif subset_path.suffix == ".json":
        rows = _load_json(subset_path)
    else:
        raise SwesmithDatasetError("subset path must end with .json or .jsonl")
    if not rows:
        raise SwesmithDatasetError("subset must contain at least one instance")
    return rows


def filter_instances(
    instances: Iterable[dict[str, Any]],
    *,
    require_pr: bool,
    min_fail_to_pass: int,
    max_fail_to_pass: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for raw in instances:
        instance = validate_instance(dict(raw))
        fail_to_pass = instance["FAIL_TO_PASS"]
        if require_pr and ".pr_" not in instance["instance_id"]:
            continue
        if len(fail_to_pass) < min_fail_to_pass:
            continue
        if len(fail_to_pass) > max_fail_to_pass:
            continue
        selected.append(instance)
    return selected


def create_subset_file(
    output: str | Path,
    *,
    instances: Iterable[dict[str, Any]],
    require_pr: bool = True,
    min_fail_to_pass: int = 2,
    max_fail_to_pass: int = 5,
) -> list[dict[str, Any]]:
    if min_fail_to_pass < 0 or max_fail_to_pass < min_fail_to_pass:
        raise SwesmithDatasetError("fail-to-pass bounds are invalid")
    selected = filter_instances(
        instances,
        require_pr=require_pr,
        min_fail_to_pass=min_fail_to_pass,
        max_fail_to_pass=max_fail_to_pass,
    )
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(selected, indent=2, ensure_ascii=True), encoding="utf-8")
    return selected


def load_huggingface_swesmith(split: str = "train") -> list[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SwesmithDatasetError("datasets package is required for Hugging Face loading") from exc
    return [dict(item) for item in load_dataset("SWE-bench/SWE-smith", split=split)]
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `python -m pytest tests/unit/test_swesmith_dataset.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/coding_agent/swesmith/__init__.py src/coding_agent/swesmith/dataset.py tests/unit/test_swesmith_dataset.py
git commit -m "feat: add SWE-smith subset loading"
```

## Task 2: SWE-smith Official Runtime Adapter

**Files:**
- Create: `src/coding_agent/swesmith/runtime.py`
- Test: `tests/unit/test_swesmith_runtime.py`

- [ ] **Step 1: Write failing runtime adapter tests**

```python
# tests/unit/test_swesmith_runtime.py
import sys
import types
from pathlib import Path

import pytest

from coding_agent.swesmith.runtime import (
    SwesmithRuntimeError,
    create_official_container,
    import_swesmith,
)


def test_import_swesmith_adds_reference_path(tmp_path: Path, monkeypatch):
    package = tmp_path / "SWE-smith" / "swesmith"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "SWE-smith"))
    sys.modules.pop("swesmith", None)

    module = import_swesmith(reference_path=tmp_path / "SWE-smith")

    assert module.VALUE == 42


def test_import_swesmith_reports_missing_checkout(tmp_path: Path):
    with pytest.raises(SwesmithRuntimeError, match="SWE-smith checkout does not exist"):
        import_swesmith(reference_path=tmp_path / "missing")


def test_create_official_container_uses_registry_get_from_inst(monkeypatch):
    calls = {}

    class FakeContainer:
        name = "swesmith.task.instance"

    class FakeProfile:
        repo_path = "/testbed"

        def get_container(self, instance):
            calls["instance"] = instance
            return FakeContainer()

    fake_registry = types.SimpleNamespace(get_from_inst=lambda instance: FakeProfile())
    fake_profiles = types.SimpleNamespace(registry=fake_registry)
    fake_module = types.SimpleNamespace(profiles=fake_profiles)
    monkeypatch.setattr("coding_agent.swesmith.runtime.import_swesmith", lambda reference_path=None: fake_module)

    prepared = create_official_container({"instance_id": "repo__name.pr_1"}, reference_path=None)

    assert prepared.container_name == "swesmith.task.instance"
    assert prepared.repo_path == "/testbed"
    assert calls["instance"]["instance_id"] == "repo__name.pr_1"


def test_create_official_container_wraps_profile_failure(monkeypatch):
    fake_registry = types.SimpleNamespace(get_from_inst=lambda instance: (_ for _ in ()).throw(KeyError("missing")))
    fake_profiles = types.SimpleNamespace(registry=fake_registry)
    fake_module = types.SimpleNamespace(profiles=fake_profiles)
    monkeypatch.setattr("coding_agent.swesmith.runtime.import_swesmith", lambda reference_path=None: fake_module)

    with pytest.raises(SwesmithRuntimeError, match="failed to create SWE-smith container"):
        create_official_container({"instance_id": "repo__name.pr_1"}, reference_path=None)
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_swesmith_runtime.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.swesmith.runtime'`.

- [ ] **Step 3: Implement runtime adapter**

```python
# src/coding_agent/swesmith/runtime.py
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SwesmithRuntimeError(RuntimeError):
    """Raised when SWE-smith official runtime setup cannot proceed."""


@dataclass(frozen=True)
class SwesmithPreparedContainer:
    instance_id: str
    container_name: str
    repo_path: str
    profile_key: str
    raw_container: Any
    raw_profile: Any


def import_swesmith(reference_path: str | Path | None = None) -> Any:
    if reference_path is not None:
        root = Path(reference_path)
        if not root.exists():
            raise SwesmithRuntimeError(f"SWE-smith checkout does not exist: {root}")
        root_text = str(root.resolve())
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
    try:
        return importlib.import_module("swesmith")
    except ImportError as exc:
        raise SwesmithRuntimeError(
            "SWE-smith cannot be imported; pass --reference-path or set PYTHONPATH to the SWE-smith checkout"
        ) from exc


def _container_name(container: Any) -> str:
    name = getattr(container, "name", None) or getattr(container, "short_id", None)
    if not name:
        raise SwesmithRuntimeError("SWE-smith container did not expose a name")
    return str(name)


def _repo_path(profile: Any) -> str:
    path = getattr(profile, "repo_path", None)
    if path:
        return str(path)
    return "/testbed"


def create_official_container(
    instance: dict[str, Any],
    *,
    reference_path: str | Path | None,
) -> SwesmithPreparedContainer:
    try:
        import_swesmith(reference_path=reference_path)
        profiles_module = importlib.import_module("swesmith.profiles")
        profile = profiles_module.registry.get_from_inst(instance)
        container = profile.get_container(instance)
    except Exception as exc:
        raise SwesmithRuntimeError(f"failed to create SWE-smith container for {instance.get('instance_id')}: {exc}") from exc
    return SwesmithPreparedContainer(
        instance_id=str(instance["instance_id"]),
        container_name=_container_name(container),
        repo_path=_repo_path(profile),
        profile_key=str(instance.get("repo") or str(instance["instance_id"]).rsplit(".", 1)[0]),
        raw_container=container,
        raw_profile=profile,
    )
```

- [ ] **Step 4: Run tests and fix the fake import path if needed**

Run: `python -m pytest tests/unit/test_swesmith_runtime.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swesmith/runtime.py tests/unit/test_swesmith_runtime.py
git commit -m "feat: add SWE-smith official runtime adapter"
```

## Task 3: Single SWE-smith Instance Runner

**Files:**
- Create: `src/coding_agent/swesmith/run.py`
- Modify: `src/coding_agent/swesmith/__init__.py`
- Test: `tests/unit/test_swesmith_run.py`

- [ ] **Step 1: Write failing run tests**

```python
# tests/unit/test_swesmith_run.py
import json
from pathlib import Path

from coding_agent.models import RunBudget, RunStatus, RunSummary
from coding_agent.swesmith.run import run_swesmith_instance


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
    assert sandbox["container_name"] == "container-1"
```

- [ ] **Step 2: Run test and verify it fails**

Run: `python -m pytest tests/unit/test_swesmith_run.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.swesmith.run'`.

- [ ] **Step 3: Implement single-instance runner**

```python
# src/coding_agent/swesmith/run.py
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from coding_agent.agent import run_task
from coding_agent.model_backends.base import ModelBackend
from coding_agent.models import BenchmarkTask, Prediction, RunBudget, RunSummary
from coding_agent.sandbox.docker_cli import DockerCli
from coding_agent.sandbox.tools import ContainerToolExecutor
from coding_agent.swebench.prediction import prediction_to_dict
from coding_agent.swesmith.runtime import SwesmithPreparedContainer, create_official_container


SELF_TEST_COMMANDS = (
    "pytest ...",
    "python -m pytest ...",
    'python -c "..."',
    "python path/to/diagnostic.py",
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _write_prediction(path: Path, prediction: Prediction) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prediction_to_dict(prediction), ensure_ascii=True) + "\n", encoding="utf-8")


def _write_sandbox_json(path: Path, prepared: SwesmithPreparedContainer) -> None:
    _write_json(
        path,
        {
            "instance_id": prepared.instance_id,
            "container_name": prepared.container_name,
            "repo_path": prepared.repo_path,
            "profile_key": prepared.profile_key,
            "runtime": {"path": "swesmith_official"},
        },
    )


def _export_container_diff(docker: DockerCli, prepared: SwesmithPreparedContainer) -> str:
    return docker.exec(
        prepared.container_name,
        ["git", "-C", prepared.repo_path, "diff", "--binary"],
    ).stdout


def run_swesmith_instance(
    instance: dict[str, Any],
    *,
    docker: DockerCli,
    backend: ModelBackend,
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    reference_path: str | Path | None,
    container_factory: Callable[[dict[str, Any]], SwesmithPreparedContainer] | None = None,
) -> RunSummary:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    if container_factory is None:
        prepared = create_official_container(instance, reference_path=reference_path)
    else:
        prepared = container_factory(instance)
    task = BenchmarkTask(
        instance_id=str(instance["instance_id"]),
        workspace=output_path,
        problem_statement=str(instance["problem_statement"]),
        allowed_test_commands=SELF_TEST_COMMANDS,
    )
    executor = ContainerToolExecutor(
        docker=docker,
        container_name=prepared.container_name,
        repo_path=prepared.repo_path,
        allowed_test_commands=SELF_TEST_COMMANDS,
        test_timeout_seconds=budget.test_timeout_seconds,
    )
    summary = run_task(
        task=task,
        budget=budget,
        backend=backend,
        model_name=model_name,
        output_dir=output_path,
        tool_executor=executor,
    )
    patch = _export_container_diff(docker, prepared)
    (output_path / "final.patch").write_text(patch, encoding="utf-8")
    _write_prediction(output_path / "prediction.jsonl", Prediction(prepared.instance_id, model_name, patch))
    _write_sandbox_json(output_path / "sandbox.json", prepared)
    return summary
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `python -m pytest tests/unit/test_swesmith_run.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swesmith/run.py tests/unit/test_swesmith_run.py
git commit -m "feat: run current agent on SWE-smith containers"
```

## Task 4: Subset Runner And Batch Prediction Output

**Files:**
- Modify: `src/coding_agent/swesmith/run.py`
- Test: `tests/unit/test_swesmith_run.py`

- [ ] **Step 1: Add failing subset runner test**

```python
# append to tests/unit/test_swesmith_run.py
from coding_agent.swesmith.run import run_swesmith_subset


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
    assert exit_code == 0
    assert [row["instance_id"] for row in preds] == ["repo__name.abcdef12.pr_1", "repo__name.abcdef12.pr_2"]
    assert batch["total"] == 2
```

- [ ] **Step 2: Run test and verify it fails**

Run: `python -m pytest tests/unit/test_swesmith_run.py::test_run_swesmith_subset_writes_ordered_predictions_and_summary -q`

Expected: FAIL with `ImportError: cannot import name 'run_swesmith_subset'`.

- [ ] **Step 3: Implement sequential subset runner**

```python
# append to src/coding_agent/swesmith/run.py
from coding_agent.swesmith.dataset import load_subset


def _safe_instance_dir(instance_id: str) -> str:
    return instance_id.replace("/", "__").replace("\\", "__")


def _read_prediction(run_dir: Path, instance_id: str, model_name: str) -> Prediction:
    path = run_dir / "prediction.jsonl"
    if not path.is_file():
        return Prediction(instance_id, model_name, "")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        return Prediction(
            str(payload.get("instance_id", instance_id)),
            str(payload.get("model_name_or_path", model_name)),
            str(payload.get("model_patch", "")),
        )
    return Prediction(instance_id, model_name, "")


def run_swesmith_subset(
    *,
    subset_path: str | Path,
    docker: DockerCli,
    backend_factory: Callable[[], ModelBackend],
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    reference_path: str | Path | None,
    jobs: int = 1,
) -> int:
    if jobs != 1:
        raise ValueError("SWE-smith run-subset supports jobs=1 in the first version")
    rows = load_subset(subset_path)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    predictions: list[Prediction] = []
    for instance in rows:
        instance_id = str(instance["instance_id"])
        run_dir = root / _safe_instance_dir(instance_id)
        try:
            summary = run_swesmith_instance(
                instance,
                docker=docker,
                backend=backend_factory(),
                budget=budget,
                model_name=model_name,
                output_dir=run_dir,
                reference_path=reference_path,
            )
            status = summary.status.value
            error = summary.error
        except Exception as exc:
            status = "errored"
            error = str(exc)
        predictions.append(_read_prediction(run_dir, instance_id, model_name))
        results.append({"instance_id": instance_id, "status": status, "error": error, "run_dir": str(run_dir)})
    preds_path = root / "preds.jsonl"
    preds_path.write_text(
        "".join(json.dumps(prediction_to_dict(pred), ensure_ascii=True) + "\n" for pred in predictions),
        encoding="utf-8",
    )
    _write_json(
        root / "batch_summary.json",
        {
            "total": len(results),
            "jobs": jobs,
            "subset": str(subset_path),
            "predictions": str(preds_path),
            "tasks": results,
        },
    )
    return 4 if any(result["status"] == "errored" for result in results) else 0
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `python -m pytest tests/unit/test_swesmith_run.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swesmith/run.py tests/unit/test_swesmith_run.py
git commit -m "feat: add SWE-smith subset runner"
```

## Task 5: Official SWE-smith Evaluation Wrapper

**Files:**
- Create: `src/coding_agent/swesmith/evaluate.py`
- Test: `tests/unit/test_swesmith_evaluate.py`

- [ ] **Step 1: Write failing evaluation tests**

```python
# tests/unit/test_swesmith_evaluate.py
import json
from pathlib import Path

from coding_agent.swesmith.evaluate import read_resolved_ids, run_official_eval


def test_run_official_eval_invokes_swesmith_module(tmp_path: Path):
    calls = {}

    def fake_runner(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs

        class Completed:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Completed()

    exit_code = run_official_eval(
        dataset_path=tmp_path / "subset.json",
        predictions_path=tmp_path / "preds.jsonl",
        run_id="run-1",
        workers=2,
        timeout=240,
        reference_path=tmp_path / "Reference" / "SWE-smith",
        runner=fake_runner,
    )

    assert exit_code == 0
    assert calls["command"][:3][-1] == "swesmith.harness.eval"
    assert "--dataset_path" in calls["command"]
    assert str(tmp_path / "subset.json") in calls["command"]


def test_read_resolved_ids_reads_per_instance_reports(tmp_path: Path):
    eval_dir = tmp_path / "logs" / "run_evaluation" / "run-1"
    (eval_dir / "inst-1").mkdir(parents=True)
    (eval_dir / "inst-2").mkdir(parents=True)
    (eval_dir / "inst-1" / "report.json").write_text(json.dumps({"resolved": True}), encoding="utf-8")
    (eval_dir / "inst-2" / "report.json").write_text(json.dumps({"resolved": False}), encoding="utf-8")

    assert read_resolved_ids(eval_dir) == {"inst-1"}
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_swesmith_evaluate.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.swesmith.evaluate'`.

- [ ] **Step 3: Implement evaluation wrapper**

```python
# src/coding_agent/swesmith/evaluate.py
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Any


def run_official_eval(
    *,
    dataset_path: str | Path,
    predictions_path: str | Path,
    run_id: str,
    workers: int,
    timeout: int,
    reference_path: str | Path | None,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    command = [
        sys.executable,
        "-m",
        "swesmith.harness.eval",
        "--dataset_path",
        str(dataset_path),
        "--predictions_path",
        str(predictions_path),
        "--run_id",
        run_id,
        "--workers",
        str(workers),
        "--timeout",
        str(timeout),
    ]
    env = dict(os.environ)
    if reference_path is not None:
        env["PYTHONPATH"] = str(Path(reference_path).resolve()) + os.pathsep + env.get("PYTHONPATH", "")
    completed = runner(command, text=True, capture_output=True, check=False, env=env)
    return int(completed.returncode)


def _report_resolved(payload: dict[str, Any], instance_id: str) -> bool:
    if "resolved" in payload:
        return bool(payload["resolved"])
    nested = payload.get(instance_id)
    if isinstance(nested, dict):
        return bool(nested.get("resolved", False))
    return False


def read_resolved_ids(eval_dir: str | Path) -> set[str]:
    root = Path(eval_dir)
    resolved: set[str] = set()
    if not root.is_dir():
        return resolved
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        report_path = child / "report.json"
        if not report_path.is_file():
            continue
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if _report_resolved(payload, child.name):
            resolved.add(child.name)
    return resolved
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `python -m pytest tests/unit/test_swesmith_evaluate.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swesmith/evaluate.py tests/unit/test_swesmith_evaluate.py
git commit -m "feat: wrap official SWE-smith evaluation"
```

## Task 6: Resolved-Only SFT Exporter

**Files:**
- Create: `src/coding_agent/swesmith/export_sft.py`
- Test: `tests/unit/test_swesmith_export_sft.py`

- [ ] **Step 1: Write failing exporter tests**

```python
# tests/unit/test_swesmith_export_sft.py
import json
from pathlib import Path

from coding_agent.swesmith.export_sft import export_sft


def _write_run(root: Path, instance_id: str, resolved: bool) -> None:
    run_dir = root / instance_id
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"instance_id": instance_id, "model_name": "mock-model"}),
        encoding="utf-8",
    )
    (run_dir / "final.patch").write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps({"action_type": "model", "reasoning_summary": "I will inspect the code."}) + "\n"
        + json.dumps(
            {
                "action_type": "tool_result",
                "tool_call": {"tool_name": "read_file", "input": {"path": "app.py"}},
                "tool_result": {"output": {"content": "print('hi')"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report_dir = root.parent / "eval" / instance_id
    report_dir.mkdir(parents=True)
    report_dir.joinpath("report.json").write_text(json.dumps({"resolved": resolved}), encoding="utf-8")


def test_export_sft_includes_only_resolved_runs(tmp_path: Path):
    runs = tmp_path / "runs"
    _write_run(runs, "inst-1", True)
    _write_run(runs, "inst-2", False)
    output = tmp_path / "out.jsonl"

    count = export_sft(runs_dir=runs, eval_dir=tmp_path / "eval", output=output, style="xml")

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert count == 1
    assert rows[0]["instance_id"] == "inst-1"
    assert rows[0]["resolved"] is True
    assert rows[0]["messages"][0]["role"] == "system"
    assert "<function=read_file>" in rows[0]["messages"][-1]["content"]
```

- [ ] **Step 2: Run test and verify it fails**

Run: `python -m pytest tests/unit/test_swesmith_export_sft.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.swesmith.export_sft'`.

- [ ] **Step 3: Implement exporter**

```python
# src/coding_agent/swesmith/export_sft.py
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from coding_agent.swesmith.evaluate import read_resolved_ids


SYSTEM_PROMPT = "You are a coding agent that solves repository issues using the provided tools."


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tool_xml(tool_name: str, arguments: dict[str, Any]) -> str:
    lines = [f"<function={tool_name}>"]
    for key, value in arguments.items():
        if key in {"old_string", "new_string", "content"}:
            lines.append(f"<parameter={key}>\n{value}\n</parameter>")
        else:
            lines.append(f"<parameter={key}>{value}</parameter>")
    lines.append("</function>")
    return "\n".join(lines)


def _messages_from_trajectory(path: Path) -> list[dict[str, str]]:
    events = _load_jsonl(path)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    pending_reasoning = ""
    for event in events:
        if event.get("action_type") == "model":
            pending_reasoning = str(event.get("reasoning_summary") or "")
            continue
        if event.get("action_type") != "tool_result":
            continue
        tool_call = event.get("tool_call") or {}
        tool_name = str(tool_call.get("tool_name") or "")
        arguments = tool_call.get("input") if isinstance(tool_call.get("input"), dict) else {}
        content = pending_reasoning.strip()
        xml = _tool_xml(tool_name, arguments)
        messages.append({"role": "assistant", "content": (content + "\n\n" + xml).strip()})
        observation = event.get("tool_result") or {}
        messages.append({"role": "user", "content": "OBSERVATION:\n" + json.dumps(observation, ensure_ascii=False, default=str)})
        pending_reasoning = ""
    return messages


def _traj_id(instance_id: str, runs_dir: Path) -> str:
    digest = hashlib.sha1(f"{runs_dir.resolve()}::{instance_id}".encode("utf-8")).hexdigest()[:12]
    return f"{instance_id}.{digest}"


def export_sft(*, runs_dir: str | Path, eval_dir: str | Path, output: str | Path, style: str = "xml") -> int:
    if style != "xml":
        raise ValueError("only xml style is supported in the first version")
    runs_root = Path(runs_dir)
    resolved_ids = read_resolved_ids(eval_dir)
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        summary_path = run_dir / "summary.json"
        trajectory_path = run_dir / "trajectory.jsonl"
        patch_path = run_dir / "final.patch"
        if not summary_path.is_file() or not trajectory_path.is_file():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        instance_id = str(summary.get("instance_id") or run_dir.name)
        if instance_id not in resolved_ids:
            continue
        rows.append(
            {
                "instance_id": instance_id,
                "resolved": True,
                "model": str(summary.get("model_name", "")),
                "traj_id": _traj_id(instance_id, runs_root),
                "patch": patch_path.read_text(encoding="utf-8") if patch_path.is_file() else "",
                "messages": _messages_from_trajectory(trajectory_path),
            }
        )
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return len(rows)
```

- [ ] **Step 4: Run test and verify it passes**

Run: `python -m pytest tests/unit/test_swesmith_export_sft.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swesmith/export_sft.py tests/unit/test_swesmith_export_sft.py
git commit -m "feat: export resolved SWE-smith trajectories"
```

## Task 7: CLI Wiring

**Files:**
- Modify: `src/coding_agent/cli.py`
- Test: `tests/contract/test_cli_swesmith_contract.py`

- [ ] **Step 1: Write failing CLI contract tests**

```python
# tests/contract/test_cli_swesmith_contract.py
import json
from pathlib import Path

from coding_agent.cli import main


def test_swesmith_help_lists_official_pipeline_commands(capsys):
    exit_code = main(["swesmith", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "create-subset" in captured.out
    assert "run-subset" in captured.out
    assert "eval" in captured.out
    assert "export-sft" in captured.out


def test_swesmith_run_subset_wires_arguments(tmp_path: Path, monkeypatch):
    subset = tmp_path / "subset.json"
    subset.write_text(json.dumps([{"instance_id": "inst-1", "problem_statement": "Fix", "FAIL_TO_PASS": ["a"]}]), encoding="utf-8")
    captured = {}

    def fake_run_swesmith_subset(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("coding_agent.cli.run_swesmith_subset", fake_run_swesmith_subset, raising=False)

    exit_code = main(
        [
            "swesmith",
            "run-subset",
            "--subset",
            str(subset),
            "--output-dir",
            str(tmp_path / "runs"),
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--backend",
            "mock",
            "--model",
            "mock",
            "--reference-path",
            str(tmp_path / "Reference" / "SWE-smith"),
        ]
    )

    assert exit_code == 0
    assert captured["subset_path"] == str(subset)
    assert captured["output_dir"] == Path(tmp_path / "runs")
    assert captured["model_name"] == "mock"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/contract/test_cli_swesmith_contract.py -q`

Expected: FAIL because `swesmith` command is not implemented.

- [ ] **Step 3: Add imports in `cli.py`**

```python
from coding_agent.swesmith.dataset import SwesmithDatasetError, create_subset_file, load_huggingface_swesmith
from coding_agent.swesmith.evaluate import run_official_eval
from coding_agent.swesmith.export_sft import export_sft
from coding_agent.swesmith.run import run_swesmith_subset
from coding_agent.swesmith.runtime import SwesmithRuntimeError
```

- [ ] **Step 4: Add parser group in `build_parser()` before returning parser**

```python
    swesmith_parser = subparsers.add_parser("swesmith", help="SWE-smith training trajectory commands")
    swesmith_subparsers = swesmith_parser.add_subparsers(dest="swesmith_command")
    swesmith_create_parser = swesmith_subparsers.add_parser("create-subset", help="create a local SWE-smith subset file")
    swesmith_create_parser.add_argument("--out", required=True)
    swesmith_create_parser.add_argument("--split", default="train")
    swesmith_create_parser.add_argument("--min-fail-to-pass", type=int, default=2)
    swesmith_create_parser.add_argument("--max-fail-to-pass", type=int, default=5)
    swesmith_create_parser.add_argument("--require-pr", action="store_true")
    swesmith_run_parser = swesmith_subparsers.add_parser("run-subset", help="run current agent on a SWE-smith subset")
    swesmith_run_parser.add_argument("--subset", required=True)
    swesmith_run_parser.add_argument("--output-dir", required=True)
    swesmith_run_parser.add_argument("--max-steps", type=int, required=True)
    swesmith_run_parser.add_argument("--timeout-seconds", type=int, required=True)
    swesmith_run_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    swesmith_run_parser.add_argument("--jobs", type=int, default=1)
    swesmith_run_parser.add_argument("--reference-path")
    swesmith_run_parser.add_argument("--model")
    swesmith_run_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
    swesmith_eval_parser = swesmith_subparsers.add_parser("eval", help="run official SWE-smith evaluation")
    swesmith_eval_parser.add_argument("--subset", required=True)
    swesmith_eval_parser.add_argument("--predictions", required=True)
    swesmith_eval_parser.add_argument("--run-id", required=True)
    swesmith_eval_parser.add_argument("--workers", type=int, default=10)
    swesmith_eval_parser.add_argument("--timeout", type=int, default=240)
    swesmith_eval_parser.add_argument("--reference-path")
    swesmith_export_parser = swesmith_subparsers.add_parser("export-sft", help="export resolved trajectories to SFT JSONL")
    swesmith_export_parser.add_argument("--runs", required=True)
    swesmith_export_parser.add_argument("--eval-dir", required=True)
    swesmith_export_parser.add_argument("--out", required=True)
    swesmith_export_parser.add_argument("--style", choices=("xml",), default="xml")
```

- [ ] **Step 5: Add command handlers in `cli.py`**

```python
def _swesmith_create_subset_command(args: argparse.Namespace) -> int:
    try:
        instances = load_huggingface_swesmith(split=args.split)
        selected = create_subset_file(
            args.out,
            instances=instances,
            require_pr=args.require_pr,
            min_fail_to_pass=args.min_fail_to_pass,
            max_fail_to_pass=args.max_fail_to_pass,
        )
        print(json.dumps({"output": args.out, "count": len(selected)}, indent=2))
    except SwesmithDatasetError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    return 0


def _swesmith_run_subset_command(args: argparse.Namespace) -> int:
    try:
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        if args.backend == "mock":
            model_name = args.model or "mock-model"

            def backend_factory():
                return MockBackend()
        else:
            config = load_model_config(model_override=args.model)
            model_name = config.model

            def backend_factory():
                return OpenAICompatibleBackend(config)
        return run_swesmith_subset(
            subset_path=args.subset,
            docker=DockerCli(),
            backend_factory=backend_factory,
            budget=budget,
            model_name=model_name,
            output_dir=Path(args.output_dir),
            reference_path=args.reference_path,
            jobs=args.jobs,
        )
    except (ValueError, SwesmithDatasetError, SwesmithRuntimeError, MissingModelConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ArtifactPersistenceError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4


def _swesmith_eval_command(args: argparse.Namespace) -> int:
    return run_official_eval(
        dataset_path=args.subset,
        predictions_path=args.predictions,
        run_id=args.run_id,
        workers=args.workers,
        timeout=args.timeout,
        reference_path=args.reference_path,
    )


def _swesmith_export_sft_command(args: argparse.Namespace) -> int:
    try:
        count = export_sft(runs_dir=args.runs, eval_dir=args.eval_dir, output=args.out, style=args.style)
        print(json.dumps({"output": args.out, "count": count}, indent=2))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0
```

- [ ] **Step 6: Dispatch `swesmith` in `main()`**

```python
    if args.command == "swesmith":
        if getattr(args, "swesmith_command", None) == "create-subset":
            return _swesmith_create_subset_command(args)
        if getattr(args, "swesmith_command", None) == "run-subset":
            return _swesmith_run_subset_command(args)
        if getattr(args, "swesmith_command", None) == "eval":
            return _swesmith_eval_command(args)
        if getattr(args, "swesmith_command", None) == "export-sft":
            return _swesmith_export_sft_command(args)
        parser.error("swesmith subcommand is required")
        return 2
```

- [ ] **Step 7: Run CLI contract tests**

Run: `python -m pytest tests/contract/test_cli_swesmith_contract.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/coding_agent/cli.py tests/contract/test_cli_swesmith_contract.py
git commit -m "feat: add SWE-smith CLI commands"
```

## Task 8: Fake End-To-End Pipeline Test

**Files:**
- Create: `tests/integration/test_swesmith_pipeline_fake.py`

- [ ] **Step 1: Write fake integration test**

```python
# tests/integration/test_swesmith_pipeline_fake.py
import json
from pathlib import Path

from coding_agent.cli import main


def test_fake_swesmith_pipeline_exports_only_resolved(tmp_path: Path, monkeypatch):
    subset = tmp_path / "subset.json"
    subset.write_text(
        json.dumps(
            [
                {"instance_id": "inst-1", "problem_statement": "Fix one", "FAIL_TO_PASS": ["a"]},
                {"instance_id": "inst-2", "problem_statement": "Fix two", "FAIL_TO_PASS": ["b"]},
            ]
        ),
        encoding="utf-8",
    )

    def fake_run_subset(**kwargs):
        root = Path(kwargs["output_dir"])
        for instance_id in ("inst-1", "inst-2"):
            run_dir = root / instance_id
            run_dir.mkdir(parents=True)
            (run_dir / "summary.json").write_text(json.dumps({"instance_id": instance_id, "model_name": "mock"}), encoding="utf-8")
            (run_dir / "final.patch").write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
            (run_dir / "trajectory.jsonl").write_text(
                json.dumps({"action_type": "model", "reasoning_summary": "Inspect."}) + "\n"
                + json.dumps({"action_type": "tool_result", "tool_call": {"tool_name": "read_file", "input": {"path": "app.py"}}, "tool_result": {"output": {"content": "x"}}}) + "\n",
                encoding="utf-8",
            )
        (root / "preds.jsonl").write_text("", encoding="utf-8")
        (root / "batch_summary.json").write_text(json.dumps({"total": 2}), encoding="utf-8")
        return 0

    monkeypatch.setattr("coding_agent.cli.run_swesmith_subset", fake_run_subset, raising=False)
    runs = tmp_path / "runs"
    assert main(["swesmith", "run-subset", "--subset", str(subset), "--output-dir", str(runs), "--max-steps", "1", "--timeout-seconds", "60", "--test-timeout-seconds", "10", "--backend", "mock"]) == 0

    eval_dir = tmp_path / "eval"
    for instance_id, resolved in {"inst-1": True, "inst-2": False}.items():
        report_dir = eval_dir / instance_id
        report_dir.mkdir(parents=True)
        (report_dir / "report.json").write_text(json.dumps({"resolved": resolved}), encoding="utf-8")

    output = tmp_path / "sft.jsonl"
    assert main(["swesmith", "export-sft", "--runs", str(runs), "--eval-dir", str(eval_dir), "--out", str(output)]) == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["instance_id"] for row in rows] == ["inst-1"]
```

- [ ] **Step 2: Run fake integration test**

Run: `python -m pytest tests/integration/test_swesmith_pipeline_fake.py -q`

Expected: PASS.

- [ ] **Step 3: Run focused SWE-smith suite**

Run:

```bash
python -m pytest \
  tests/unit/test_swesmith_dataset.py \
  tests/unit/test_swesmith_runtime.py \
  tests/unit/test_swesmith_run.py \
  tests/unit/test_swesmith_evaluate.py \
  tests/unit/test_swesmith_export_sft.py \
  tests/contract/test_cli_swesmith_contract.py \
  tests/integration/test_swesmith_pipeline_fake.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_swesmith_pipeline_fake.py
git commit -m "test: cover fake SWE-smith SFT pipeline"
```

## Task 9: Manual Official SWE-smith Smoke Check

**Files:**
- No code changes unless this exposes a defect.

- [ ] **Step 1: Verify SWE-smith import with the reference checkout**

Run:

```bash
python -c "import sys; sys.path.insert(0, r'D:\code\coding_agent\Reference\SWE-smith'); import swesmith; print(swesmith.__file__)"
```

Expected: prints a path under `D:\code\coding_agent\Reference\SWE-smith\swesmith`.

- [ ] **Step 2: Run CLI help**

Run: `python -m coding_agent.cli swesmith --help`

Expected: output lists `create-subset`, `run-subset`, `eval`, and `export-sft`.

- [ ] **Step 3: Run official eval help through wrapper path**

Run:

```bash
$env:PYTHONPATH='D:\code\coding_agent\Reference\SWE-smith;src'; python -m swesmith.harness.eval --help
```

Expected: output contains `--dataset_path`, `--predictions_path`, and `--run_id`.

- [ ] **Step 4: Record blocker if official dependencies are missing**

If imports fail because `docker`, `datasets`, `swebench`, `unidiff`, or another SWE-smith dependency is missing, do not rewrite the integration. Record the missing package in the final report and keep automated fake tests passing.

## Task 10: Final Verification

**Files:**
- No code changes unless verification fails.

- [ ] **Step 1: Run all automated tests**

Run: `python -m pytest -q`

Expected: PASS, or existing unrelated failures documented with exact failing tests.

- [ ] **Step 2: Inspect git diff**

Run: `git diff --stat`

Expected: only SWE-smith integration files, CLI wiring, and tests from this plan are changed.

- [ ] **Step 3: Final commit if verification fixes were needed**

If any final verification edits were made:

```bash
git add src/coding_agent/swesmith src/coding_agent/cli.py tests/unit/test_swesmith_*.py tests/contract/test_cli_swesmith_contract.py tests/integration/test_swesmith_pipeline_fake.py
git commit -m "fix: stabilize SWE-smith pipeline verification"
```

## Self-Review

Spec coverage:

- Current agent instead of SWE-agent: Tasks 3, 4, and 7.
- Official SWE-smith profiles/runtime: Task 2 and manual Task 9.
- Official SWE-smith eval: Task 5 and CLI Task 7.
- Local subset primary input and optional HF subset creation: Task 1 and CLI Task 7.
- Resolved-only SFT export: Task 6 and fake integration Task 8.
- No Docker/HF/GitHub in automated defaults: Tasks 2, 5, 8 use fakes; Task 9 is manual.

Placeholder scan:

- No placeholder steps remain. Every code-writing step includes concrete code or exact insertion snippets.

Type consistency:

- `SwesmithDatasetError`, `SwesmithRuntimeError`, `SwesmithPreparedContainer`, `run_swesmith_instance`, `run_swesmith_subset`, `run_official_eval`, `read_resolved_ids`, and `export_sft` are introduced before use in later tasks.
