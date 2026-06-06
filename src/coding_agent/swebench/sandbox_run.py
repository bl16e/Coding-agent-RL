from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from coding_agent.agent import ArtifactPersistenceError, run_task
from coding_agent.model_backends.base import ModelBackend
from coding_agent.models import (
    BaseImage,
    BenchmarkTask,
    Prediction,
    RunBudget,
    RunStatus,
    RunSummary,
    SandboxMetadata,
    TaskSandbox,
    ValidationTestSet,
)
from coding_agent.sandbox.docker_cli import DockerCli
from coding_agent.sandbox.manager import TaskSandboxManager
from coding_agent.sandbox.registry import SandboxRegistryError, load_base_image_from_registry as registry_load_base_image
from coding_agent.sandbox.tools import ContainerToolExecutor
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.prediction import write_prediction_jsonl
from coding_agent.swebench.validation import ValidationMetadataError, build_validation_test_set
from coding_agent.trajectory.summary import write_summary


class SandboxedRunInputError(ValueError):
    """Raised for invalid sandboxed run inputs before model execution."""


class SandboxedRunRuntimeError(RuntimeError):
    """Raised after agent execution begins and partial artifacts are preserved."""

    def __init__(self, summary: RunSummary) -> None:
        self.summary = summary
        super().__init__(summary.error or "sandboxed run failed")


def validation_from_task(
    task_record: SwebenchTaskRecord,
    base_image: BaseImage,
    *,
    include_pass_to_pass: bool = False,
) -> ValidationTestSet:
    try:
        return build_validation_test_set(task_record, base_image, include_pass_to_pass=include_pass_to_pass)
    except ValidationMetadataError as exc:
        raise SandboxedRunInputError(str(exc)) from exc


def _sandbox_payload(sandbox: TaskSandbox, validation: ValidationTestSet, *, status: str) -> dict[str, Any]:
    return {
        "instance_id": sandbox.instance_id,
        "repo": sandbox.repo,
        "base_commit": sandbox.base_commit,
        "container_name": sandbox.container_name,
        "repo_path": sandbox.repo_path,
        "status": status,
        "base_image": sandbox.base_image.to_dict() if hasattr(sandbox.base_image, "to_dict") else {
            "repo": sandbox.base_image.repo,
            "image": sandbox.base_image.image,
            "repo_path": sandbox.base_image.repo_path,
            "official_compatible": sandbox.base_image.official_compatible,
            "compatibility_source": sandbox.base_image.compatibility_source,
            "validation_command_template": sandbox.base_image.validation_command_template,
        },
        "validation": {
            "mode": "fail_to_pass",
            "command_source": validation.command_source,
            "allowed_command_count": len(validation.allowed_commands),
            "fail_to_pass_count": len(validation.fail_to_pass),
            "pass_to_pass_count": len(validation.pass_to_pass),
        },
    }


def _write_sandbox_json(path: Path, sandbox: TaskSandbox, validation: ValidationTestSet, *, status: str) -> None:
    path.write_text(json.dumps(_sandbox_payload(sandbox, validation, status=status), indent=2), encoding="utf-8")


def _write_runtime_failure_artifacts(
    *,
    output_dir: Path,
    run_id: str,
    task_record: SwebenchTaskRecord,
    sandbox: TaskSandbox,
    validation: ValidationTestSet,
    budget: RunBudget,
    model_name: str,
    error: Exception,
) -> RunSummary:
    (output_dir / "final.patch").write_text("", encoding="utf-8")
    summary = RunSummary(
        run_id=run_id,
        instance_id=task_record.instance_id,
        model_name=model_name,
        status=RunStatus.ERRORED,
        budget=budget,
        error=str(error),
        artifacts={
            "trajectory": str(output_dir / "trajectory.jsonl"),
            "final_patch": str(output_dir / "final.patch"),
            "prediction": str(output_dir / "prediction.jsonl"),
            "sandbox": str(output_dir / "sandbox.json"),
        },
        sandbox=SandboxMetadata(
            task_sandbox=TaskSandbox(
                container_name=sandbox.container_name,
                base_image=sandbox.base_image,
                instance_id=sandbox.instance_id,
                repo=sandbox.repo,
                base_commit=sandbox.base_commit,
                repo_path=sandbox.repo_path,
                status="error",
            ),
            validation_test_set=validation,
            failure_state="error",
        ),
    )
    write_summary(output_dir / "summary.json", summary)
    write_prediction_jsonl(output_dir / "prediction.jsonl", Prediction(task_record.instance_id, model_name, ""))
    _write_sandbox_json(output_dir / "sandbox.json", sandbox, validation, status="error")
    return summary


def run_swebench_task(
    *,
    task_record: SwebenchTaskRecord,
    base_image: BaseImage,
    docker: DockerCli,
    backend: ModelBackend,
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    include_pass_to_pass: bool = False,
) -> RunSummary:
    if not base_image.official_compatible:
        raise SandboxedRunInputError("base image must be marked official_compatible")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    host_workspace = output_path / "_workspace_snapshot"
    host_workspace.mkdir(parents=True, exist_ok=True)
    validation = validation_from_task(task_record, base_image, include_pass_to_pass=include_pass_to_pass)
    manager = TaskSandboxManager(docker=docker)
    sandbox = manager.prepare(base_image=base_image, instance_id=task_record.instance_id, base_commit=task_record.base_commit)
    _write_sandbox_json(output_path / "sandbox.json", sandbox, validation, status="running")
    run_id = str(uuid.uuid4())
    task = BenchmarkTask(
        instance_id=task_record.instance_id,
        workspace=host_workspace,
        problem_statement=task_record.problem_statement,
        allowed_test_commands=validation.allowed_commands,
        repo=task_record.repo,
        base_commit=task_record.base_commit,
    )
    executor = ContainerToolExecutor(
        docker=docker,
        container_name=sandbox.container_name,
        repo_path=sandbox.repo_path,
        allowed_test_commands=validation.allowed_commands,
        test_timeout_seconds=budget.test_timeout_seconds,
    )
    try:
        summary = run_task(
            task=task,
            budget=budget,
            backend=backend,
            model_name=model_name,
            output_dir=output_path,
            run_id=run_id,
            tool_executor=executor,
        )
    except ArtifactPersistenceError:
        raise
    except Exception as exc:
        failure_summary = _write_runtime_failure_artifacts(
            output_dir=output_path,
            run_id=run_id,
            task_record=task_record,
            sandbox=sandbox,
            validation=validation,
            budget=budget,
            model_name=model_name,
            error=exc,
        )
        manager.stop(sandbox)
        return failure_summary
    manager.stop(sandbox)
    summary = RunSummary(
        run_id=summary.run_id,
        instance_id=summary.instance_id,
        model_name=summary.model_name,
        status=summary.status,
        budget=summary.budget,
        changed_files=summary.changed_files,
        test_summary=summary.test_summary,
        error=summary.error,
        last_successful_tool_call=summary.last_successful_tool_call,
        artifacts={**summary.artifacts, "sandbox": str(output_path / "sandbox.json")},
        sandbox=SandboxMetadata(task_sandbox=sandbox, validation_test_set=validation),
    )
    write_summary(output_path / "summary.json", summary)
    _write_sandbox_json(output_path / "sandbox.json", sandbox, validation, status="stopped")
    return summary


def load_base_image_from_registry(path: str | Path, repo: str) -> BaseImage:
    try:
        base_image = registry_load_base_image(path, repo, require_runnable=False)
        if not base_image.official_compatible:
            raise SandboxedRunInputError("base image must be marked official_compatible")
        return base_image
    except SandboxRegistryError as exc:
        raise SandboxedRunInputError(str(exc)) from exc
