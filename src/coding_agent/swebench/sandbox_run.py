from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any

from coding_agent.agent import AgentConfig, ArtifactPersistenceError, ToolAgent
from coding_agent.models import (
    BaseImage,
    BenchmarkTask,
    PreparedEnvironmentStatus,
    PreparedTaskEnvironment,
    Prediction,
    RunBudget,
    RunStatus,
    RunSummary,
    RuntimeLineage,
    TaskSandbox,
    ValidationTestSet,
    EvalReport,
    utc_now,
)
from coding_agent.sandbox_manager import DockerCli, DockerCommandError, DockerCommandTimeout, TaskSandboxManager
from coding_agent.tools.container_executor import ContainerToolExecutor, install_tool_scripts
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
from coding_agent.swebench.validation import build_official_validation_set
from coding_agent.trajectory_exporter import convert_trajectory_to_summary_format, write_summary


logger = logging.getLogger(__name__)


class SandboxedRunInputError(ValueError):
    """模型执行前发现沙箱输入无效时抛出。"""


class SandboxedRunRuntimeError(RuntimeError):
    """模型执行已经开始，且已尽量保留部分产物后抛出。"""

    def __init__(self, summary: RunSummary) -> None:
        self.summary = summary
        super().__init__(summary.error or "sandboxed run failed")


SELF_TEST_COMMAND_GUIDANCE = (
    "test/test_file.py::test_name",
    "test/rules/",
    "test/rules/std_test.py test/rules/yaml_test_cases_test.py",
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
    logger.info("prepared environment ready checks started: instance_id=%s container=%s", prepared.instance_id, prepared.container_name)
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
    logger.info("prepared environment ready checks completed: instance_id=%s base_commit=%s", prepared.instance_id, head)
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
    logger.info(
        "official runtime prepare started: instance_id=%s dataset=%s output_dir=%s build_missing=%s replace_existing=%s arch=%s",
        instance_id,
        dataset_path,
        output_dir,
        build_missing,
        replace_existing,
        arch,
    )
    output_path = Path(output_dir)
    index_path = Path(active_index_path)
    logger.info("checking active prepared slot: instance_id=%s index=%s", instance_id, index_path)
    index_payload = _assert_prepared_slot_available(index_path, instance_id, replace_existing=replace_existing)
    old_entry = index_payload.get("prepared_environments", {}).get(instance_id)

    logger.info("loading SWE-Bench task record: instance_id=%s dataset=%s", instance_id, dataset_path)
    task_record = normalize_benchmark_task_record(load_task_record(dataset_path, instance_id))
    logger.info(
        "loaded SWE-Bench task record: instance_id=%s repo=%s version=%s base_commit=%s",
        task_record.instance_id,
        task_record.repo,
        task_record.version,
        task_record.base_commit,
    )
    logger.info("building adapted TestSpec: instance_id=%s arch=%s", task_record.instance_id, arch)
    testspec = build_adapted_testspec(task_record, arch=arch)
    image_plan = inspect_image_graph(testspec, docker=docker, build_missing=build_missing)
    built_images = build_missing_images(testspec, docker=docker, plan=image_plan) if image_plan.missing_images else ()
    if old_entry and replace_existing and old_entry.get("container_name"):
        logger.info("replacing existing prepared environment: instance_id=%s old_container=%s", instance_id, old_entry["container_name"])
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
    logger.info("creating prepared task container: instance_id=%s image=%s", task_record.instance_id, testspec.instance_image_key)
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
    logger.info("writing prepare sandbox metadata: instance_id=%s path=%s", task_record.instance_id, sandbox_json_path)
    sandbox_json_path.write_text(
        json.dumps(_official_sandbox_payload(prepared=prepared, status=prepared.status, ready_checks=ready_checks), indent=2),
        encoding="utf-8",
    )
    _save_active_prepared_environment(index_path, prepared)
    logger.info("official runtime prepare completed: instance_id=%s container=%s", task_record.instance_id, prepared.container_name)
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
    if eval_report is not None and eval_report.resolved:
        benchmark_status = RunStatus.SOLVED
    elif eval_report is not None and summary.status is RunStatus.SOLVED:
        benchmark_status = RunStatus.INCOMPLETE
    else:
        benchmark_status = summary.status
    benchmark_error = None if benchmark_status is RunStatus.SOLVED else summary.error
    metadata = _runtime_metadata(
        prepared=prepared,
        validation=validation,
        status_transition=status_transition,
        output_path=output_path,
        cleanup_requested=cleanup_requested,
        cleanup_action=cleanup_action,
        active_index_result=active_index_result,
        eval_report=eval_report,
    )
    if "self_test_coverage" in summary.metadata:
        metadata["self_test_coverage"] = summary.metadata["self_test_coverage"]
    else:
        metadata["self_test_coverage"] = _default_self_test_coverage(summary.test_summary)
    metadata["agent_status"] = summary.status.value
    metadata["agent_error"] = summary.error
    rewritten = RunSummary(
        run_id=summary.run_id,
        instance_id=summary.instance_id,
        model_name=summary.model_name,
        status=benchmark_status,
        budget=summary.budget,
        changed_files=_changed_files_from_patch(patch) if patch else summary.changed_files,
        test_summary=summary.test_summary,
        error=benchmark_error,
        last_successful_tool_call=summary.last_successful_tool_call,
        artifacts=_artifact_locations(output_path),
        metadata=metadata,
    )
    write_summary(output_path / "summary.json", rewritten)
    return rewritten


def _default_self_test_coverage(test_summary: Mapping[str, int]) -> dict[str, dict[str, int]]:
    statuses = ("passed", "failed", "rejected", "timeout", "execution_error")
    empty = {status: 0 for status in statuses}
    return {
        "existing_tests": {
            status: int(test_summary.get(status, 0))
            for status in statuses
        },
        "self_authored_tests": dict(empty),
        "diagnostic_tests": dict(empty),
    }


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
    logger.info("cleanup prepared environment started: instance_id=%s container=%s", prepared.instance_id, prepared.container_name)
    TaskSandboxManager(docker=docker).stop(_task_sandbox_from_prepared(prepared))
    logger.info("cleanup prepared environment completed: instance_id=%s container=%s", prepared.instance_id, prepared.container_name)


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
    logger.info("official final eval started: instance_id=%s log=%s", prepared.instance_id, eval_log)
    try:
        result = docker.exec(
            prepared.container_name,
            ["bash", "-lc", f"cd {prepared.repo_path} && {validation.allowed_commands[0]}"],
            timeout_seconds=timeout_seconds,
        )
    except DockerCommandError as exc:
        result = exc.result
    except DockerCommandTimeout as exc:
        raw_output = f"official eval command timed out: {exc}"
        eval_log.write_text(raw_output, encoding="utf-8")
        return _failure_eval_report(validation, str(eval_log))
    except Exception as exc:
        raw_output = f"official eval command failed: {exc}"
        eval_log.write_text(raw_output, encoding="utf-8")
        return _failure_eval_report(validation, str(eval_log))
    raw_output = (result.stdout + ("\n" if result.stdout and result.stderr else "") + result.stderr).strip()
    eval_log.write_text(raw_output, encoding="utf-8")
    try:
        report = parse_eval_report(
            raw_output,
            repo=prepared.repo,
            version=prepared.version,
            fail_to_pass=validation.fail_to_pass,
            pass_to_pass=validation.pass_to_pass,
            raw_output_artifact=str(eval_log),
        )
        logger.info(
            "official final eval completed: instance_id=%s resolved=%s fail_success=%s fail_failure=%s pass_success=%s pass_failure=%s",
            prepared.instance_id,
            report.resolved,
            len(report.fail_to_pass_success),
            len(report.fail_to_pass_failure),
            len(report.pass_to_pass_success),
            len(report.pass_to_pass_failure),
        )
        return report
    except EvalOutputParseError:
        logger.warning("official final eval output could not be parsed: instance_id=%s log=%s", prepared.instance_id, eval_log)
        return _failure_eval_report(validation, str(eval_log))


def run_prepared_swebench_runtime(
    *,
    dataset_path: str | Path,
    instance_id: str,
    docker: DockerCli,
    backend: Any,
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    active_index_path: str | Path = ".coding-agent/active-sandboxes.json",
    include_pass_to_pass: bool = False,
    cleanup: bool = False,
    arch: str = "x86_64",
) -> RunSummary:
    """Run the host-owned agent through an active official-style prepared environment."""
    logger.info(
        "official runtime run started: instance_id=%s dataset=%s output_dir=%s cleanup=%s include_pass_to_pass=%s",
        instance_id,
        dataset_path,
        output_dir,
        cleanup,
        include_pass_to_pass,
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    index_path = Path(active_index_path)
    task_record = normalize_benchmark_task_record(load_task_record(dataset_path, instance_id))
    testspec = build_adapted_testspec(task_record, arch=arch)
    validation = build_official_validation_set(testspec, include_pass_to_pass=include_pass_to_pass)
    logger.info(
        "official validation set built: instance_id=%s fail_to_pass=%s pass_to_pass=%s",
        task_record.instance_id,
        len(validation.fail_to_pass),
        len(validation.pass_to_pass),
    )
    prepared = _load_active_prepared_environment(index_path, instance_id)
    logger.info("loaded active prepared environment: instance_id=%s container=%s status=%s", instance_id, prepared.container_name, prepared.status.value)
    _validate_active_prepared_environment(prepared, task_record)
    ready_checks = _official_ready_checks(docker, prepared, testspec)
    prepared = replace(prepared, ready_checks=ready_checks)

    running = replace(prepared, status=PreparedEnvironmentStatus.RUNNING, sandbox_json=output_path / "sandbox.json")
    _save_active_prepared_environment(index_path, running)
    status_transition: list[str] = [PreparedEnvironmentStatus.READY.value, PreparedEnvironmentStatus.RUNNING.value]
    logger.info("prepared environment status transition: instance_id=%s %s", instance_id, " -> ".join(status_transition))
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
        allowed_test_commands=SELF_TEST_COMMAND_GUIDANCE,
        fail_to_pass=validation.fail_to_pass,
        repo=task_record.repo,
        base_commit=task_record.base_commit,
    )
    executor = ContainerToolExecutor(
        docker=docker,
        container_name=prepared.container_name,
        repo_path=prepared.repo_path,
    )
    install_tool_scripts(prepared.container_name, docker)
    run_id = str(uuid.uuid4())
    try:
        logger.info("agent run started: instance_id=%s run_id=%s model=%s", task_record.instance_id, run_id, model_name)
        template_dir = Path(__file__).resolve().parents[1] / "config" / "templates"
        agent = ToolAgent(
            model=backend,
            executor=executor,
            config=AgentConfig(
                system_template=(template_dir / "system.j2").read_text(encoding="utf-8"),
                instance_template=(template_dir / "instance.j2").read_text(encoding="utf-8"),
                step_limit=budget.max_steps,
                time_limit_seconds=budget.timeout_seconds,
                test_timeout_seconds=budget.test_timeout_seconds,
                output_path=output_path,
            ),
        )
        if not getattr(agent.model, "model_name", ""):
            agent.model.model_name = model_name
        summary = agent.run(task)
        if summary.error == "AgentException":
            raise RuntimeError("agent execution failed")
        logger.info("agent run completed: instance_id=%s run_id=%s status=%s", task_record.instance_id, run_id, summary.status.value)
    except ArtifactPersistenceError:
        raise
    except Exception as exc:
        logger.exception("agent run failed after start: instance_id=%s run_id=%s", task_record.instance_id, run_id)
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
    logger.info(
        "exported final patch: instance_id=%s raw_bytes=%s filtered_bytes=%s",
        task_record.instance_id,
        len(container_patch.encode("utf-8")),
        len(final_patch.encode("utf-8")),
    )
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
    logger.info("prepared environment terminal status: instance_id=%s status=%s", instance_id, terminal_status.value)
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
    logger.info(
        "official runtime run completed: instance_id=%s status=%s active_index=%s cleanup_action=%s",
        instance_id,
        summary.status.value,
        active_index_result,
        cleanup_action,
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


def _safe_instance_dir(instance_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in instance_id).strip("-")
    return safe or "instance"


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


def _load_all_records_from_datasets(dataset_paths: Sequence[str | Path]) -> tuple[tuple[Path, SwebenchTaskRecord], ...]:
    paths = tuple(Path(path) for path in dataset_paths)
    if not paths:
        raise SandboxedRunInputError("at least one dataset is required")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SandboxedRunInputError("pyarrow is required to read parquet datasets") from exc

    loaded: list[tuple[Path, SwebenchTaskRecord]] = []
    seen_instance_ids: set[str] = set()
    duplicates: list[str] = []
    for path in paths:
        if not path.is_file():
            raise SandboxedRunInputError(f"dataset does not exist: {path}")
        for row in pq.read_table(path).to_pylist():
            record = SwebenchTaskRecord.from_row(row)
            if record.instance_id in seen_instance_ids and record.instance_id not in duplicates:
                duplicates.append(record.instance_id)
            seen_instance_ids.add(record.instance_id)
            loaded.append((path, record))
    if duplicates:
        raise SandboxedRunInputError("duplicate instance id: " + ", ".join(duplicates))
    if not loaded:
        raise SandboxedRunInputError("at least one task record is required")
    return tuple(loaded)


def _initialize_official_batch_state(
    *,
    path: Path,
    lock: Lock,
    records: Sequence[tuple[Path, SwebenchTaskRecord]],
    output_dir: Path,
) -> None:
    with lock:
        state = _load_batch_state(path)
        state["datasets"] = [str(dataset_path) for dataset_path, _record in records]
        tasks = state.setdefault("tasks", {})
        for dataset_path, record in records:
            entry = dict(tasks.get(record.instance_id, {}))
            entry.setdefault("instance_id", record.instance_id)
            entry.setdefault("repo", record.repo)
            entry.setdefault("base_commit", record.base_commit)
            entry.setdefault("dataset", str(dataset_path))
            entry.setdefault("status", "pending")
            entry.setdefault("prepare_dir", str(output_dir / _safe_instance_dir(record.instance_id) / "prepare"))
            entry.setdefault("run_dir", str(output_dir / _safe_instance_dir(record.instance_id) / "run"))
            tasks[record.instance_id] = entry
        _write_batch_state(path, state)


def _official_batch_records_to_preflight(
    *,
    records: Sequence[tuple[Path, SwebenchTaskRecord]],
    state_path: Path,
    resume: bool,
    terminal_resume_statuses: set[str],
) -> tuple[tuple[Path, SwebenchTaskRecord], ...]:
    if not resume:
        return tuple(records)
    current_state = _load_batch_state(state_path)
    tasks = current_state.get("tasks", {})
    return tuple(
        (dataset_path, record)
        for dataset_path, record in records
        if str(tasks.get(record.instance_id, {}).get("status")) not in terminal_resume_statuses
    )


def _preflight_official_batch_records(
    *,
    records: Sequence[tuple[Path, SwebenchTaskRecord]],
    docker: DockerCli,
    build_missing: bool,
    arch: str,
) -> None:
    logger.info("official batch preflight started: tasks=%s build_missing=%s arch=%s", len(records), build_missing, arch)
    for dataset_path, record in records:
        try:
            task_record = normalize_benchmark_task_record(record)
            testspec = build_adapted_testspec(task_record, arch=arch)
            image_plan = inspect_image_graph(testspec, docker=docker, build_missing=build_missing)
            if image_plan.missing_images:
                build_missing_images(testspec, docker=docker, plan=image_plan)
        except SandboxedRunInputError:
            raise
        except ValueError as exc:
            raise SandboxedRunInputError(
                f"batch preflight failed for {record.instance_id} from {dataset_path}: {exc}"
            ) from exc
    logger.info("official batch preflight completed: tasks=%s", len(records))


def _official_batch_task_active_index(active_index_path: str | Path, instance_id: str) -> Path:
    base = Path(active_index_path)
    return base.parent / _safe_instance_dir(instance_id) / base.name


def _official_batch_output_path_occupied(path: Path) -> bool:
    if not path.exists():
        return False
    if not path.is_dir():
        return True
    return any(path.iterdir())


def _preflight_official_batch_collisions(
    *,
    records: Sequence[tuple[Path, SwebenchTaskRecord]],
    output_dir: Path,
    active_index_path: str | Path,
    replace_existing: bool,
    resume: bool,
) -> None:
    collisions: list[str] = []
    for _dataset_path, record in records:
        instance_root = output_dir / _safe_instance_dir(record.instance_id)
        prepare_dir = instance_root / "prepare"
        run_dir = instance_root / "run"
        task_active_index = _official_batch_task_active_index(active_index_path, record.instance_id)
        if not replace_existing:
            payload = _read_active_prepared_index(task_active_index)
            if record.instance_id in payload.get("prepared_environments", {}):
                collisions.append(f"{record.instance_id}: active prepared slot exists at {task_active_index}")
        if not resume:
            existing_outputs = [path for path in (prepare_dir, run_dir) if _official_batch_output_path_occupied(path)]
            if existing_outputs:
                collisions.append(
                    f"{record.instance_id}: output already exists at "
                    + ", ".join(str(path) for path in existing_outputs)
                )
    if collisions:
        raise SandboxedRunInputError("official batch preflight found output/slot collisions: " + "; ".join(collisions))


def run_official_swebench_batch(
    *,
    dataset_paths: Sequence[str | Path],
    docker: DockerCli,
    backend_factory: Callable[[], Any],
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    jobs: int = 1,
    build_missing: bool = False,
    replace_existing: bool = False,
    resume: bool = False,
    include_pass_to_pass: bool = False,
    cleanup: bool = True,
    active_index_path: str | Path = ".coding-agent/active-sandboxes.json",
    arch: str = "x86_64",
) -> int:
    """Run all tasks from one or more datasets through official prepare -> run."""
    if jobs <= 0:
        raise SandboxedRunInputError("jobs must be a positive integer")
    records = _load_all_records_from_datasets(dataset_paths)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    state = root / "batch_state.json"
    state_lock = Lock()
    _initialize_official_batch_state(path=state, lock=state_lock, records=records, output_dir=root)
    terminal_resume_statuses = {RunStatus.SOLVED.value, RunStatus.FAILED.value, RunStatus.INCOMPLETE.value}
    preflight_records = _official_batch_records_to_preflight(
        records=records,
        state_path=state,
        resume=resume,
        terminal_resume_statuses=terminal_resume_statuses,
    )
    _preflight_official_batch_collisions(
        records=preflight_records,
        output_dir=root,
        active_index_path=active_index_path,
        replace_existing=replace_existing,
        resume=resume,
    )
    _preflight_official_batch_records(
        records=preflight_records,
        docker=docker,
        build_missing=build_missing,
        arch=arch,
    )

    def run_one(item: tuple[Path, SwebenchTaskRecord]) -> dict[str, Any]:
        dataset_path, record = item
        instance_root = root / _safe_instance_dir(record.instance_id)
        prepare_dir = instance_root / "prepare"
        run_dir = instance_root / "run"
        task_active_index = _official_batch_task_active_index(active_index_path, record.instance_id)
        if resume:
            current_state = _load_batch_state(state)
            current_status = current_state.get("tasks", {}).get(record.instance_id, {}).get("status")
            if current_status in terminal_resume_statuses:
                return {
                    "instance_id": record.instance_id,
                    "status": str(current_status),
                    "error": None,
                    "prepare_dir": str(prepare_dir),
                    "run_dir": str(run_dir),
                    "skipped": True,
                    "input_error": False,
                    "artifact_error": False,
                    "runtime_error": False,
                }
        _update_batch_task(
            state,
            state_lock,
            record.instance_id,
            status="preparing",
            dataset=str(dataset_path),
            prepare_dir=str(prepare_dir),
            run_dir=str(run_dir),
            last_error=None,
        )
        try:
            prepare_official_swebench_runtime(
                dataset_path=dataset_path,
                instance_id=record.instance_id,
                docker=docker,
                output_dir=prepare_dir,
                active_index_path=task_active_index,
                build_missing=build_missing,
                replace_existing=replace_existing,
                arch=arch,
            )
            _update_batch_task(state, state_lock, record.instance_id, status="running", last_error=None)
            summary = run_prepared_swebench_runtime(
                dataset_path=dataset_path,
                instance_id=record.instance_id,
                docker=docker,
                backend=backend_factory(),
                budget=budget,
                model_name=model_name,
                output_dir=run_dir,
                active_index_path=task_active_index,
                include_pass_to_pass=include_pass_to_pass,
                cleanup=cleanup,
                arch=arch,
            )
            _update_batch_task(
                state,
                state_lock,
                record.instance_id,
                status=summary.status.value,
                last_error=summary.error,
            )
            return {
                "instance_id": record.instance_id,
                "status": summary.status.value,
                "error": summary.error,
                "prepare_dir": str(prepare_dir),
                "run_dir": str(run_dir),
                "skipped": False,
                "input_error": False,
                "artifact_error": False,
                "runtime_error": summary.status is RunStatus.ERRORED,
            }
        except SandboxedRunInputError as exc:
            _update_batch_task(state, state_lock, record.instance_id, status="input_error", last_error=str(exc))
            return {
                "instance_id": record.instance_id,
                "status": "input_error",
                "error": str(exc),
                "prepare_dir": str(prepare_dir),
                "run_dir": str(run_dir),
                "skipped": False,
                "input_error": True,
                "artifact_error": False,
                "runtime_error": False,
            }
        except ArtifactPersistenceError as exc:
            _update_batch_task(state, state_lock, record.instance_id, status="artifact_error", last_error=str(exc))
            return {
                "instance_id": record.instance_id,
                "status": "artifact_error",
                "error": str(exc),
                "prepare_dir": str(prepare_dir),
                "run_dir": str(run_dir),
                "skipped": False,
                "input_error": False,
                "artifact_error": True,
                "runtime_error": False,
            }
        except Exception as exc:
            _update_batch_task(state, state_lock, record.instance_id, status="errored", last_error=str(exc))
            return {
                "instance_id": record.instance_id,
                "status": "errored",
                "error": str(exc),
                "prepare_dir": str(prepare_dir),
                "run_dir": str(run_dir),
                "skipped": False,
                "input_error": False,
                "artifact_error": False,
                "runtime_error": True,
            }

    max_workers = min(jobs, len(records))
    results_by_id: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_record = {pool.submit(run_one, item): item[1] for item in records}
        for future in as_completed(future_to_record):
            record = future_to_record[future]
            results_by_id[record.instance_id] = future.result()

    ordered_results = [results_by_id[record.instance_id] for _dataset_path, record in records]
    status_counts: dict[str, int] = {}
    for result in ordered_results:
        status = str(result["status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    predictions = [
        _prediction_from_run_dir(Path(result["run_dir"]), result["instance_id"], model_name)
        for result in ordered_results
    ]
    write_predictions_jsonl(root / "prediction.jsonl", predictions)
    (root / "batch_summary.json").write_text(
        json.dumps(
            {
                "total": len(ordered_results),
                "jobs": jobs,
                "datasets": [str(path) for path in dataset_paths],
                "statuses": status_counts,
                "tasks": ordered_results,
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    if any(result["artifact_error"] for result in ordered_results):
        return 3
    if any(result["input_error"] for result in ordered_results):
        return 2
    if any(result["runtime_error"] for result in ordered_results):
        return 4
    return 0


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
