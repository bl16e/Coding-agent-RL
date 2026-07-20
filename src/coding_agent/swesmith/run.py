from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from coding_agent.agent import run_task
from coding_agent.model_backends.base import ModelBackend
from coding_agent.models import BenchmarkTask, Prediction, RunBudget, RunSummary
from coding_agent.sandbox.docker_cli import DockerCli
from coding_agent.sandbox.tools import ContainerToolExecutor
from coding_agent.swebench.prediction import prediction_to_dict
from coding_agent.swesmith.dataset import _repo_key, load_subset
from coding_agent.swesmith.runtime import SwesmithPreparedContainer, create_official_container, import_swesmith


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


def _run_instance_and_collect(
    instance: dict[str, Any],
    docker: DockerCli,
    backend_factory: Callable[[], ModelBackend],
    budget: RunBudget,
    model_name: str,
    root: Path,
    reference_path: str | Path | None,
) -> tuple[str, str, str | None, str, Prediction]:
    """Run one SWE-smith instance and return (instance_id, status, error, run_dir, prediction)."""
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
    pred = _read_prediction(run_dir, instance_id, model_name)
    return (instance_id, status, error, str(run_dir), pred)


def _collect_image_names(
    instances: list[dict[str, Any]],
    reference_path: str | Path | None,
) -> list[str]:
    """Return sorted unique Docker image names for the repos in *instances*."""
    import importlib

    import_swesmith(reference_path=reference_path)
    profiles_module = importlib.import_module("swesmith.profiles")
    registry = profiles_module.registry

    seen: set[str] = set()
    image_names: list[str] = []
    for inst in instances:
        try:
            profile = registry.get_from_inst(inst)
        except Exception:
            continue
        name = profile.image_name
        if name not in seen:
            seen.add(name)
            image_names.append(name)
    return sorted(image_names)


def _cleanup_docker_images(image_names: list[str]) -> None:
    """Remove the listed Docker images (best-effort, non-fatal)."""
    for name in image_names:
        subprocess.run(
            ["docker", "rmi", name],
            check=False,
            capture_output=True,
        )


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
    cleanup_images: bool = False,
) -> int:
    if jobs < 1:
        raise ValueError("jobs must be a positive integer")

    rows = load_subset(subset_path)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    # ── Sort by repo so same-image instances cluster together ────────────
    # Same repo → same Docker image → pull once, reused for all instances.
    rows = sorted(rows, key=lambda inst: _repo_key(inst))
    repo_count = len({_repo_key(inst) for inst in rows})
    import logging
    _log = logging.getLogger(__name__)
    _log.info("SWE-smith subset: %d instances across %d repos, jobs=%d", len(rows), repo_count, jobs)

    results: list[dict[str, Any]] = []
    predictions: list[Prediction] = []

    if jobs == 1:
        # ── Sequential path ────────────────────────────────────────────────
        for instance in rows:
            instance_id, status, error, run_dir_str, pred = _run_instance_and_collect(
                instance, docker=docker, backend_factory=backend_factory,
                budget=budget, model_name=model_name, root=root,
                reference_path=reference_path,
            )
            predictions.append(pred)
            results.append({"instance_id": instance_id, "status": status, "error": error, "run_dir": run_dir_str})
    else:
        # ── Parallel path ──────────────────────────────────────────────────
        instance_map: dict[str, dict[str, Any]] = {
            str(inst["instance_id"]): inst for inst in rows
        }
        instance_order: list[str] = [str(inst["instance_id"]) for inst in rows]
        gathered: dict[str, tuple[str, str | None, str, Prediction]] = {}
        results_lock = threading.Lock()

        def _run_one(instance_id: str) -> None:
            inst = instance_map[instance_id]
            _, status, error, run_dir_str, pred = _run_instance_and_collect(
                inst, docker=docker, backend_factory=backend_factory,
                budget=budget, model_name=model_name, root=root,
                reference_path=reference_path,
            )
            with results_lock:
                gathered[instance_id] = (status, error, run_dir_str, pred)

        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = [executor.submit(_run_one, iid) for iid in instance_order]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    raise RuntimeError(f"unexpected worker failure: {exc}") from exc

        # Reconstruct in original (repo-sorted) instance order.
        for instance_id in instance_order:
            status, error, run_dir_str, pred = gathered[instance_id]
            predictions.append(pred)
            results.append({"instance_id": instance_id, "status": status, "error": error, "run_dir": run_dir_str})

    # ── Write batch artifacts ───────────────────────────────────────────────
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

    # ── Optional image cleanup ──────────────────────────────────────────────
    if cleanup_images:
        _log.info("Cleaning up Docker images...")
        image_names = _collect_image_names(rows, reference_path)
        _cleanup_docker_images(image_names)
        _log.info("Removed %d Docker images", len(image_names))

    return 4 if any(result["status"] == "errored" for result in results) else 0
