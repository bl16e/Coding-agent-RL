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
