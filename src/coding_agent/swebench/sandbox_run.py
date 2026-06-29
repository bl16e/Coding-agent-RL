from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any

from coding_agent.agent import ArtifactPersistenceError, run_task
from coding_agent.model_backends.base import ModelBackend
from coding_agent.models import (
    BaseImage,
    BenchmarkTask,
    PreparedEnvironmentStatus,
    PreparedTaskEnvironment,
    Prediction,
    PreparedSandboxSummary,
    RunBudget,
    RunStatus,
    RunSummary,
    RuntimeLineage,
    SandboxMetadata,
    TaskSandbox,
    ValidationTestSet,
    EvalReport,
    utc_now,
)
from coding_agent.sandbox.docker_cli import DockerCli
from coding_agent.sandbox.manager import TaskSandboxManager
from coding_agent.sandbox.registry import SandboxRegistryError, load_base_image_from_registry as registry_load_base_image
from coding_agent.sandbox.tools import ContainerToolExecutor
from coding_agent.swebench.dataset import SwebenchTaskRecord, load_task_record, load_task_records, normalize_benchmark_task_record
from coding_agent.swebench.grading import EvalOutputParseError, parse_eval_report
from coding_agent.swebench.images import build_missing_images, inspect_image_graph
from coding_agent.swebench.prediction import (
    export_prepared_environment_patch,
    write_prediction_from_patch,
    write_prediction_jsonl,
    write_predictions_jsonl,
)
from coding_agent.swebench.testspec import build_adapted_testspec
from coding_agent.swebench.validation import ValidationMetadataError, build_official_validation_set, build_validation_test_set
from coding_agent.trajectory.converter import convert_trajectory_to_summary_format
from coding_agent.trajectory.summary import write_summary


class SandboxedRunInputError(ValueError):
    """模型执行前发现沙箱输入无效时抛出。"""


class SandboxedRunRuntimeError(RuntimeError):
    """模型执行已经开始，且已尽量保留部分产物后抛出。"""

    def __init__(self, summary: RunSummary) -> None:
        self.summary = summary
        super().__init__(summary.error or "sandboxed run failed")


def validation_from_task(
    task_record: SwebenchTaskRecord,
    base_image: BaseImage,
    *,
    include_pass_to_pass: bool = False,
) -> ValidationTestSet:
    """从任务记录和基础镜像生成验证集合，并统一转换错误类型。"""
    try:
        return build_validation_test_set(task_record, base_image, include_pass_to_pass=include_pass_to_pass)
    except ValidationMetadataError as exc:
        raise SandboxedRunInputError(str(exc)) from exc


def _sandbox_payload(
    sandbox: TaskSandbox,
    validation: ValidationTestSet,
    *,
    status: str,
    runtime_path: str = "legacy_registry",
    test_patch_applied: bool = False,
    test_patch_staged: bool = False,
    ready_checks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 sandbox.json 内容。

    sandbox.json 是 Docker 模式的审计补充文件，用来回答“这次任务跑在哪个容器、哪个
    镜像、哪个 base commit、使用了哪些验证来源”。
    """
    return {
        "instance_id": sandbox.instance_id,
        "repo": sandbox.repo,
        "base_commit": sandbox.base_commit,
        "container_name": sandbox.container_name,
        "repo_path": sandbox.repo_path,
        "status": status,
        "runtime_path": runtime_path,
        "runtime": {
            "path": runtime_path,
            "official_style": runtime_path == "official_style",
        },
        "test_patch_applied": test_patch_applied,
        "test_patch_staged": test_patch_staged,
        "ready_checks": dict(ready_checks or {}),
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


def _write_sandbox_json(
    path: Path,
    sandbox: TaskSandbox,
    validation: ValidationTestSet,
    *,
    status: str,
    runtime_path: str = "legacy_registry",
    test_patch_applied: bool = False,
    test_patch_staged: bool = False,
    ready_checks: Mapping[str, Any] | None = None,
) -> None:
    """写入沙箱元数据文件。"""
    path.write_text(
        json.dumps(
            _sandbox_payload(
                sandbox,
                validation,
                status=status,
                runtime_path=runtime_path,
                test_patch_applied=test_patch_applied,
                test_patch_staged=test_patch_staged,
                ready_checks=ready_checks,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )


def _official_sandbox_payload(
    *,
    prepared: PreparedTaskEnvironment,
    status: PreparedEnvironmentStatus,
    ready_checks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    lineage = prepared.runtime_lineage
    return {
        "instance_id": prepared.instance_id,
        "repo": prepared.repo,
        "version": prepared.version,
        "base_commit": prepared.base_commit,
        "container_name": prepared.container_name,
        "repo_path": prepared.repo_path,
        "status": status.value,
        "runtime_path": lineage.runtime_path,
        "runtime": {
            "path": lineage.runtime_path,
            "base_image_key": lineage.base_image_key,
            "env_image_key": lineage.env_image_key,
            "instance_image_key": lineage.instance_image_key,
            "platform": lineage.platform,
            "build_missing": lineage.build_missing,
            "built_images": list(lineage.built_images),
            "reused_images": list(lineage.reused_images),
            "metadata_sources": list(lineage.metadata_sources),
        },
        "ready_checks": dict(ready_checks or {}),
    }


def _read_active_prepared_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"prepared_environments": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SandboxedRunInputError(str(exc)) from exc
    payload.setdefault("prepared_environments", {})
    return payload


def _write_active_prepared_index(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _assert_prepared_slot_available(index_path: Path, instance_id: str, *, replace_existing: bool) -> dict[str, Any]:
    payload = _read_active_prepared_index(index_path)
    if instance_id in payload.get("prepared_environments", {}) and not replace_existing:
        raise ValueError(f"{instance_id} already has an active prepared environment")
    return payload


def _save_active_prepared_environment(index_path: Path, prepared: PreparedTaskEnvironment) -> None:
    payload = _read_active_prepared_index(index_path)
    payload.setdefault("prepared_environments", {})[prepared.instance_id] = {
        "instance_id": prepared.instance_id,
        "container_name": prepared.container_name,
        "repo": prepared.repo,
        "version": prepared.version,
        "base_commit": prepared.base_commit,
        "repo_path": prepared.repo_path,
        "sandbox_json": str(prepared.sandbox_json),
        "status": prepared.status.value,
        "ready_checks": dict(prepared.ready_checks),
        "runtime_lineage": {
            "runtime_path": prepared.runtime_lineage.runtime_path,
            "base_image_key": prepared.runtime_lineage.base_image_key,
            "env_image_key": prepared.runtime_lineage.env_image_key,
            "instance_image_key": prepared.runtime_lineage.instance_image_key,
            "platform": prepared.runtime_lineage.platform,
            "build_missing": prepared.runtime_lineage.build_missing,
            "built_images": list(prepared.runtime_lineage.built_images),
            "reused_images": list(prepared.runtime_lineage.reused_images),
            "metadata_sources": list(prepared.runtime_lineage.metadata_sources),
        },
    }
    _write_active_prepared_index(index_path, payload)


def _runtime_lineage_from_payload(payload: Mapping[str, Any]) -> RuntimeLineage:
    return RuntimeLineage(
        runtime_path=str(payload["runtime_path"]),
        base_image_key=str(payload["base_image_key"]),
        env_image_key=str(payload["env_image_key"]),
        instance_image_key=str(payload["instance_image_key"]),
        platform=str(payload["platform"]),
        build_missing=bool(payload.get("build_missing", False)),
        built_images=tuple(str(item) for item in payload.get("built_images", ())),
        reused_images=tuple(str(item) for item in payload.get("reused_images", ())),
        metadata_sources=tuple(str(item) for item in payload.get("metadata_sources", ())),
    )


def _prepared_environment_from_index(entry: Mapping[str, Any]) -> PreparedTaskEnvironment:
    return PreparedTaskEnvironment(
        instance_id=str(entry["instance_id"]),
        repo=str(entry["repo"]),
        version=str(entry["version"]),
        base_commit=str(entry["base_commit"]),
        container_name=str(entry["container_name"]),
        repo_path=str(entry["repo_path"]),
        runtime_lineage=_runtime_lineage_from_payload(entry["runtime_lineage"]),
        status=PreparedEnvironmentStatus(str(entry["status"])),
        ready_checks=dict(entry.get("ready_checks", {})),
        sandbox_json=Path(str(entry["sandbox_json"])) if entry.get("sandbox_json") else None,
    )


def _load_active_prepared_environment(index_path: Path, instance_id: str) -> PreparedTaskEnvironment:
    payload = _read_active_prepared_index(index_path)
    entry = payload.get("prepared_environments", {}).get(instance_id)
    if not entry:
        raise SandboxedRunInputError(
            f"active prepared environment not found for {instance_id}; run swebench prepare --replace-existing"
        )
    prepared = _prepared_environment_from_index(entry)
    if prepared.status is not PreparedEnvironmentStatus.READY:
        raise SandboxedRunInputError(
            f"active prepared environment for {instance_id} is {prepared.status.value}; "
            "run swebench prepare --replace-existing"
        )
    return prepared


def _remove_active_prepared_environment(index_path: Path, instance_id: str) -> None:
    payload = _read_active_prepared_index(index_path)
    payload.setdefault("prepared_environments", {}).pop(instance_id, None)
    _write_active_prepared_index(index_path, payload)


def _task_sandbox_from_prepared(prepared: PreparedTaskEnvironment) -> TaskSandbox:
    source = next(iter(prepared.runtime_lineage.metadata_sources), None)
    return TaskSandbox(
        container_name=prepared.container_name,
        base_image=BaseImage(
            repo=prepared.repo,
            image=prepared.runtime_lineage.instance_image_key,
            repo_path=prepared.repo_path,
            official_compatible=True,
            compatibility_source=source,
        ),
        instance_id=prepared.instance_id,
        repo=prepared.repo,
        base_commit=prepared.base_commit,
        repo_path=prepared.repo_path,
        status=prepared.status.value,
    )


def _exec_ready_command(docker: DockerCli, prepared: PreparedTaskEnvironment, command: list[str]) -> Any:
    try:
        result = docker.exec(prepared.container_name, command)
    except Exception as exc:
        raise SandboxedRunInputError("container is not ready") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        message = "container is not ready" + (f": {detail}" if detail else "")
        raise SandboxedRunInputError(message)
    return result


def _official_ready_checks(
    docker: DockerCli,
    prepared: PreparedTaskEnvironment,
    testspec: Any,
) -> dict[str, Any]:
    _exec_ready_command(docker, prepared, ["true"])
    head = _exec_ready_command(
        docker,
        prepared,
        ["git", "-C", prepared.repo_path, "rev-parse", "HEAD"],
    ).stdout.strip()
    if head != prepared.base_commit:
        raise SandboxedRunInputError("prepared environment base commit does not match requested task")
    status = _exec_ready_command(
        docker,
        prepared,
        ["git", "-C", prepared.repo_path, "status", "--porcelain"],
    ).stdout.strip()
    if status:
        raise SandboxedRunInputError("prepared workspace is not clean")
    return {
        "container_exec": {"ok": True},
        "task_identity": {"ok": True, "instance_id": prepared.instance_id},
        "base_commit": {"ok": True, "base_commit": head},
        "workspace_clean": {"ok": True},
        "validation_source": {"ok": True, "source": testspec.repo_version_source},
    }


def prepare_official_swebench_runtime(
    *,
    dataset_path: str | Path,
    instance_id: str,
    docker: DockerCli,
    output_dir: str | Path,
    active_index_path: str | Path = ".coding-agent/active-sandboxes.json",
    build_missing: bool = False,
    replace_existing: bool = False,
    arch: str = "x86_64",
) -> PreparedTaskEnvironment:
    """Prepare an official-style SWE-Bench task runtime without starting the agent."""
    output_path = Path(output_dir)
    index_path = Path(active_index_path)
    index_payload = _assert_prepared_slot_available(index_path, instance_id, replace_existing=replace_existing)
    old_entry = index_payload.get("prepared_environments", {}).get(instance_id)

    task_record = normalize_benchmark_task_record(load_task_record(dataset_path, instance_id))
    testspec = build_adapted_testspec(task_record, arch=arch)
    image_plan = inspect_image_graph(testspec, docker=docker, build_missing=build_missing)
    built_images = build_missing_images(testspec, docker=docker, plan=image_plan) if image_plan.missing_images else ()
    if old_entry and replace_existing and old_entry.get("container_name"):
        docker.stop_container(str(old_entry["container_name"]))
        docker.remove_container(str(old_entry["container_name"]))

    lineage = RuntimeLineage(
        runtime_path="official_style",
        base_image_key=testspec.base_image_key,
        env_image_key=testspec.env_image_key,
        instance_image_key=testspec.instance_image_key,
        platform=testspec.platform,
        build_missing=build_missing,
        built_images=built_images,
        reused_images=image_plan.reused_images,
        metadata_sources=(testspec.repo_version_source,),
    )
    sandbox = TaskSandboxManager(docker=docker).prepare_official_instance(
        repo=task_record.repo,
        instance_id=task_record.instance_id,
        base_commit=task_record.base_commit,
        instance_image_key=testspec.instance_image_key,
        repo_path=testspec.repo_path,
        source_reference=testspec.repo_version_source,
        run_id=str(uuid.uuid4()),
    )
    sandbox_json_path = output_path / "sandbox.json"
    ready_checks: dict[str, Any] = {}
    prepared = PreparedTaskEnvironment(
        instance_id=task_record.instance_id,
        repo=task_record.repo,
        version=task_record.version or "",
        base_commit=task_record.base_commit,
        container_name=sandbox.container_name,
        repo_path=testspec.repo_path,
        runtime_lineage=lineage,
        status=PreparedEnvironmentStatus.READY,
        ready_checks=ready_checks,
        sandbox_json=sandbox_json_path,
    )
    ready_checks = _official_ready_checks(docker, prepared, testspec)
    prepared = replace(prepared, ready_checks=ready_checks)
    output_path.mkdir(parents=True, exist_ok=True)
    sandbox_json_path.write_text(
        json.dumps(_official_sandbox_payload(prepared=prepared, status=prepared.status, ready_checks=ready_checks), indent=2),
        encoding="utf-8",
    )
    _save_active_prepared_environment(index_path, prepared)
    return prepared


def _eval_report_payload(report: EvalReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "resolved": report.resolved,
        "fail_to_pass_success": list(report.fail_to_pass_success),
        "fail_to_pass_failure": list(report.fail_to_pass_failure),
        "pass_to_pass_success": list(report.pass_to_pass_success),
        "pass_to_pass_failure": list(report.pass_to_pass_failure),
        "raw_output_artifact": report.raw_output_artifact,
    }


def _artifact_locations(output_path: Path) -> dict[str, str]:
    return {
        "trajectory": str(output_path / "trajectory.jsonl"),
        "trajectory_json": str(output_path / "trajectory.json"),
        "summary": str(output_path / "summary.json"),
        "final_patch": str(output_path / "final.patch"),
        "prediction": str(output_path / "prediction.jsonl"),
        "sandbox": str(output_path / "sandbox.json"),
    }


def _runtime_metadata(
    *,
    prepared: PreparedTaskEnvironment,
    validation: ValidationTestSet,
    status_transition: Sequence[str],
    output_path: Path,
    cleanup_requested: bool,
    cleanup_action: str,
    active_index_result: str,
    eval_report: EvalReport | None = None,
) -> dict[str, Any]:
    lineage = prepared.runtime_lineage
    artifacts = _artifact_locations(output_path)
    validation_payload: dict[str, Any] = {
        "source": validation.command_source,
        "mode": "fail_to_pass_plus_pass_to_pass" if validation.include_pass_to_pass else "fail_to_pass",
        "eval_script": validation.eval_script,
        "allowed_commands": list(validation.allowed_commands),
        "fail_to_pass": list(validation.fail_to_pass),
        "pass_to_pass": list(validation.pass_to_pass),
    }
    eval_payload = _eval_report_payload(eval_report)
    if eval_payload is not None:
        validation_payload["eval_report"] = eval_payload
    return {
        "runtime": {
            "path": lineage.runtime_path,
            "base_image_key": lineage.base_image_key,
            "env_image_key": lineage.env_image_key,
            "instance_image_key": lineage.instance_image_key,
            "platform": lineage.platform,
            "build_missing": lineage.build_missing,
            "built_images": list(lineage.built_images),
            "reused_images": list(lineage.reused_images),
            "metadata_sources": list(lineage.metadata_sources),
        },
        "prepared_environment": {
            "instance_id": prepared.instance_id,
            "repo": prepared.repo,
            "version": prepared.version,
            "base_commit": prepared.base_commit,
            "container_name": prepared.container_name,
            "repo_path": prepared.repo_path,
            "status_transition": list(status_transition),
        },
        "validation": validation_payload,
        "cleanup": {
            "requested": cleanup_requested,
            "action": cleanup_action,
            "active_index_result": active_index_result,
        },
        "active_index": {
            "result": active_index_result,
        },
        "artifacts": artifacts,
    }


def _write_official_sandbox_json(
    *,
    output_path: Path,
    prepared: PreparedTaskEnvironment,
    validation: ValidationTestSet,
    status: PreparedEnvironmentStatus,
    status_transition: Sequence[str],
    cleanup_requested: bool,
    cleanup_action: str,
    active_index_result: str,
    eval_report: EvalReport | None = None,
) -> None:
    validation_payload: dict[str, Any] = {
        "source": validation.command_source,
        "mode": "fail_to_pass_plus_pass_to_pass" if validation.include_pass_to_pass else "fail_to_pass",
        "eval_script": validation.eval_script,
        "allowed_commands": list(validation.allowed_commands),
        "fail_to_pass": list(validation.fail_to_pass),
        "pass_to_pass": list(validation.pass_to_pass),
    }
    eval_payload = _eval_report_payload(eval_report)
    if eval_payload is not None:
        validation_payload["eval_report"] = eval_payload
    payload = _official_sandbox_payload(prepared=prepared, status=status, ready_checks=prepared.ready_checks)
    payload.update(
        {
            "prepared_environment": {
                "status_transition": list(status_transition),
                "sandbox_json": str(output_path / "sandbox.json"),
            },
            "validation": validation_payload,
            "cleanup": {
                "requested": cleanup_requested,
                "action": cleanup_action,
                "active_index_result": active_index_result,
            },
            "active_index": {
                "result": active_index_result,
            },
            "artifacts": _artifact_locations(output_path),
        }
    )
    (output_path / "sandbox.json").write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _write_official_summary(
    *,
    output_path: Path,
    summary: RunSummary,
    prepared: PreparedTaskEnvironment,
    validation: ValidationTestSet,
    patch: str,
    status_transition: Sequence[str],
    cleanup_requested: bool,
    cleanup_action: str,
    active_index_result: str,
    eval_report: EvalReport | None = None,
) -> RunSummary:
    rewritten = RunSummary(
        run_id=summary.run_id,
        instance_id=summary.instance_id,
        model_name=summary.model_name,
        status=summary.status,
        budget=summary.budget,
        changed_files=_changed_files_from_patch(patch) if patch else summary.changed_files,
        test_summary=summary.test_summary,
        error=summary.error,
        last_successful_tool_call=summary.last_successful_tool_call,
        artifacts=_artifact_locations(output_path),
        metadata=_runtime_metadata(
            prepared=prepared,
            validation=validation,
            status_transition=status_transition,
            output_path=output_path,
            cleanup_requested=cleanup_requested,
            cleanup_action=cleanup_action,
            active_index_result=active_index_result,
            eval_report=eval_report,
        ),
    )
    write_summary(output_path / "summary.json", rewritten)
    return rewritten


def _ensure_trajectory_json(*, output_path: Path, task_record: Any, patch: str, resolved: bool) -> None:
    jsonl_path = output_path / "trajectory.jsonl"
    if not jsonl_path.exists():
        jsonl_path.write_text("", encoding="utf-8")
    convert_trajectory_to_summary_format(
        trajectory_jsonl=jsonl_path,
        task_id=task_record.instance_id,
        issue=task_record.problem_statement,
        final_diff=patch,
        resolved=resolved,
        output_path=output_path / "trajectory.json",
    )


def _cleanup_prepared_environment(docker: DockerCli, prepared: PreparedTaskEnvironment) -> None:
    TaskSandboxManager(docker=docker).stop(_task_sandbox_from_prepared(prepared))


def _validate_active_prepared_environment(prepared: PreparedTaskEnvironment, task_record: Any) -> None:
    if prepared.instance_id != task_record.instance_id:
        raise SandboxedRunInputError("active prepared environment instance id does not match requested task")
    if prepared.repo != task_record.repo:
        raise SandboxedRunInputError("active prepared environment repo does not match requested task")
    if prepared.version != (task_record.version or ""):
        raise SandboxedRunInputError("active prepared environment repo version does not match requested task")
    if prepared.base_commit != task_record.base_commit:
        raise SandboxedRunInputError("active prepared environment base commit does not match requested task")
    if prepared.runtime_lineage.runtime_path != "official_style":
        raise SandboxedRunInputError("active prepared environment is not official_style")


def _validation_patch_files(test_patch: str) -> set[str]:
    return set(_changed_files_from_patch(test_patch)) if test_patch.strip() else set()


def filter_validation_patch_changes(final_patch: str, test_patch: str) -> str:
    """Remove validation-only files from an exported final diff."""
    validation_files = _validation_patch_files(test_patch)
    if not validation_files or not final_patch.strip():
        return final_patch
    kept_blocks: list[list[str]] = []
    current: list[str] = []
    current_file: str | None = None
    for line in final_patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current and current_file not in validation_files:
                kept_blocks.append(current)
            current = [line]
            parts = line.split()
            current_file = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else None
            continue
        current.append(line)
    if current and current_file not in validation_files:
        kept_blocks.append(current)
    return "".join("".join(block) for block in kept_blocks)


def _apply_validation_test_patch(docker: DockerCli, prepared: PreparedTaskEnvironment, test_patch: str) -> bool:
    if not test_patch.strip():
        return False
    docker.exec(
        prepared.container_name,
        ["sh", "-lc", f"git -C {prepared.repo_path} apply --whitespace=nowarn -"],
        stdin=test_patch,
    )
    return True


def _revert_validation_test_patch(docker: DockerCli, prepared: PreparedTaskEnvironment, test_patch: str) -> None:
    if not test_patch.strip():
        return
    docker.exec(
        prepared.container_name,
        ["sh", "-lc", f"git -C {prepared.repo_path} apply -R --whitespace=nowarn -"],
        stdin=test_patch,
    )


def _failure_eval_report(validation: ValidationTestSet, raw_output_artifact: str) -> EvalReport:
    return EvalReport(
        resolved=False,
        fail_to_pass_failure=validation.fail_to_pass,
        pass_to_pass_failure=validation.pass_to_pass,
        raw_output_artifact=raw_output_artifact,
    )


def _run_final_eval(
    *,
    docker: DockerCli,
    prepared: PreparedTaskEnvironment,
    validation: ValidationTestSet,
    test_patch: str,
    output_path: Path,
    timeout_seconds: int,
) -> EvalReport:
    eval_log = output_path / "eval.log"
    applied = _apply_validation_test_patch(docker, prepared, test_patch)
    try:
        result = docker.exec(
            prepared.container_name,
            ["bash", "-lc", f"cd {prepared.repo_path} && {validation.allowed_commands[0]}"],
            timeout_seconds=timeout_seconds,
        )
        raw_output = (result.stdout + ("\n" if result.stdout and result.stderr else "") + result.stderr).strip()
        eval_log.write_text(raw_output, encoding="utf-8")
        try:
            return parse_eval_report(
                raw_output,
                repo=prepared.repo,
                version=prepared.version,
                fail_to_pass=validation.fail_to_pass,
                pass_to_pass=validation.pass_to_pass,
                raw_output_artifact=str(eval_log),
            )
        except EvalOutputParseError:
            return _failure_eval_report(validation, str(eval_log))
    finally:
        if applied:
            _revert_validation_test_patch(docker, prepared, test_patch)


def run_prepared_swebench_runtime(
    *,
    dataset_path: str | Path,
    instance_id: str,
    docker: DockerCli,
    backend: ModelBackend,
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    active_index_path: str | Path = ".coding-agent/active-sandboxes.json",
    include_pass_to_pass: bool = False,
    cleanup: bool = False,
    arch: str = "x86_64",
) -> RunSummary:
    """Run the host-owned agent through an active official-style prepared environment."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    index_path = Path(active_index_path)
    task_record = normalize_benchmark_task_record(load_task_record(dataset_path, instance_id))
    testspec = build_adapted_testspec(task_record, arch=arch)
    validation = build_official_validation_set(testspec, include_pass_to_pass=include_pass_to_pass)
    prepared = _load_active_prepared_environment(index_path, instance_id)
    _validate_active_prepared_environment(prepared, task_record)
    ready_checks = _official_ready_checks(docker, prepared, testspec)
    prepared = replace(prepared, ready_checks=ready_checks)

    running = replace(prepared, status=PreparedEnvironmentStatus.RUNNING, sandbox_json=output_path / "sandbox.json")
    _save_active_prepared_environment(index_path, running)
    status_transition: list[str] = [PreparedEnvironmentStatus.READY.value, PreparedEnvironmentStatus.RUNNING.value]
    _write_official_sandbox_json(
        output_path=output_path,
        prepared=running,
        validation=validation,
        status=PreparedEnvironmentStatus.RUNNING,
        status_transition=status_transition,
        cleanup_requested=cleanup,
        cleanup_action="none",
        active_index_result="updated",
    )

    host_workspace = output_path / "_workspace_snapshot"
    host_workspace.mkdir(parents=True, exist_ok=True)
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
        container_name=prepared.container_name,
        repo_path=prepared.repo_path,
        allowed_test_commands=validation.allowed_commands,
        test_timeout_seconds=budget.test_timeout_seconds,
    )
    run_id = str(uuid.uuid4())
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
        error_prepared = replace(prepared, status=PreparedEnvironmentStatus.ERROR, sandbox_json=output_path / "sandbox.json")
        status_transition.append(PreparedEnvironmentStatus.ERROR.value)
        if cleanup:
            _cleanup_prepared_environment(docker, error_prepared)
            _remove_active_prepared_environment(index_path, instance_id)
            cleanup_action = "stop_remove"
            active_index_result = "removed"
        else:
            _save_active_prepared_environment(index_path, error_prepared)
            cleanup_action = "none"
            active_index_result = "retained_error"
        (output_path / "final.patch").write_text("", encoding="utf-8")
        write_prediction_from_patch(output_path / "prediction.jsonl", instance_id=task_record.instance_id, model_name=model_name, patch="")
        _ensure_trajectory_json(output_path=output_path, task_record=task_record, patch="", resolved=False)
        failure_summary = RunSummary(
            run_id=run_id,
            instance_id=task_record.instance_id,
            model_name=model_name,
            status=RunStatus.ERRORED,
            budget=budget,
            error=str(exc),
            artifacts=_artifact_locations(output_path),
        )
        failure_summary = _write_official_summary(
            output_path=output_path,
            summary=failure_summary,
            prepared=error_prepared,
            validation=validation,
            patch="",
            status_transition=status_transition,
            cleanup_requested=cleanup,
            cleanup_action=cleanup_action,
            active_index_result=active_index_result,
        )
        _write_official_sandbox_json(
            output_path=output_path,
            prepared=error_prepared,
            validation=validation,
            status=PreparedEnvironmentStatus.ERROR,
            status_transition=status_transition,
            cleanup_requested=cleanup,
            cleanup_action=cleanup_action,
            active_index_result=active_index_result,
        )
        return failure_summary

    eval_report = _run_final_eval(
        docker=docker,
        prepared=prepared,
        validation=validation,
        test_patch=task_record.test_patch,
        output_path=output_path,
        timeout_seconds=budget.test_timeout_seconds,
    )
    container_patch = export_prepared_environment_patch(
        docker,
        container_name=prepared.container_name,
        repo_path=prepared.repo_path,
    )
    final_patch = filter_validation_patch_changes(container_patch, task_record.test_patch)
    (output_path / "final.patch").write_text(final_patch, encoding="utf-8")
    write_prediction_from_patch(
        output_path / "prediction.jsonl",
        instance_id=task_record.instance_id,
        model_name=model_name,
        patch=final_patch,
    )
    _ensure_trajectory_json(
        output_path=output_path,
        task_record=task_record,
        patch=final_patch,
        resolved=eval_report.resolved,
    )

    terminal_status = (
        PreparedEnvironmentStatus.ERROR
        if summary.status is RunStatus.ERRORED
        else PreparedEnvironmentStatus.USED
    )
    status_transition.append(terminal_status.value)
    terminal_prepared = replace(prepared, status=terminal_status, sandbox_json=output_path / "sandbox.json")
    if cleanup and terminal_status is PreparedEnvironmentStatus.USED:
        status_transition.append(PreparedEnvironmentStatus.STOPPED.value)
        terminal_prepared = replace(terminal_prepared, status=PreparedEnvironmentStatus.STOPPED)
        _cleanup_prepared_environment(docker, terminal_prepared)
        _remove_active_prepared_environment(index_path, instance_id)
        cleanup_action = "stop_remove"
        active_index_result = "removed"
    elif cleanup:
        _cleanup_prepared_environment(docker, terminal_prepared)
        _remove_active_prepared_environment(index_path, instance_id)
        cleanup_action = "stop_remove"
        active_index_result = "removed"
    else:
        _save_active_prepared_environment(index_path, terminal_prepared)
        cleanup_action = "none"
        active_index_result = "retained_" + terminal_status.value

    summary = _write_official_summary(
        output_path=output_path,
        summary=summary,
        prepared=terminal_prepared,
        validation=validation,
        patch=final_patch,
        status_transition=status_transition,
        cleanup_requested=cleanup,
        cleanup_action=cleanup_action,
        active_index_result=active_index_result,
        eval_report=eval_report,
    )
    _write_official_sandbox_json(
        output_path=output_path,
        prepared=terminal_prepared,
        validation=validation,
        status=terminal_prepared.status,
        status_transition=status_transition,
        cleanup_requested=cleanup,
        cleanup_action=cleanup_action,
        active_index_result=active_index_result,
        eval_report=eval_report,
    )
    return summary


def _changed_files_from_patch(patch: str) -> list[str]:
    """Return changed file paths from a unified git diff."""
    changed: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3]
        changed.add(path[2:] if path.startswith("b/") else path)
    return sorted(changed)


def _export_container_patch(docker: DockerCli, sandbox: TaskSandbox) -> str:
    """Export repository changes made inside the task container."""
    return docker.exec(
        sandbox.container_name,
        ["git", "-C", sandbox.repo_path, "diff", "--binary"],
    ).stdout


def _apply_test_patch(docker: DockerCli, sandbox: TaskSandbox, test_patch: str) -> None:
    """Apply and stage SWE-Bench test_patch so validation tests exist but are not exported."""
    if not test_patch.strip():
        return
    docker.exec(
        sandbox.container_name,
        ["sh", "-lc", f"tr -d '\\r' | git -C {sandbox.repo_path} apply --whitespace=nowarn -"],
        stdin=test_patch,
    )
    docker.exec(sandbox.container_name, ["git", "-C", sandbox.repo_path, "add", "-A"])


def _base_image_from_dict(payload: Mapping[str, Any]) -> BaseImage:
    return BaseImage(
        repo=str(payload["repo"]),
        image=str(payload["image"]),
        repo_path=str(payload["repo_path"]),
        official_compatible=bool(payload.get("official_compatible", False)),
        compatibility_source=payload.get("compatibility_source"),
        validation_command_template=payload.get("validation_command_template"),
    )


def _sandbox_from_payload(payload: Mapping[str, Any]) -> TaskSandbox:
    return TaskSandbox(
        container_name=str(payload["container_name"]),
        base_image=_base_image_from_dict(payload["base_image"]),
        instance_id=str(payload["instance_id"]),
        repo=str(payload["repo"]),
        base_commit=str(payload["base_commit"]),
        repo_path=str(payload["repo_path"]),
        status=str(payload.get("status", "ready")),
    )


def load_active_sandbox(index_path: str | Path, instance_id: str) -> TaskSandbox:
    """Load the active sandbox for an instance id from the active sandbox index."""
    path = Path(index_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SandboxedRunInputError("active sandbox index does not exist") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SandboxedRunInputError(str(exc)) from exc
    entry = payload.get("sandboxes", {}).get(instance_id)
    if not entry:
        raise SandboxedRunInputError(f"active sandbox not found for instance id: {instance_id}")
    sandbox_json = Path(str(entry["sandbox_json"]))
    try:
        sandbox_payload = json.loads(sandbox_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SandboxedRunInputError(str(exc)) from exc
    return _sandbox_from_payload(sandbox_payload)


def save_active_sandbox(
    index_path: str | Path,
    sandbox: TaskSandbox,
    sandbox_json_path: str | Path,
    *,
    replace_existing: bool = False,
) -> None:
    """Record a prepared sandbox as the active sandbox for its instance id."""
    path = Path(index_path)
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = {"sandboxes": {}}
    except (OSError, json.JSONDecodeError) as exc:
        raise SandboxedRunInputError(str(exc)) from exc
    sandboxes = payload.setdefault("sandboxes", {})
    if sandbox.instance_id in sandboxes and not replace_existing:
        raise ValueError(f"{sandbox.instance_id} already has an active sandbox")
    sandboxes[sandbox.instance_id] = {
        "container_name": sandbox.container_name,
        "repo": sandbox.repo,
        "base_commit": sandbox.base_commit,
        "repo_path": sandbox.repo_path,
        "sandbox_json": str(Path(sandbox_json_path)),
        "status": sandbox.status,
        "base_image": {
            "repo": sandbox.base_image.repo,
            "image": sandbox.base_image.image,
            "repo_path": sandbox.base_image.repo_path,
            "official_compatible": sandbox.base_image.official_compatible,
            "compatibility_source": sandbox.base_image.compatibility_source,
            "validation_command_template": sandbox.base_image.validation_command_template,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _assert_active_slot_available(index_path: str | Path, instance_id: str, *, replace_existing: bool) -> None:
    if replace_existing:
        return
    path = Path(index_path)
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SandboxedRunInputError(str(exc)) from exc
    if instance_id in payload.get("sandboxes", {}):
        raise ValueError(f"{instance_id} already has an active sandbox")


def _collect_command(command: str) -> str:
    if "pytest" in command and "--collect-only" not in command:
        return f"{command} --collect-only"
    return command


def _ready_checks(docker: DockerCli, sandbox: TaskSandbox, validation: ValidationTestSet) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    docker.exec(sandbox.container_name, ["git", "-C", sandbox.repo_path, "rev-parse", "--is-inside-work-tree"])
    checks["container_exec"] = {"ok": True}
    head = docker.exec(
        sandbox.container_name,
        ["git", "-C", sandbox.repo_path, "rev-parse", "HEAD"],
    ).stdout.strip()
    checks["head_match"] = {"ok": head == sandbox.base_commit, "actual": head}
    if head != sandbox.base_commit:
        raise SandboxedRunInputError(f"container HEAD {head} does not match base commit {sandbox.base_commit}")
    docker.exec(sandbox.container_name, ["git", "-C", sandbox.repo_path, "diff", "--quiet"])
    checks["unstaged_diff"] = {"ok": True}
    collect = _collect_command(validation.allowed_commands[0])
    docker.exec(sandbox.container_name, ["sh", "-lc", f"cd {sandbox.repo_path} && {collect}"])
    checks["collect_only"] = {"ok": True, "command": collect}
    return checks


def _validate_prepared_sandbox(docker: DockerCli, sandbox: TaskSandbox) -> None:
    docker.exec(sandbox.container_name, ["git", "-C", sandbox.repo_path, "rev-parse", "--is-inside-work-tree"])
    head = docker.exec(
        sandbox.container_name,
        ["git", "-C", sandbox.repo_path, "rev-parse", "HEAD"],
    ).stdout.strip()
    if head != sandbox.base_commit:
        raise SandboxedRunInputError(f"container HEAD {head} does not match base commit {sandbox.base_commit}")
    docker.exec(sandbox.container_name, ["git", "-C", sandbox.repo_path, "diff", "--quiet"])


def prepare_swebench_sandbox(
    *,
    task_record: SwebenchTaskRecord,
    base_image: BaseImage,
    docker: DockerCli,
    output_dir: str | Path,
    include_pass_to_pass: bool = False,
    active_index_path: str | Path | None = None,
    replace_existing: bool = False,
) -> PreparedSandboxSummary:
    """Create and leave running a SWE-Bench sandbox prepared for solving."""
    if not base_image.official_compatible:
        raise SandboxedRunInputError("base image must be marked official_compatible")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    validation = validation_from_task(task_record, base_image, include_pass_to_pass=include_pass_to_pass)
    if active_index_path is not None:
        _assert_active_slot_available(
            active_index_path,
            task_record.instance_id,
            replace_existing=replace_existing,
        )
    manager = TaskSandboxManager(docker=docker)
    sandbox = manager.prepare(
        base_image=base_image,
        instance_id=task_record.instance_id,
        base_commit=task_record.base_commit,
        run_id=str(uuid.uuid4()),
    )
    test_patch_applied = False
    test_patch_staged = False
    ready_checks: dict[str, Any] = {}
    sandbox_json_path = output_path / "sandbox.json"
    try:
        _apply_test_patch(docker, sandbox, task_record.test_patch)
        test_patch_applied = bool(task_record.test_patch.strip())
        test_patch_staged = test_patch_applied
        ready_checks = _ready_checks(docker, sandbox, validation)
        ready_sandbox = replace(sandbox, status="ready")
        _write_sandbox_json(
            sandbox_json_path,
            ready_sandbox,
            validation,
            status="ready",
            test_patch_applied=test_patch_applied,
            test_patch_staged=test_patch_staged,
            ready_checks=ready_checks,
        )
        if active_index_path is not None:
            save_active_sandbox(
                active_index_path,
                ready_sandbox,
                sandbox_json_path,
                replace_existing=replace_existing,
            )
        return PreparedSandboxSummary(
            sandbox=ready_sandbox,
            validation_test_set=validation,
            sandbox_json=sandbox_json_path,
            status="ready",
            ready_checks=ready_checks,
        )
    except Exception:
        _write_sandbox_json(
            sandbox_json_path,
            sandbox,
            validation,
            status="error",
            test_patch_applied=test_patch_applied,
            test_patch_staged=test_patch_staged,
            ready_checks=ready_checks,
        )
        raise


def solve_prepared_sandbox(
    *,
    task_record: SwebenchTaskRecord,
    sandbox: TaskSandbox,
    docker: DockerCli,
    backend: ModelBackend,
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    include_pass_to_pass: bool = False,
    cleanup: bool = False,
) -> RunSummary:
    """Run the coding agent inside an already prepared SWE-Bench sandbox."""
    if sandbox.instance_id != task_record.instance_id:
        raise SandboxedRunInputError("active sandbox instance id does not match requested task")
    if sandbox.base_commit != task_record.base_commit:
        raise SandboxedRunInputError("active sandbox base commit does not match requested task")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    host_workspace = output_path / "_workspace_snapshot"
    host_workspace.mkdir(parents=True, exist_ok=True)
    validation = validation_from_task(task_record, sandbox.base_image, include_pass_to_pass=include_pass_to_pass)
    manager = TaskSandboxManager(docker=docker)
    run_id = str(uuid.uuid4())
    _validate_prepared_sandbox(docker, sandbox)
    running_sandbox = replace(sandbox, status="running")
    _write_sandbox_json(
        output_path / "sandbox.json",
        running_sandbox,
        validation,
        status="running",
        test_patch_applied=bool(task_record.test_patch.strip()),
        test_patch_staged=bool(task_record.test_patch.strip()),
    )
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
        if cleanup:
            manager.stop(sandbox)
        raise
    except Exception as exc:
        failure_summary = _write_runtime_failure_artifacts(
            output_dir=output_path,
            run_id=run_id,
            task_record=task_record,
            sandbox=replace(sandbox, status="error"),
            validation=validation,
            budget=budget,
            model_name=model_name,
            error=exc,
        )
        if cleanup:
            manager.stop(sandbox)
        return failure_summary
    container_patch = _export_container_patch(docker, sandbox)
    used_sandbox = replace(sandbox, status="used")
    summary = RunSummary(
        run_id=summary.run_id,
        instance_id=summary.instance_id,
        model_name=summary.model_name,
        status=summary.status,
        budget=summary.budget,
        changed_files=_changed_files_from_patch(container_patch) if container_patch else summary.changed_files,
        test_summary=summary.test_summary,
        error=summary.error,
        last_successful_tool_call=summary.last_successful_tool_call,
        artifacts={**summary.artifacts, "sandbox": str(output_path / "sandbox.json")},
        sandbox=SandboxMetadata(task_sandbox=used_sandbox, validation_test_set=validation),
    )
    write_summary(output_path / "summary.json", summary)
    if container_patch:
        summary = _rewrite_patch_artifacts(
            output_path=output_path,
            task_record=task_record,
            summary=summary,
            sandbox=used_sandbox,
            validation=validation,
            model_name=model_name,
            patch=container_patch,
        )
    _write_sandbox_json(
        output_path / "sandbox.json",
        used_sandbox,
        validation,
        status="used",
        test_patch_applied=bool(task_record.test_patch.strip()),
        test_patch_staged=bool(task_record.test_patch.strip()),
    )
    if cleanup:
        manager.stop(sandbox)
    return summary


def _rewrite_patch_artifacts(
    *,
    output_path: Path,
    task_record: SwebenchTaskRecord,
    summary: RunSummary,
    sandbox: TaskSandbox,
    validation: ValidationTestSet,
    model_name: str,
    patch: str,
) -> RunSummary:
    """Replace host placeholder patch artifacts with the container diff."""
    (output_path / "final.patch").write_bytes(patch.encode("utf-8"))
    write_prediction_jsonl(output_path / "prediction.jsonl", Prediction(task_record.instance_id, model_name, patch))
    convert_trajectory_to_summary_format(
        trajectory_jsonl=output_path / "trajectory.jsonl",
        task_id=task_record.instance_id,
        issue=task_record.problem_statement,
        final_diff=patch,
        resolved=summary.status is RunStatus.SOLVED,
        output_path=output_path / "trajectory.json",
    )
    rewritten = RunSummary(
        run_id=summary.run_id,
        instance_id=summary.instance_id,
        model_name=summary.model_name,
        status=summary.status,
        budget=summary.budget,
        changed_files=_changed_files_from_patch(patch),
        test_summary=summary.test_summary,
        error=summary.error,
        last_successful_tool_call=summary.last_successful_tool_call,
        artifacts={**summary.artifacts, "sandbox": str(output_path / "sandbox.json")},
        sandbox=SandboxMetadata(task_sandbox=sandbox, validation_test_set=validation),
    )
    write_summary(output_path / "summary.json", rewritten)
    return rewritten


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
    """运行期异常时写入可审计的失败产物。

    一旦 agent loop 已经开始，调用方通常需要 summary/prediction/sandbox 等文件来判断
    失败位置。因此这里即使 patch 为空，也会尽力写完整的失败摘要。
    """
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


def _safe_instance_dir(instance_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in instance_id).strip("-")
    return safe or "instance"


def parse_instance_id_file(path: str | Path) -> tuple[str, ...]:
    """Read one instance id per line, ignoring blank lines and comment lines."""
    source = Path(path)
    try:
        instance_ids = tuple(
            line.strip()
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    except OSError as exc:
        raise SandboxedRunInputError(str(exc)) from exc
    if not instance_ids:
        raise SandboxedRunInputError("instance-id-file must contain at least one instance id")
    return instance_ids


def _state_path(output_dir: str | Path, state_path: str | Path | None) -> Path:
    return Path(state_path) if state_path is not None else Path(output_dir) / "batch_state.json"


def _load_batch_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "tasks": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SandboxedRunInputError(str(exc)) from exc
    payload.setdefault("version", 1)
    payload.setdefault("tasks", {})
    return payload


def _write_batch_state(path: Path, payload: Mapping[str, Any]) -> None:
    state = dict(payload)
    tasks = dict(state.get("tasks", {}))
    status_counts: dict[str, int] = {}
    for task in tasks.values():
        status = str(task.get("status", "pending"))
        status_counts[status] = status_counts.get(status, 0) + 1
    state["total"] = len(tasks)
    state["statuses"] = status_counts
    state["updated_at"] = utc_now().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")


def _update_batch_task(path: Path, lock: Lock, instance_id: str, **fields: Any) -> None:
    with lock:
        state = _load_batch_state(path)
        tasks = state.setdefault("tasks", {})
        entry = dict(tasks.get(instance_id, {}))
        entry.update(fields)
        entry["updated_at"] = utc_now().isoformat()
        tasks[instance_id] = entry
        _write_batch_state(path, state)


def _initialize_batch_state(
    *,
    path: Path,
    lock: Lock,
    task_records: Sequence[SwebenchTaskRecord],
    output_dir: Path,
) -> None:
    with lock:
        state = _load_batch_state(path)
        tasks = state.setdefault("tasks", {})
        for record in task_records:
            entry = dict(tasks.get(record.instance_id, {}))
            entry.setdefault("instance_id", record.instance_id)
            entry.setdefault("repo", record.repo)
            entry.setdefault("base_commit", record.base_commit)
            entry.setdefault("status", "pending")
            entry.setdefault("prepare_dir", str(output_dir / _safe_instance_dir(record.instance_id) / "prepare"))
            entry.setdefault("solve_dir", str(output_dir / _safe_instance_dir(record.instance_id) / "solve"))
            tasks[record.instance_id] = entry
        _write_batch_state(path, state)


def _load_records_for_batch(
    *,
    task_records: Sequence[SwebenchTaskRecord] | None,
    dataset_path: str | Path | None,
    instance_ids: Sequence[str],
) -> tuple[SwebenchTaskRecord, ...]:
    if task_records is not None:
        records = tuple(task_records)
    else:
        if dataset_path is None:
            raise SandboxedRunInputError("dataset is required")
        records = tuple(load_task_records(dataset_path, instance_ids))
    if not records:
        raise SandboxedRunInputError("at least one instance id is required")
    seen_instance_ids: set[str] = set()
    duplicate_instance_ids: list[str] = []
    for record in records:
        if record.instance_id in seen_instance_ids and record.instance_id not in duplicate_instance_ids:
            duplicate_instance_ids.append(record.instance_id)
        seen_instance_ids.add(record.instance_id)
    if duplicate_instance_ids:
        raise SandboxedRunInputError("duplicate instance id: " + ", ".join(duplicate_instance_ids))
    return records


def prepare_swebench_sandboxes(
    *,
    task_records: Sequence[SwebenchTaskRecord] | None = None,
    dataset_path: str | Path | None = None,
    instance_ids: Sequence[str] = (),
    registry_path: str | Path | None = None,
    base_images: Mapping[str, BaseImage] | None = None,
    docker: DockerCli,
    output_dir: str | Path,
    state_path: str | Path | None = None,
    active_index_path: str | Path = ".coding-agent/active-sandboxes.json",
    jobs: int = 1,
    include_pass_to_pass: bool = False,
    replace_existing: bool = False,
) -> int:
    """Prepare many reusable SWE-Bench sandboxes in one process with locked state writes."""
    if jobs <= 0:
        raise SandboxedRunInputError("jobs must be a positive integer")
    records = _load_records_for_batch(task_records=task_records, dataset_path=dataset_path, instance_ids=instance_ids)
    images_by_repo = _load_base_images_for_records(
        task_records=records,
        registry_path=registry_path,
        base_images=base_images,
    )
    for record in records:
        validation_from_task(record, images_by_repo[record.repo], include_pass_to_pass=include_pass_to_pass)
    active_index = Path(active_index_path)
    if not replace_existing:
        for record in records:
            _assert_active_slot_available(active_index, record.instance_id, replace_existing=False)

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    state = _state_path(root, state_path)
    state_lock = Lock()
    active_lock = Lock()
    _initialize_batch_state(path=state, lock=state_lock, task_records=records, output_dir=root)

    def prepare_one(record: SwebenchTaskRecord) -> dict[str, Any]:
        prepare_dir = root / _safe_instance_dir(record.instance_id) / "prepare"
        current_state = _load_batch_state(state)
        current_status = current_state.get("tasks", {}).get(record.instance_id, {}).get("status")
        if current_status in {"ready", "solving", "solved"}:
            return {"instance_id": record.instance_id, "status": current_status, "error": None}
        _update_batch_task(state, state_lock, record.instance_id, status="preparing", prepare_dir=str(prepare_dir), last_error=None)
        try:
            prepared = prepare_swebench_sandbox(
                task_record=record,
                base_image=images_by_repo[record.repo],
                docker=docker,
                output_dir=prepare_dir,
                include_pass_to_pass=include_pass_to_pass,
            )
            with active_lock:
                save_active_sandbox(
                    active_index,
                    prepared.sandbox,
                    prepared.sandbox_json,
                    replace_existing=replace_existing,
                )
            _update_batch_task(
                state,
                state_lock,
                record.instance_id,
                status="ready",
                container_name=prepared.sandbox.container_name,
                sandbox_json=str(prepared.sandbox_json),
                last_error=None,
            )
            return {"instance_id": record.instance_id, "status": "ready", "error": None}
        except Exception as exc:
            _update_batch_task(state, state_lock, record.instance_id, status="errored", last_error=str(exc))
            return {"instance_id": record.instance_id, "status": "errored", "error": str(exc)}

    max_workers = min(jobs, len(records))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(prepare_one, record) for record in records]
        for future in as_completed(futures):
            results.append(future.result())
    return 4 if any(result["status"] == "errored" for result in results) else 0


def solve_swebench_sandboxes(
    *,
    task_records: Sequence[SwebenchTaskRecord] | None = None,
    dataset_path: str | Path | None = None,
    instance_ids: Sequence[str] = (),
    docker: DockerCli,
    backend_factory: Callable[[], ModelBackend],
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    state_path: str | Path | None = None,
    active_index_path: str | Path = ".coding-agent/active-sandboxes.json",
    jobs: int = 1,
    include_pass_to_pass: bool = False,
    cleanup: bool = False,
) -> int:
    """Solve many prepared SWE-Bench sandboxes, using the batch state for resumable skips."""
    if jobs <= 0:
        raise SandboxedRunInputError("jobs must be a positive integer")
    records = _load_records_for_batch(task_records=task_records, dataset_path=dataset_path, instance_ids=instance_ids)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    state = _state_path(root, state_path)
    state_lock = Lock()
    active_lock = Lock()
    _initialize_batch_state(path=state, lock=state_lock, task_records=records, output_dir=root)

    def solve_one(record: SwebenchTaskRecord) -> dict[str, Any]:
        solve_dir = root / _safe_instance_dir(record.instance_id) / "solve"
        current_state = _load_batch_state(state)
        current_status = current_state.get("tasks", {}).get(record.instance_id, {}).get("status")
        if current_status == "solved":
            return {"instance_id": record.instance_id, "status": "solved", "error": None}
        _update_batch_task(state, state_lock, record.instance_id, status="solving", solve_dir=str(solve_dir), last_error=None)
        try:
            with active_lock:
                sandbox = load_active_sandbox(active_index_path, record.instance_id)
            summary = solve_prepared_sandbox(
                task_record=record,
                sandbox=sandbox,
                docker=docker,
                backend=backend_factory(),
                budget=budget,
                model_name=model_name,
                output_dir=solve_dir,
                include_pass_to_pass=include_pass_to_pass,
                cleanup=cleanup,
            )
            _update_batch_task(
                state,
                state_lock,
                record.instance_id,
                status=summary.status.value,
                solve_dir=str(solve_dir),
                last_error=summary.error,
            )
            return {"instance_id": record.instance_id, "status": summary.status.value, "error": summary.error}
        except ArtifactPersistenceError as exc:
            _update_batch_task(state, state_lock, record.instance_id, status="artifact_error", last_error=str(exc))
            return {"instance_id": record.instance_id, "status": "artifact_error", "error": str(exc)}
        except Exception as exc:
            _update_batch_task(state, state_lock, record.instance_id, status="errored", last_error=str(exc))
            return {"instance_id": record.instance_id, "status": "errored", "error": str(exc)}

    max_workers = min(jobs, len(records))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(solve_one, record) for record in records]
        for future in as_completed(futures):
            results.append(future.result())
    if any(result["status"] == "artifact_error" for result in results):
        return 3
    return 4 if any(result["status"] == "errored" for result in results) else 0


def _load_base_images_for_records(
    *,
    task_records: Sequence[SwebenchTaskRecord],
    registry_path: str | Path | None,
    base_images: Mapping[str, BaseImage] | None,
) -> dict[str, BaseImage]:
    if base_images is not None:
        images = dict(base_images)
        required_repos = {record.repo for record in task_records}
        missing = sorted(repo for repo in required_repos if repo not in images)
        if missing:
            raise SandboxedRunInputError("base image not provided for repo: " + ", ".join(missing))
        for repo in required_repos:
            image = images[repo]
            if not image.official_compatible:
                raise SandboxedRunInputError("base image must be marked official_compatible")
        return images
    if registry_path is None:
        raise SandboxedRunInputError("registry is required")
    return {
        repo: load_base_image_from_registry(registry_path, repo)
        for repo in sorted({record.repo for record in task_records})
    }


def _prediction_from_run_dir(run_dir: Path, instance_id: str, model_name: str) -> Prediction:
    prediction_path = run_dir / "prediction.jsonl"
    if not prediction_path.is_file():
        return Prediction(instance_id, model_name, "")
    for line in prediction_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        return Prediction(
            instance_id=str(payload.get("instance_id", instance_id)),
            model_name_or_path=str(payload.get("model_name_or_path", model_name)),
            model_patch=str(payload.get("model_patch", "")),
        )
    return Prediction(instance_id, model_name, "")


def run_swebench_tasks(
    *,
    task_records: Sequence[SwebenchTaskRecord] | None = None,
    dataset_path: str | Path | None = None,
    instance_ids: Sequence[str] = (),
    registry_path: str | Path | None = None,
    base_images: Mapping[str, BaseImage] | None = None,
    docker: DockerCli,
    backend_factory: Callable[[], ModelBackend],
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    jobs: int = 1,
    include_pass_to_pass: bool = False,
) -> int:
    """Run multiple SWE-Bench tasks with independent sandboxes and artifacts."""
    if jobs <= 0:
        raise SandboxedRunInputError("jobs must be a positive integer")
    if task_records is None:
        if dataset_path is None:
            raise SandboxedRunInputError("dataset is required")
        records = tuple(load_task_records(dataset_path, instance_ids))
    else:
        records = tuple(task_records)
    if not records:
        raise SandboxedRunInputError("at least one instance id is required")
    seen_instance_ids: set[str] = set()
    duplicate_instance_ids: list[str] = []
    for record in records:
        if record.instance_id in seen_instance_ids and record.instance_id not in duplicate_instance_ids:
            duplicate_instance_ids.append(record.instance_id)
        seen_instance_ids.add(record.instance_id)
    if duplicate_instance_ids:
        raise SandboxedRunInputError("duplicate instance id: " + ", ".join(duplicate_instance_ids))

    images_by_repo = _load_base_images_for_records(
        task_records=records,
        registry_path=registry_path,
        base_images=base_images,
    )
    for record in records:
        validation_from_task(record, images_by_repo[record.repo], include_pass_to_pass=include_pass_to_pass)

    root = Path(output_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 3
    max_workers = min(jobs, len(records))
    results: dict[str, dict[str, Any]] = {}

    def run_one(record: SwebenchTaskRecord) -> dict[str, Any]:
        run_dir = root / _safe_instance_dir(record.instance_id)
        try:
            summary = run_swebench_task(
                task_record=record,
                base_image=images_by_repo[record.repo],
                docker=docker,
                backend=backend_factory(),
                budget=budget,
                model_name=model_name,
                output_dir=run_dir,
                include_pass_to_pass=include_pass_to_pass,
            )
            return {
                "instance_id": record.instance_id,
                "status": summary.status.value,
                "error": summary.error,
                "output_dir": str(run_dir),
                "artifact_error": False,
                "runtime_error": summary.status is RunStatus.ERRORED,
            }
        except ArtifactPersistenceError as exc:
            return {
                "instance_id": record.instance_id,
                "status": "artifact_error",
                "error": str(exc),
                "output_dir": str(run_dir),
                "artifact_error": True,
                "runtime_error": False,
            }
        except Exception as exc:
            return {
                "instance_id": record.instance_id,
                "status": "errored",
                "error": str(exc),
                "output_dir": str(run_dir),
                "artifact_error": False,
                "runtime_error": True,
            }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_record = {pool.submit(run_one, record): record for record in records}
        for future in as_completed(future_to_record):
            record = future_to_record[future]
            results[record.instance_id] = future.result()

    ordered_results = [results[record.instance_id] for record in records]
    status_counts: dict[str, int] = {}
    for result in ordered_results:
        status = str(result["status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    try:
        predictions = [
            _prediction_from_run_dir(Path(result["output_dir"]), result["instance_id"], model_name)
            for result in ordered_results
        ]
        write_predictions_jsonl(root / "prediction.jsonl", predictions)
        (root / "batch_summary.json").write_text(
            json.dumps(
                {
                    "total": len(ordered_results),
                    "jobs": jobs,
                    "statuses": status_counts,
                    "tasks": ordered_results,
                },
                indent=2,
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
    except OSError:
        return 3

    if any(result["artifact_error"] for result in ordered_results):
        return 3
    if any(result["runtime_error"] for result in ordered_results):
        return 4
    return 0


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
    """在 Docker 沙箱中运行一个 SWE-Bench 任务。

    该函数是宿主侧编排入口：它加载验证命令、准备容器、把 ContainerToolExecutor 注入
    通用 agent loop，并在成功或失败后清理容器。
    """
    prepared = prepare_swebench_sandbox(
        task_record=task_record,
        base_image=base_image,
        docker=docker,
        output_dir=output_dir,
        include_pass_to_pass=include_pass_to_pass,
    )
    return solve_prepared_sandbox(
        task_record=task_record,
        sandbox=prepared.sandbox,
        docker=docker,
        backend=backend,
        budget=budget,
        model_name=model_name,
        output_dir=output_dir,
        include_pass_to_pass=include_pass_to_pass,
        cleanup=True,
    )


def load_base_image_from_registry(path: str | Path, repo: str) -> BaseImage:
    """为 swebench run 加载并校验基础镜像。"""
    try:
        base_image = registry_load_base_image(path, repo, require_runnable=False)
        if not base_image.official_compatible:
            raise SandboxedRunInputError("base image must be marked official_compatible")
        return base_image
    except SandboxRegistryError as exc:
        raise SandboxedRunInputError(str(exc)) from exc
