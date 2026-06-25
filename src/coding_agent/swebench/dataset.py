from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding_agent.models import BenchmarkTaskRecord
from coding_agent.swebench.repo_specs import DEFAULT_REPO_SPECS, MissingRepoSpecError


class SwebenchDatasetError(ValueError):
    """Raised when local SWE-Bench task data is missing or invalid."""


class SwebenchMetadataError(SwebenchDatasetError):
    """Raised when a task record lacks source-backed runtime metadata."""


def _normalize_list(value: Any, field_name: str) -> tuple[str, ...]:
    """把 SWE-Bench parquet 中的测试列表字段规范化为 tuple[str, ...]。

    不同来源的数据可能把 FAIL_TO_PASS/PASS_TO_PASS 存成真实列表，也可能存成 JSON
    字符串。这里统一转换，后续 validation 模块就不需要关心原始存储形态。
    """
    if value is None:
        raise SwebenchDatasetError(f"{field_name} is required")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
        value = parsed
    if not isinstance(value, (list, tuple)):
        raise SwebenchDatasetError(f"{field_name} must be a list")
    normalized = tuple(str(item) for item in value if str(item))
    if field_name == "FAIL_TO_PASS" and not normalized:
        raise SwebenchDatasetError("FAIL_TO_PASS must not be empty")
    return normalized


@dataclass(frozen=True)
class SwebenchTaskRecord:
    """从 SWE-Bench 数据集中抽取出的单任务记录。

    字段名保留官方数据集语义：base_commit 是修复前起点，FAIL_TO_PASS 是默认需要
    变绿的失败测试，PASS_TO_PASS 是可选回归测试。
    """

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...] = ()
    version: str | None = None
    environment_setup_commit: str | None = None
    eval_script: str | None = None
    test_patch: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SwebenchTaskRecord":
        """从 parquet 行构造任务记录并校验必需字段。"""
        required = ("instance_id", "repo", "base_commit", "problem_statement", "FAIL_TO_PASS")
        for field_name in required:
            if field_name not in row or row[field_name] in (None, ""):
                raise SwebenchDatasetError(f"{field_name} is required")
        return cls(
            instance_id=str(row["instance_id"]),
            repo=str(row["repo"]),
            base_commit=str(row["base_commit"]),
            problem_statement=str(row["problem_statement"]),
            fail_to_pass=_normalize_list(row["FAIL_TO_PASS"], "FAIL_TO_PASS"),
            pass_to_pass=_normalize_list(row.get("PASS_TO_PASS", ()), "PASS_TO_PASS") if row.get("PASS_TO_PASS") is not None else (),
            version=str(row["version"]) if row.get("version") else None,
            environment_setup_commit=str(row["environment_setup_commit"]) if row.get("environment_setup_commit") else None,
            eval_script=str(row["eval_script"]) if row.get("eval_script") else None,
            test_patch=str(row["test_patch"]) if row.get("test_patch") else "",
        )


def load_task_record(dataset_path: str | Path, instance_id: str) -> SwebenchTaskRecord:
    """从本地 parquet 数据集中加载一个 instance_id。

    当前设计一次只跑一个任务，因此这里线性扫描 to_pylist 足够简单直接；未来如果要
    批量 benchmark，再考虑索引或流式读取。
    """
    path = Path(dataset_path)
    if not path.is_file():
        raise SwebenchDatasetError(f"dataset does not exist: {path}")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SwebenchDatasetError("pyarrow is required to read parquet datasets") from exc

    table = pq.read_table(path)
    for row in table.to_pylist():
        if str(row.get("instance_id")) == instance_id:
            return SwebenchTaskRecord.from_row(row)
    raise SwebenchDatasetError(f"instance not found: {instance_id}")


def load_task_records(dataset_path: str | Path, instance_ids: Sequence[str]) -> tuple[SwebenchTaskRecord, ...]:
    """Load multiple task records with one parquet read after input validation."""
    requested = tuple(str(instance_id) for instance_id in instance_ids if str(instance_id))
    if not requested:
        raise SwebenchDatasetError("at least one instance id is required")
    seen: set[str] = set()
    duplicates: list[str] = []
    for instance_id in requested:
        if instance_id in seen and instance_id not in duplicates:
            duplicates.append(instance_id)
        seen.add(instance_id)
    if duplicates:
        raise SwebenchDatasetError("duplicate instance id: " + ", ".join(duplicates))

    path = Path(dataset_path)
    if not path.is_file():
        raise SwebenchDatasetError(f"dataset does not exist: {path}")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SwebenchDatasetError("pyarrow is required to read parquet datasets") from exc

    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in pq.read_table(path).to_pylist():
        row_instance_id = str(row.get("instance_id"))
        if row_instance_id in seen and row_instance_id not in rows_by_id:
            rows_by_id[row_instance_id] = row

    missing = [instance_id for instance_id in requested if instance_id not in rows_by_id]
    if missing:
        raise SwebenchDatasetError("instance not found: " + ", ".join(missing))
    return tuple(SwebenchTaskRecord.from_row(rows_by_id[instance_id]) for instance_id in requested)


def require_source_metadata(record: SwebenchTaskRecord) -> SwebenchTaskRecord:
    """Validate metadata fields required before official-style runtime planning."""
    if not record.version:
        raise SwebenchMetadataError(f"repo version is required for {record.instance_id}")
    return record


def normalize_benchmark_task_record(record: SwebenchTaskRecord) -> BenchmarkTaskRecord:
    """Normalize a loaded parquet row into the source-backed runtime task model."""
    require_source_metadata(record)
    try:
        DEFAULT_REPO_SPECS.require(record.repo, record.version or "")
    except MissingRepoSpecError as exc:
        supported_repo = any(spec.repo == record.repo for spec in DEFAULT_REPO_SPECS._specs.values())
        if not supported_repo:
            raise SwebenchMetadataError(f"unsupported repository: {record.repo}") from exc
        raise SwebenchMetadataError(str(exc)) from exc
    return BenchmarkTaskRecord(
        instance_id=record.instance_id,
        repo=record.repo,
        version=record.version,
        base_commit=record.base_commit,
        problem_statement=record.problem_statement,
        fail_to_pass=record.fail_to_pass,
        pass_to_pass=record.pass_to_pass,
        test_patch=record.test_patch,
        environment_setup_commit=record.environment_setup_commit,
        eval_script=record.eval_script,
    )
