from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from coding_agent.swesmith.dataset import _get_language_repo_ids, _repo_key, validate_instance


MANIFEST_SCHEMA = "coding-agent.swesmith.training-manifest.v1"


class SwesmithTrainingManifestError(ValueError):
    """Raised when a SWE-smith training manifest would be invalid."""


@dataclass(frozen=True)
class TrainingManifestResult:
    manifest_path: Path
    splits_dir: Path
    summary: dict[str, int]


class TrainingInstances(list[dict[str, Any]]):
    def __init__(self, rows: list[dict[str, Any]], *, skipped_missing_problem_statement: int = 0) -> None:
        super().__init__(rows)
        self.skipped_missing_problem_statement = skipped_missing_problem_statement


@dataclass(frozen=True)
class _SplitPlan:
    heldout_ids: set[str]
    grpo_dev_ids: set[str]
    sft_candidate_ids: set[str]
    summary: dict[str, int]
    skipped_missing_problem_statement: int


def difficulty_for_fail_to_pass(
    count: int,
    *,
    easy_max: int,
    medium_min: int,
    medium_max: int,
) -> str:
    if count <= easy_max:
        return "easy"
    if medium_min <= count <= medium_max:
        return "medium"
    return "hard"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoder = json.JSONEncoder(indent=2, ensure_ascii=False)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in encoder.iterencode(payload):
            handle.write(chunk)
        handle.write("\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


class _JsonArrayWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None
        self._first = True
        self._encoder = json.JSONEncoder(ensure_ascii=False)

    def __enter__(self) -> "_JsonArrayWriter":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("w", encoding="utf-8")
        self._handle.write("[\n")
        return self

    def write(self, payload: Any) -> None:
        if self._handle is None:
            raise RuntimeError("writer is not open")
        if not self._first:
            self._handle.write(",\n")
        self._first = False
        for chunk in self._encoder.iterencode(payload):
            self._handle.write(chunk)

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return
        self._handle.write("\n]\n")
        self._handle.close()
        self._handle = None


def _write_encoded(handle: Any, payload: Any, *, indent: int | None = None) -> None:
    encoder = json.JSONEncoder(indent=indent, ensure_ascii=False)
    for chunk in encoder.iterencode(payload):
        handle.write(chunk)


def _normalized_repo_key(instance: dict[str, Any]) -> str:
    key = _repo_key(instance)
    return key.split("/", 1)[1] if key.startswith("swesmith/") else key


def iter_training_instances(
    input_path: str | Path,
    *,
    languages: list[str],
    reference_path: str | Path | None,
) -> list[dict[str, Any]]:
    source = Path(input_path)
    if not source.exists():
        raise SwesmithTrainingManifestError(f"input path does not exist: {source}")

    repo_ids: set[str] | None = None
    if languages:
        repo_ids = _get_language_repo_ids(languages, reference_path=reference_path)

    rows: list[dict[str, Any]] = []
    skipped_missing_problem_statement = 0
    for row in _iter_raw_instances(source):
        raw = dict(row)
        if repo_ids is not None and _normalized_repo_key(raw) not in repo_ids:
            continue
        if not raw.get("problem_statement"):
            skipped_missing_problem_statement += 1
            continue
        instance = validate_instance(raw)
        rows.append(instance)
    return TrainingInstances(rows, skipped_missing_problem_statement=skipped_missing_problem_statement)


def _iter_raw_instances(source: Path) -> Iterable[dict[str, Any]]:
    if source.is_dir():
        children = sorted(source.glob("*.parquet"))
        if not children:
            raise SwesmithTrainingManifestError(f"no parquet files found in input directory: {source}")
        for child in children:
            yield from _iter_raw_instances(child)
        return
    if source.suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SwesmithTrainingManifestError("json input must be an array")
        for item in payload:
            yield dict(item)
        return
    if source.suffix == ".jsonl":
        with source.open("r", encoding="utf-8") as handle:
            for line in handle:
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
    raise SwesmithTrainingManifestError("input must be a .json, .jsonl, .parquet, or directory of parquet files")


def _validate_unique_instances(rows: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for row in rows:
        instance_id = str(row["instance_id"])
        if instance_id in seen:
            duplicates.append(instance_id)
        seen.add(instance_id)
    if duplicates:
        raise SwesmithTrainingManifestError("duplicate instance_id: " + ", ".join(sorted(set(duplicates))))


def _repo_ids_for_languages(languages: list[str], reference_path: str | Path | None) -> set[str] | None:
    if not languages:
        return None
    return _get_language_repo_ids(languages, reference_path=reference_path)


def _load_repo_filter(path: str | Path | None) -> set[str] | None:
    if path is None:
        return None
    repo_file = Path(path)
    if not repo_file.exists():
        raise SwesmithTrainingManifestError(f"sft repos file does not exist: {repo_file}")
    repo_ids = {
        line.strip().split("/", 1)[1] if line.strip().startswith("swesmith/") else line.strip()
        for line in repo_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    if not repo_ids:
        raise SwesmithTrainingManifestError(f"sft repos file is empty: {repo_file}")
    return repo_ids


def _iter_language_rows(source: Path, repo_ids: set[str] | None) -> Iterable[dict[str, Any]]:
    for row in _iter_raw_instances(source):
        raw = dict(row)
        if repo_ids is not None and _normalized_repo_key(raw) not in repo_ids:
            continue
        yield raw


def _build_split_plan(
    *,
    input_path: str | Path,
    languages: list[str],
    reference_path: str | Path | None,
    easy_fail_to_pass_max: int,
    medium_fail_to_pass_min: int,
    medium_fail_to_pass_max: int,
    sft_candidate_limit: int,
    grpo_dev_count: int,
    heldout_count: int,
    seed: int,
    sft_repo_ids: set[str] | None = None,
) -> _SplitPlan:
    source = Path(input_path)
    if not source.exists():
        raise SwesmithTrainingManifestError(f"input path does not exist: {source}")
    repo_ids = _repo_ids_for_languages(languages, reference_path)
    minimal: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    skipped_missing_problem_statement = 0
    for raw in _iter_language_rows(source, repo_ids):
        if not raw.get("problem_statement"):
            skipped_missing_problem_statement += 1
            continue
        instance = validate_instance(raw)
        instance_id = str(instance["instance_id"])
        if instance_id in seen:
            duplicates.append(instance_id)
            continue
        seen.add(instance_id)
        fail_count = len(instance["FAIL_TO_PASS"])
        minimal.append(
            {
                "instance_id": instance_id,
                "repo": _normalized_repo_key(instance),
                "difficulty": difficulty_for_fail_to_pass(
                    fail_count,
                    easy_max=easy_fail_to_pass_max,
                    medium_min=medium_fail_to_pass_min,
                    medium_max=medium_fail_to_pass_max,
                ),
                "fail_to_pass_count": fail_count,
            }
        )
    if duplicates:
        raise SwesmithTrainingManifestError("duplicate instance_id: " + ", ".join(sorted(set(duplicates))))

    ordered = sorted(minimal, key=lambda row: str(row["instance_id"]))
    rng = random.Random(seed)
    rng.shuffle(ordered)
    heldout_ids = {str(row["instance_id"]) for row in ordered[:heldout_count]}
    dev_start = heldout_count
    dev_end = heldout_count + grpo_dev_count
    grpo_dev_ids = {str(row["instance_id"]) for row in ordered[dev_start:dev_end]}
    heldout_or_dev = heldout_ids | grpo_dev_ids
    medium_remaining = [
        row
        for row in ordered
        if str(row["instance_id"]) not in heldout_or_dev
        and row["difficulty"] == "medium"
        and (sft_repo_ids is None or str(row["repo"]) in sft_repo_ids)
    ]
    sft_candidate_ids = {str(row["instance_id"]) for row in medium_remaining[:sft_candidate_limit]}

    summary: dict[str, int] = {
        "total": len(minimal),
        "easy": 0,
        "medium": 0,
        "hard": 0,
        "sft_candidate": 0,
        "rl_candidate": 0,
        "grpo_dev": len(grpo_dev_ids),
        "heldout": len(heldout_ids),
        "pending_teacher": len(sft_candidate_ids),
        "rl_train": 0,
        "sft_train": 0,
        "skipped_missing_problem_statement": skipped_missing_problem_statement,
    }
    for row in minimal:
        instance_id = str(row["instance_id"])
        summary[str(row["difficulty"])] += 1
        if instance_id in heldout_ids or instance_id in grpo_dev_ids:
            continue
        if instance_id in sft_candidate_ids:
            summary["sft_candidate"] += 1
        else:
            summary["rl_candidate"] += 1
            summary["rl_train"] += 1
    return _SplitPlan(
        heldout_ids=heldout_ids,
        grpo_dev_ids=grpo_dev_ids,
        sft_candidate_ids=sft_candidate_ids,
        summary=summary,
        skipped_missing_problem_statement=skipped_missing_problem_statement,
    )


def _summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {
        "total": len(items),
        "easy": 0,
        "medium": 0,
        "hard": 0,
        "sft_candidate": 0,
        "rl_candidate": 0,
        "grpo_dev": 0,
        "heldout": 0,
        "pending_teacher": 0,
        "rl_train": 0,
        "sft_train": 0,
    }
    for item in items:
        difficulty = str(item.get("difficulty") or "")
        initial_split = str(item.get("initial_split") or "")
        final_pool = str(item.get("final_pool") or "")
        if difficulty in summary:
            summary[difficulty] += 1
        if initial_split in summary:
            summary[initial_split] += 1
        if final_pool in summary:
            summary[final_pool] += 1
    return summary


def _instances_for(items: list[dict[str, Any]], *, initial_split: str | None = None, final_pool: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if initial_split is not None and item.get("initial_split") != initial_split:
            continue
        if final_pool is not None and item.get("final_pool") != final_pool:
            continue
        instance = item.get("instance")
        if isinstance(instance, dict):
            rows.append(instance)
    return rows


def _validate_manifest_items(items: list[dict[str, Any]]) -> None:
    instance_ids = [str(item.get("instance_id") or "") for item in items]
    if len(instance_ids) != len(set(instance_ids)):
        raise SwesmithTrainingManifestError("manifest contains duplicate instance_id")
    pools: dict[str, set[str]] = {}
    for pool in ("sft_train", "rl_train", "grpo_dev", "heldout"):
        pools[pool] = {str(item["instance_id"]) for item in items if item.get("final_pool") == pool}
    if pools["sft_train"] & pools["rl_train"]:
        raise SwesmithTrainingManifestError("sft_train and rl_train overlap")
    train_ids = pools["sft_train"] | pools["rl_train"]
    if pools["grpo_dev"] & train_ids:
        raise SwesmithTrainingManifestError("grpo_dev overlaps train pools")
    if pools["heldout"] & train_ids:
        raise SwesmithTrainingManifestError("heldout overlaps train pools")
    for item in items:
        if item.get("final_pool") == "sft_train" and item.get("initial_split") != "sft_candidate":
            raise SwesmithTrainingManifestError("sft_train item must come from sft_candidate")


def _export_initial_splits(items: list[dict[str, Any]], splits_dir: Path) -> None:
    _write_json(splits_dir / "sft_candidate.json", _instances_for(items, initial_split="sft_candidate"))
    _write_json(splits_dir / "rl_train_initial.json", _instances_for(items, final_pool="rl_train"))
    _write_json(splits_dir / "grpo_dev.json", _instances_for(items, final_pool="grpo_dev"))
    _write_json(splits_dir / "heldout.json", _instances_for(items, final_pool="heldout"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _export_final_splits(
    *,
    items: list[dict[str, Any]],
    accepted_sft_rows: list[dict[str, Any]],
    splits_dir: Path,
) -> None:
    _write_jsonl(splits_dir / "sft_accepted.jsonl", accepted_sft_rows)
    _write_json(splits_dir / "rl_train_final.json", _instances_for(items, final_pool="rl_train"))
    recycled = [
        item["instance"]
        for item in items
        if item.get("initial_split") == "sft_candidate" and item.get("final_pool") == "rl_train"
    ]
    _write_json(splits_dir / "recycled_from_teacher.json", recycled)


def _manifest_item_for_instance(
    instance: dict[str, Any],
    *,
    plan: _SplitPlan,
    easy_fail_to_pass_max: int,
    medium_fail_to_pass_min: int,
    medium_fail_to_pass_max: int,
) -> dict[str, Any]:
    instance_id = str(instance["instance_id"])
    difficulty = difficulty_for_fail_to_pass(
        len(instance["FAIL_TO_PASS"]),
        easy_max=easy_fail_to_pass_max,
        medium_min=medium_fail_to_pass_min,
        medium_max=medium_fail_to_pass_max,
    )
    if instance_id in plan.heldout_ids:
        initial_split = "heldout"
        final_pool = "heldout"
        reason = "selected_for_heldout"
    elif instance_id in plan.grpo_dev_ids:
        initial_split = "grpo_dev"
        final_pool = "grpo_dev"
        reason = "selected_for_grpo_dev"
    elif instance_id in plan.sft_candidate_ids:
        initial_split = "sft_candidate"
        final_pool = "pending_teacher"
        reason = "selected_medium_for_teacher"
    else:
        initial_split = "rl_candidate"
        final_pool = "rl_train"
        reason = "available_for_rl"
    return {
        "instance_id": instance_id,
        "repo": _repo_key(instance),
        "difficulty": difficulty,
        "fail_to_pass_count": len(instance["FAIL_TO_PASS"]),
        "initial_split": initial_split,
        "teacher_status": "not_run",
        "quality_status": "not_run",
        "final_pool": final_pool,
        "reason": reason,
        "instance": instance,
    }


def create_training_manifest_from_input(
    *,
    input_path: str | Path,
    out: str | Path,
    splits_dir: str | Path,
    languages: list[str],
    reference_path: str | Path | None,
    easy_fail_to_pass_max: int,
    medium_fail_to_pass_min: int,
    medium_fail_to_pass_max: int,
    sft_candidate_limit: int,
    grpo_dev_count: int,
    heldout_count: int,
    seed: int,
    sft_repos_file: str | Path | None = None,
) -> TrainingManifestResult:
    if easy_fail_to_pass_max < 0:
        raise SwesmithTrainingManifestError("easy_fail_to_pass_max must be non-negative")
    if medium_fail_to_pass_min <= easy_fail_to_pass_max:
        raise SwesmithTrainingManifestError("medium_fail_to_pass_min must be greater than easy_fail_to_pass_max")
    if medium_fail_to_pass_max < medium_fail_to_pass_min:
        raise SwesmithTrainingManifestError("medium_fail_to_pass_max must be >= medium_fail_to_pass_min")
    if min(sft_candidate_limit, grpo_dev_count, heldout_count) < 0:
        raise SwesmithTrainingManifestError("split counts must be non-negative")

    source = Path(input_path)
    repo_ids = _repo_ids_for_languages(languages, reference_path)
    sft_repo_ids = _load_repo_filter(sft_repos_file)
    plan = _build_split_plan(
        input_path=input_path,
        languages=languages,
        reference_path=reference_path,
        easy_fail_to_pass_max=easy_fail_to_pass_max,
        medium_fail_to_pass_min=medium_fail_to_pass_min,
        medium_fail_to_pass_max=medium_fail_to_pass_max,
        sft_candidate_limit=sft_candidate_limit,
        grpo_dev_count=grpo_dev_count,
        heldout_count=heldout_count,
        seed=seed,
        sft_repo_ids=sft_repo_ids,
    )
    manifest_path = Path(out)
    split_path = Path(splits_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    split_path.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).isoformat()
    encoder = json.JSONEncoder(ensure_ascii=False)
    first_item = True

    with (
        manifest_path.open("w", encoding="utf-8") as manifest_file,
        _JsonArrayWriter(split_path / "sft_candidate.json") as sft_writer,
        _JsonArrayWriter(split_path / "rl_train_initial.json") as rl_writer,
        _JsonArrayWriter(split_path / "grpo_dev.json") as dev_writer,
        _JsonArrayWriter(split_path / "heldout.json") as heldout_writer,
    ):
        manifest_file.write("{\n")
        fields = [
            ("schema", MANIFEST_SCHEMA),
            ("created_at", created_at),
            ("seed", seed),
            (
                "source",
                {
                    "input": str(input_path),
                    "languages": list(languages),
                    "reference_path": str(reference_path) if reference_path is not None else None,
                    "sft_repos_file": str(sft_repos_file) if sft_repos_file is not None else None,
                    "skipped_missing_problem_statement": plan.skipped_missing_problem_statement,
                },
            ),
            (
                "difficulty_rules",
                {
                    "easy_max_fail_to_pass": easy_fail_to_pass_max,
                    "medium_min_fail_to_pass": medium_fail_to_pass_min,
                    "medium_max_fail_to_pass": medium_fail_to_pass_max,
                    "hard_min_fail_to_pass": medium_fail_to_pass_max + 1,
                },
            ),
            (
                "split_config",
                {
                    "sft_candidate_limit": sft_candidate_limit,
                    "grpo_dev_count": grpo_dev_count,
                    "heldout_count": heldout_count,
                },
            ),
        ]
        for key, value in fields:
            manifest_file.write(f"  {json.dumps(key)}: ")
            _write_encoded(manifest_file, value, indent=2)
            manifest_file.write(",\n")
        manifest_file.write('  "items": [\n')

        for raw in _iter_language_rows(source, repo_ids):
            if not raw.get("problem_statement"):
                continue
            instance = validate_instance(raw)
            item = _manifest_item_for_instance(
                instance,
                plan=plan,
                easy_fail_to_pass_max=easy_fail_to_pass_max,
                medium_fail_to_pass_min=medium_fail_to_pass_min,
                medium_fail_to_pass_max=medium_fail_to_pass_max,
            )
            if not first_item:
                manifest_file.write(",\n")
            first_item = False
            for chunk in encoder.iterencode(item):
                manifest_file.write(chunk)

            instance_id = str(instance["instance_id"])
            if instance_id in plan.heldout_ids:
                heldout_writer.write(instance)
            elif instance_id in plan.grpo_dev_ids:
                dev_writer.write(instance)
            elif instance_id in plan.sft_candidate_ids:
                sft_writer.write(instance)
            else:
                rl_writer.write(instance)

        manifest_file.write("\n  ],\n")
        manifest_file.write('  "summary": ')
        _write_encoded(manifest_file, plan.summary, indent=2)
        manifest_file.write("\n}\n")

    return TrainingManifestResult(manifest_path=manifest_path, splits_dir=split_path, summary=plan.summary)


def create_training_manifest(
    instances: list[dict[str, Any]],
    *,
    out: str | Path,
    splits_dir: str | Path,
    languages: list[str],
    reference_path: str | Path | None,
    input_path: str | Path,
    easy_fail_to_pass_max: int,
    medium_fail_to_pass_min: int,
    medium_fail_to_pass_max: int,
    sft_candidate_limit: int,
    grpo_dev_count: int,
    heldout_count: int,
    seed: int,
) -> TrainingManifestResult:
    if easy_fail_to_pass_max < 0:
        raise SwesmithTrainingManifestError("easy_fail_to_pass_max must be non-negative")
    if medium_fail_to_pass_min <= easy_fail_to_pass_max:
        raise SwesmithTrainingManifestError("medium_fail_to_pass_min must be greater than easy_fail_to_pass_max")
    if medium_fail_to_pass_max < medium_fail_to_pass_min:
        raise SwesmithTrainingManifestError("medium_fail_to_pass_max must be >= medium_fail_to_pass_min")
    if min(sft_candidate_limit, grpo_dev_count, heldout_count) < 0:
        raise SwesmithTrainingManifestError("split counts must be non-negative")

    skipped_missing_problem_statement = int(getattr(instances, "skipped_missing_problem_statement", 0))
    rows: list[dict[str, Any]] = []
    for instance in instances:
        raw = dict(instance)
        if not raw.get("problem_statement"):
            skipped_missing_problem_statement += 1
            continue
        rows.append(validate_instance(raw))
    _validate_unique_instances(rows)
    ordered = sorted(rows, key=lambda row: str(row["instance_id"]))
    rng = random.Random(seed)
    rng.shuffle(ordered)

    heldout_ids = {str(row["instance_id"]) for row in ordered[:heldout_count]}
    dev_start = heldout_count
    dev_end = heldout_count + grpo_dev_count
    grpo_dev_ids = {str(row["instance_id"]) for row in ordered[dev_start:dev_end]}
    remaining = [row for row in ordered if str(row["instance_id"]) not in heldout_ids | grpo_dev_ids]
    medium_remaining = [
        row
        for row in remaining
        if difficulty_for_fail_to_pass(
            len(row["FAIL_TO_PASS"]),
            easy_max=easy_fail_to_pass_max,
            medium_min=medium_fail_to_pass_min,
            medium_max=medium_fail_to_pass_max,
        )
        == "medium"
    ]
    sft_candidate_ids = {str(row["instance_id"]) for row in medium_remaining[:sft_candidate_limit]}

    items: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item["instance_id"])):
        instance_id = str(row["instance_id"])
        difficulty = difficulty_for_fail_to_pass(
            len(row["FAIL_TO_PASS"]),
            easy_max=easy_fail_to_pass_max,
            medium_min=medium_fail_to_pass_min,
            medium_max=medium_fail_to_pass_max,
        )
        if instance_id in heldout_ids:
            initial_split = "heldout"
            final_pool = "heldout"
            reason = "selected_for_heldout"
        elif instance_id in grpo_dev_ids:
            initial_split = "grpo_dev"
            final_pool = "grpo_dev"
            reason = "selected_for_grpo_dev"
        elif instance_id in sft_candidate_ids:
            initial_split = "sft_candidate"
            final_pool = "pending_teacher"
            reason = "selected_medium_for_teacher"
        else:
            initial_split = "rl_candidate"
            final_pool = "rl_train"
            reason = "available_for_rl"
        items.append(
            {
                "instance_id": instance_id,
                "repo": _repo_key(row),
                "difficulty": difficulty,
                "fail_to_pass_count": len(row["FAIL_TO_PASS"]),
                "initial_split": initial_split,
                "teacher_status": "not_run",
                "quality_status": "not_run",
                "final_pool": final_pool,
                "reason": reason,
                "instance": row,
            }
        )

    _validate_manifest_items(items)
    summary = _summary(items)
    summary["skipped_missing_problem_statement"] = skipped_missing_problem_statement
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "source": {
            "input": str(input_path),
            "languages": list(languages),
            "reference_path": str(reference_path) if reference_path is not None else None,
            "skipped_missing_problem_statement": skipped_missing_problem_statement,
        },
        "difficulty_rules": {
            "easy_max_fail_to_pass": easy_fail_to_pass_max,
            "medium_min_fail_to_pass": medium_fail_to_pass_min,
            "medium_max_fail_to_pass": medium_fail_to_pass_max,
            "hard_min_fail_to_pass": medium_fail_to_pass_max + 1,
        },
        "split_config": {
            "sft_candidate_limit": sft_candidate_limit,
            "grpo_dev_count": grpo_dev_count,
            "heldout_count": heldout_count,
        },
        "items": items,
        "summary": summary,
    }
    manifest_path = Path(out)
    split_path = Path(splits_dir)
    _write_json(manifest_path, manifest)
    _export_initial_splits(items, split_path)
    return TrainingManifestResult(manifest_path=manifest_path, splits_dir=split_path, summary=summary)


def update_training_manifest(
    *,
    manifest_path: str | Path,
    quality_report_path: str | Path,
    filtered_sft_path: str | Path,
    splits_dir: str | Path,
) -> TrainingManifestResult:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise SwesmithTrainingManifestError("unsupported manifest schema")
    items = manifest.get("items")
    if not isinstance(items, list):
        raise SwesmithTrainingManifestError("manifest items must be a list")

    quality = json.loads(Path(quality_report_path).read_text(encoding="utf-8"))
    quality_items = quality.get("items")
    if not isinstance(quality_items, list):
        raise SwesmithTrainingManifestError("quality report items must be a list")
    quality_by_id = {str(item.get("instance_id")): item for item in quality_items if item.get("instance_id")}
    accepted_sft_rows = _load_jsonl(Path(filtered_sft_path))
    accepted_ids = {str(row.get("instance_id")) for row in accepted_sft_rows if row.get("instance_id")}

    for item in items:
        if item.get("initial_split") != "sft_candidate":
            continue
        instance_id = str(item["instance_id"])
        quality_item = quality_by_id.get(instance_id)
        if instance_id in accepted_ids:
            if quality_item is not None and quality_item.get("accepted") is False:
                raise SwesmithTrainingManifestError(f"filtered SFT contains quality-rejected instance: {instance_id}")
            item["teacher_status"] = "resolved"
            item["quality_status"] = "accepted"
            item["final_pool"] = "sft_train"
            item["reason"] = "teacher_resolved_quality_accepted"
            item.pop("rejection_reasons", None)
        elif quality_item is not None:
            if quality_item.get("accepted"):
                raise SwesmithTrainingManifestError(f"quality accepted instance missing from filtered SFT: {instance_id}")
            item["teacher_status"] = "resolved"
            item["quality_status"] = "rejected"
            item["final_pool"] = "rl_train"
            item["reason"] = "teacher_recycled_quality_rejected"
            reasons = quality_item.get("reasons")
            item["rejection_reasons"] = reasons if isinstance(reasons, list) else []
        else:
            item["teacher_status"] = "artifact_missing"
            item["quality_status"] = "not_accepted"
            item["final_pool"] = "rl_train"
            item["reason"] = "teacher_recycled_missing_quality_report"
            item["rejection_reasons"] = ["missing_quality_report_item"]

    _validate_manifest_items(items)
    summary = _summary(items)
    previous_summary = manifest.get("summary")
    if isinstance(previous_summary, dict) and "skipped_missing_problem_statement" in previous_summary:
        summary["skipped_missing_problem_statement"] = int(previous_summary["skipped_missing_problem_statement"])
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    manifest["summary"] = summary
    _write_json(manifest_file, manifest)
    split_path = Path(splits_dir)
    _export_final_splits(items=items, accepted_sft_rows=accepted_sft_rows, splits_dir=split_path)
    return TrainingManifestResult(manifest_path=manifest_file, splits_dir=split_path, summary=summary)
