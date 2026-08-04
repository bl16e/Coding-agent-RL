from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from coding_agent.swesmith.dataset import (
    SwesmithDatasetError,
    _get_language_repo_ids,
    _repo_key,
    load_huggingface_swesmith,
    validate_instance,
)


def iter_instances_from_input(path: str | Path) -> Iterable[dict[str, Any]]:
    source = Path(path)
    if source.is_dir():
        found = False
        for child in sorted(source.glob("*.parquet")):
            found = True
            yield from iter_instances_from_input(child)
        if not found:
            raise ValueError(f"no parquet files found in input directory: {source}")
        return
    if not source.is_file():
        raise ValueError(f"input path does not exist: {source}")
    if source.suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("json input must be an array")
        for item in payload:
            yield dict(item)
        return
    if source.suffix == ".jsonl":
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)
        return
    if source.suffix == ".parquet":
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(source)
        for batch in parquet.iter_batches(batch_size=256):
            for item in batch.to_pylist():
                yield dict(item)
        return
    raise ValueError("input must be a .json, .jsonl, .parquet, or directory of parquet files")


def load_instances_from_input(path: str | Path) -> list[dict[str, Any]]:
    return list(iter_instances_from_input(path))


def normalized_repo_key(instance: dict[str, Any]) -> str:
    key = _repo_key(instance)
    return key.split("/", 1)[1] if key.startswith("swesmith/") else key


def select_pilot_instances(
    instances: Iterable[dict[str, Any]],
    *,
    language_repo_ids: set[str],
    limit: int,
    require_pr: bool,
    min_fail_to_pass: int,
    max_fail_to_pass: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for raw in instances:
        try:
            instance = validate_instance(dict(raw))
        except SwesmithDatasetError:
            continue
        fail_to_pass = instance["FAIL_TO_PASS"]
        if require_pr and ".pr_" not in instance["instance_id"]:
            continue
        if len(fail_to_pass) < min_fail_to_pass:
            continue
        if len(fail_to_pass) > max_fail_to_pass:
            continue
        if normalized_repo_key(instance) not in language_repo_ids:
            continue
        selected.append(instance)
        if len(selected) >= limit:
            break
    return selected


def write_subset(output: str | Path, rows: list[dict[str, Any]]) -> None:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(rows, indent=2, ensure_ascii=True), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a small SWE-smith Stage 2 pilot subset.")
    parser.add_argument("--input", help="Local SWE-smith .json, .jsonl, .parquet, or directory of parquet shards.")
    parser.add_argument("--out", default="data/stage2_pilot_10.json")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--split", default="train")
    parser.add_argument("--languages", default="python", help="Comma-separated language filter.")
    parser.add_argument("--reference-path", default="Reference/SWE-smith")
    parser.add_argument("--min-fail-to-pass", type=int, default=2)
    parser.add_argument("--max-fail-to-pass", type=int, default=5)
    parser.add_argument("--require-pr", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit < 1:
        raise ValueError("--limit must be positive")
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    repo_ids = _get_language_repo_ids(languages, reference_path=args.reference_path)
    instances = iter_instances_from_input(args.input) if args.input else load_huggingface_swesmith(split=args.split)
    selected = select_pilot_instances(
        instances,
        language_repo_ids=repo_ids,
        limit=args.limit,
        require_pr=args.require_pr,
        min_fail_to_pass=args.min_fail_to_pass,
        max_fail_to_pass=args.max_fail_to_pass,
    )
    write_subset(args.out, selected)
    print(
        json.dumps(
            {
                "output": str(Path(args.out)),
                "count": len(selected),
                "instance_ids": [item["instance_id"] for item in selected],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
