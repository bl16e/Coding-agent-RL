# SWE-smith Training Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a SWE-smith training manifest workflow that creates fixed SFT/RL splits, tracks teacher outcomes, recycles failed teacher candidates into RL, and prevents `instance_id` reuse.

**Architecture:** Add a focused `coding_agent.swesmith.training_manifest` module for manifest data loading, split creation, validation, update, and subset export. Wire two CLI commands under `coding-agent swesmith`: `create-training-manifest` and `update-training-manifest`. Keep Stage 2 generation unchanged except that users run it against `data/splits/sft_candidate.json`.

**Tech Stack:** Python 3.11, argparse, json, pathlib, pyarrow parquet iteration, pytest.

---

### Task 1: Manifest Creation Domain Logic

**Files:**
- Create: `src/coding_agent/swesmith/training_manifest.py`
- Test: `tests/unit/test_swesmith_training_manifest.py`

- [ ] **Step 1: Write failing tests**

Add tests covering difficulty labels, deterministic split creation, SFT candidate medium-only selection, exported initial subsets, and duplicate `instance_id` rejection.

```python
import json
from pathlib import Path

import pytest

from coding_agent.swesmith.training_manifest import (
    SwesmithTrainingManifestError,
    create_training_manifest,
    difficulty_for_fail_to_pass,
)


def _inst(instance_id: str, fail_count: int, repo: str | None = None) -> dict:
    return {
        "instance_id": instance_id,
        "repo": repo or instance_id.rsplit(".", 1)[0],
        "problem_statement": f"Fix {instance_id}",
        "FAIL_TO_PASS": [f"test_{i}" for i in range(fail_count)],
        "PASS_TO_PASS": [],
    }


def test_difficulty_for_fail_to_pass_uses_configured_bounds():
    assert difficulty_for_fail_to_pass(1, easy_max=1, medium_min=2, medium_max=5) == "easy"
    assert difficulty_for_fail_to_pass(2, easy_max=1, medium_min=2, medium_max=5) == "medium"
    assert difficulty_for_fail_to_pass(5, easy_max=1, medium_min=2, medium_max=5) == "medium"
    assert difficulty_for_fail_to_pass(6, easy_max=1, medium_min=2, medium_max=5) == "hard"


def test_create_training_manifest_writes_medium_sft_candidates_and_initial_rl(tmp_path: Path):
    rows = [
        _inst("repo__a.aaaaaaaa.pr_1", 1),
        _inst("repo__a.aaaaaaaa.pr_2", 2),
        _inst("repo__a.aaaaaaaa.pr_3", 3),
        _inst("repo__a.aaaaaaaa.pr_4", 6),
        _inst("repo__a.aaaaaaaa.pr_5", 4),
    ]
    manifest_path = tmp_path / "manifest.json"
    splits_dir = tmp_path / "splits"

    result = create_training_manifest(
        rows,
        out=manifest_path,
        splits_dir=splits_dir,
        languages=["python"],
        reference_path="Reference/SWE-smith",
        input_path="fixture",
        easy_fail_to_pass_max=1,
        medium_fail_to_pass_min=2,
        medium_fail_to_pass_max=5,
        sft_candidate_limit=2,
        grpo_dev_count=1,
        heldout_count=1,
        seed=7,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result.summary["sft_candidate"] == 2
    assert payload["schema"] == "coding-agent.swesmith.training-manifest.v1"
    sft_ids = {item["instance_id"] for item in payload["items"] if item["initial_split"] == "sft_candidate"}
    assert sft_ids
    assert all(
        item["difficulty"] == "medium"
        for item in payload["items"]
        if item["initial_split"] == "sft_candidate"
    )
    assert (splits_dir / "sft_candidate.json").is_file()
    assert (splits_dir / "rl_train_initial.json").is_file()
    assert (splits_dir / "grpo_dev.json").is_file()
    assert (splits_dir / "heldout.json").is_file()


def test_create_training_manifest_rejects_duplicate_instance_ids(tmp_path: Path):
    rows = [_inst("repo__a.aaaaaaaa.pr_1", 2), _inst("repo__a.aaaaaaaa.pr_1", 3)]
    with pytest.raises(SwesmithTrainingManifestError, match="duplicate instance_id"):
        create_training_manifest(
            rows,
            out=tmp_path / "manifest.json",
            splits_dir=tmp_path / "splits",
            languages=[],
            reference_path=None,
            input_path="fixture",
            easy_fail_to_pass_max=1,
            medium_fail_to_pass_min=2,
            medium_fail_to_pass_max=5,
            sft_candidate_limit=1,
            grpo_dev_count=0,
            heldout_count=0,
            seed=1,
        )
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/unit/test_swesmith_training_manifest.py -q`

Expected: import error because `coding_agent.swesmith.training_manifest` does not exist.

- [ ] **Step 3: Implement manifest creation**

Create `training_manifest.py` with:
- `SwesmithTrainingManifestError`
- `TrainingManifestResult`
- `difficulty_for_fail_to_pass`
- `create_training_manifest`
- subset writers for `sft_candidate.json`, `rl_train_initial.json`, `grpo_dev.json`, and `heldout.json`
- duplicate validation and summary computation

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/unit/test_swesmith_training_manifest.py -q`

Expected: all tests pass.

### Task 2: Manifest Update Domain Logic

**Files:**
- Modify: `src/coding_agent/swesmith/training_manifest.py`
- Test: `tests/unit/test_swesmith_training_manifest.py`

- [ ] **Step 1: Write failing tests**

Add tests proving quality accepted samples move to `sft_train`, unresolved/rejected/errored candidates move to `rl_train`, final subset files are exported, and pool overlaps are rejected.

```python
def test_update_training_manifest_accepts_sft_and_recycles_rejections(tmp_path: Path):
    rows = [
        _inst("repo__a.aaaaaaaa.pr_1", 2),
        _inst("repo__a.aaaaaaaa.pr_2", 3),
        _inst("repo__a.aaaaaaaa.pr_3", 4),
    ]
    manifest_path = tmp_path / "manifest.json"
    splits_dir = tmp_path / "splits"
    create_training_manifest(
        rows,
        out=manifest_path,
        splits_dir=splits_dir,
        languages=[],
        reference_path=None,
        input_path="fixture",
        easy_fail_to_pass_max=1,
        medium_fail_to_pass_min=2,
        medium_fail_to_pass_max=5,
        sft_candidate_limit=2,
        grpo_dev_count=0,
        heldout_count=0,
        seed=1,
    )
    quality = {
        "items": [
            {"instance_id": "repo__a.aaaaaaaa.pr_1", "accepted": True, "reasons": []},
            {"instance_id": "repo__a.aaaaaaaa.pr_2", "accepted": False, "reasons": ["blocked_execute_bash"]},
        ]
    }
    quality_path = tmp_path / "quality.json"
    filtered_sft = tmp_path / "filtered.jsonl"
    quality_path.write_text(json.dumps(quality), encoding="utf-8")
    filtered_sft.write_text(json.dumps({"instance_id": "repo__a.aaaaaaaa.pr_1"}) + "\n", encoding="utf-8")

    from coding_agent.swesmith.training_manifest import update_training_manifest

    result = update_training_manifest(
        manifest_path=manifest_path,
        quality_report_path=quality_path,
        filtered_sft_path=filtered_sft,
        splits_dir=splits_dir,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    pools = {item["instance_id"]: item["final_pool"] for item in payload["items"]}
    assert pools["repo__a.aaaaaaaa.pr_1"] == "sft_train"
    assert pools["repo__a.aaaaaaaa.pr_2"] == "rl_train"
    assert result.summary["sft_train"] == 1
    assert result.summary["rl_train"] == 2
    assert (splits_dir / "sft_accepted.jsonl").is_file()
    assert (splits_dir / "rl_train_final.json").is_file()
    assert (splits_dir / "recycled_from_teacher.json").is_file()
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/unit/test_swesmith_training_manifest.py::test_update_training_manifest_accepts_sft_and_recycles_rejections -q`

Expected: import error for `update_training_manifest`.

- [ ] **Step 3: Implement manifest update**

Add `update_training_manifest`:
- read manifest, quality report, and filtered SFT JSONL
- accepted IDs become `teacher_status=resolved`, `quality_status=accepted`, `final_pool=sft_train`
- rejected quality IDs become `teacher_status=resolved`, `quality_status=rejected`, `final_pool=rl_train`
- SFT candidates absent from accepted/rejected quality report become `teacher_status=artifact_missing`, `quality_status=not_accepted`, `final_pool=rl_train`
- export `sft_accepted.jsonl`, `rl_train_final.json`, and `recycled_from_teacher.json`
- validate pool disjointness

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/unit/test_swesmith_training_manifest.py -q`

Expected: all tests pass.

### Task 3: Local Input Loading And CLI Commands

**Files:**
- Modify: `src/coding_agent/cli.py`
- Modify: `src/coding_agent/swesmith/training_manifest.py`
- Test: `tests/contract/test_cli_swesmith_training_manifest.py`

- [ ] **Step 1: Write failing CLI tests**

Add contract tests for both new commands using small JSON input and synthetic quality report.

```python
import json
from pathlib import Path

from coding_agent.cli import main


def _write_rows(path: Path) -> None:
    rows = [
        {"instance_id": "repo__a.aaaaaaaa.pr_1", "repo": "repo__a.aaaaaaaa", "problem_statement": "Fix 1", "FAIL_TO_PASS": ["a", "b"]},
        {"instance_id": "repo__a.aaaaaaaa.pr_2", "repo": "repo__a.aaaaaaaa", "problem_statement": "Fix 2", "FAIL_TO_PASS": ["a", "b", "c"]},
        {"instance_id": "repo__a.aaaaaaaa.pr_3", "repo": "repo__a.aaaaaaaa", "problem_statement": "Fix 3", "FAIL_TO_PASS": ["a"]},
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_create_training_manifest_cli_writes_manifest_and_splits(tmp_path: Path):
    source = tmp_path / "rows.json"
    _write_rows(source)
    manifest = tmp_path / "manifest.json"
    splits = tmp_path / "splits"

    exit_code = main([
        "swesmith", "create-training-manifest",
        "--input", str(source),
        "--out", str(manifest),
        "--splits-dir", str(splits),
        "--medium-fail-to-pass-min", "2",
        "--medium-fail-to-pass-max", "5",
        "--sft-candidate-limit", "1",
        "--grpo-dev-count", "0",
        "--heldout-count", "0",
        "--seed", "1",
    ])

    assert exit_code == 0
    assert manifest.is_file()
    assert (splits / "sft_candidate.json").is_file()


def test_update_training_manifest_cli_writes_final_splits(tmp_path: Path):
    source = tmp_path / "rows.json"
    _write_rows(source)
    manifest = tmp_path / "manifest.json"
    splits = tmp_path / "splits"
    assert main([
        "swesmith", "create-training-manifest",
        "--input", str(source),
        "--out", str(manifest),
        "--splits-dir", str(splits),
        "--sft-candidate-limit", "1",
        "--grpo-dev-count", "0",
        "--heldout-count", "0",
    ]) == 0
    sft_id = json.loads((splits / "sft_candidate.json").read_text(encoding="utf-8"))[0]["instance_id"]
    quality = tmp_path / "quality.json"
    filtered = tmp_path / "filtered.jsonl"
    quality.write_text(json.dumps({"items": [{"instance_id": sft_id, "accepted": True, "reasons": []}]}), encoding="utf-8")
    filtered.write_text(json.dumps({"instance_id": sft_id}) + "\n", encoding="utf-8")

    exit_code = main([
        "swesmith", "update-training-manifest",
        "--manifest", str(manifest),
        "--quality-report", str(quality),
        "--filtered-sft", str(filtered),
        "--splits-dir", str(splits),
    ])

    assert exit_code == 0
    assert (splits / "rl_train_final.json").is_file()
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/contract/test_cli_swesmith_training_manifest.py -q`

Expected: argparse rejects unknown commands.

- [ ] **Step 3: Implement CLI and input loading**

Add:
- parser entries under `swesmith`
- `_swesmith_create_training_manifest_command`
- `_swesmith_update_training_manifest_command`
- input loader for `.json`, `.jsonl`, `.parquet`, and directories of parquet shards

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/contract/test_cli_swesmith_training_manifest.py tests/unit/test_swesmith_training_manifest.py -q`

Expected: all tests pass.

### Task 4: Verification And Documentation Link

**Files:**
- Modify: `docs/swesmith_sft_pipeline_guide.md`
- Test: `tests/contract/test_stage_docs.py` if existing docs tests need an assertion.

- [ ] **Step 1: Add a short Stage 2 guide link**

Add a short note to `docs/swesmith_sft_pipeline_guide.md` pointing to the training manifest design and the new commands.

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest tests/unit/test_swesmith_training_manifest.py tests/contract/test_cli_swesmith_training_manifest.py -q`

Expected: all tests pass.

- [ ] **Step 3: Run broader impacted tests**

Run: `python -m pytest tests/contract/test_cli_stage_workflows.py tests/unit/test_swesmith_quality_gate.py tests/unit/test_swesmith_evaluate.py tests/unit/test_swesmith_runtime.py -q`

Expected: all tests pass.

---

## Self-Review

Spec coverage:
- Difficulty labeling by `FAIL_TO_PASS`: Task 1.
- `sft_candidate` from medium only: Task 1.
- Teacher accepted to SFT, failed/rejected recycled to RL: Task 2.
- Manifest records instance IDs and prevents reuse: Tasks 1 and 2.
- CLI commands and subset exports: Task 3.
- Documentation link: Task 4.

Placeholder scan:
- No TBD/TODO placeholders remain.

Type consistency:
- Function names are consistent: `create_training_manifest`, `update_training_manifest`, `difficulty_for_fail_to_pass`.
- CLI names match the design: `create-training-manifest`, `update-training-manifest`.
