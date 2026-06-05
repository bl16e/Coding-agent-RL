from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SwebenchDatasetError(ValueError):
    """Raised when local SWE-Bench task data is missing or invalid."""


def _normalize_list(value: Any, field_name: str) -> tuple[str, ...]:
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
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...] = ()
    version: str | None = None
    environment_setup_commit: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SwebenchTaskRecord":
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
        )


def load_task_record(dataset_path: str | Path, instance_id: str) -> SwebenchTaskRecord:
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
