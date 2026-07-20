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
