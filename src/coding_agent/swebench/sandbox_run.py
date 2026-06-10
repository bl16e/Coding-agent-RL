from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from coding_agent.swebench.dataset import SwebenchTaskRecord, load_task_records
from coding_agent.swebench.prediction import write_prediction_jsonl, write_predictions_jsonl
from coding_agent.swebench.validation import ValidationMetadataError, build_validation_test_set
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


def _sandbox_payload(sandbox: TaskSandbox, validation: ValidationTestSet, *, status: str) -> dict[str, Any]:
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
    """写入沙箱元数据文件。"""
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
    if not base_image.official_compatible:
        raise SandboxedRunInputError("base image must be marked official_compatible")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    # 当前 agent.run_task 需要一个宿主侧 workspace 来生成本地 patch 产物。Docker 模式
    # 的真实仓库变更发生在容器中，因此这里使用占位快照目录保持接口兼容。
    host_workspace = output_path / "_workspace_snapshot"
    host_workspace.mkdir(parents=True, exist_ok=True)
    validation = validation_from_task(task_record, base_image, include_pass_to_pass=include_pass_to_pass)
    manager = TaskSandboxManager(docker=docker)
    run_id = str(uuid.uuid4())
    # prepare 会创建容器、启动容器并 checkout 到任务 base_commit。
    sandbox = manager.prepare(
        base_image=base_image,
        instance_id=task_record.instance_id,
        base_commit=task_record.base_commit,
        run_id=run_id,
    )
    _write_sandbox_json(output_path / "sandbox.json", sandbox, validation, status="running")
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
        # 从这里开始模型可能产生工具副作用。后续异常要尽量写失败产物，而不是只抛出。
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
        manager.stop(sandbox)
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
    # run_task 返回的是通用 summary；这里补充 Docker 沙箱元数据后重新写回 summary.json。
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
    """为 swebench run 加载并校验基础镜像。"""
    try:
        base_image = registry_load_base_image(path, repo, require_runnable=False)
        if not base_image.official_compatible:
            raise SandboxedRunInputError("base image must be marked official_compatible")
        return base_image
    except SandboxRegistryError as exc:
        raise SandboxedRunInputError(str(exc)) from exc
