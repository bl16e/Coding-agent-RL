import json
from pathlib import Path

import pytest

from coding_agent.swesmith.training_manifest import (
    SwesmithTrainingManifestError,
    create_training_manifest_from_input,
    create_training_manifest,
    difficulty_for_fail_to_pass,
    _write_json,
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


def test_create_training_manifest_skips_missing_problem_statement(tmp_path: Path):
    rows = [
        _inst("repo__a.aaaaaaaa.pr_1", 2),
        {**_inst("repo__a.aaaaaaaa.pr_2", 3), "problem_statement": ""},
        {**_inst("repo__a.aaaaaaaa.pr_3", 4), "problem_statement": None},
    ]
    manifest_path = tmp_path / "manifest.json"

    result = create_training_manifest(
        rows,
        out=manifest_path,
        splits_dir=tmp_path / "splits",
        languages=[],
        reference_path=None,
        input_path="fixture",
        easy_fail_to_pass_max=1,
        medium_fail_to_pass_min=2,
        medium_fail_to_pass_max=5,
        sft_candidate_limit=3,
        grpo_dev_count=0,
        heldout_count=0,
        seed=1,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result.summary["total"] == 1
    assert result.summary["skipped_missing_problem_statement"] == 2
    assert payload["summary"]["skipped_missing_problem_statement"] == 2
    assert payload["source"]["skipped_missing_problem_statement"] == 2
    assert [item["instance_id"] for item in payload["items"]] == ["repo__a.aaaaaaaa.pr_1"]


def test_write_json_streams_without_json_dumps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fail_dumps(*args, **kwargs):
        raise AssertionError("json.dumps should not build the full payload")

    monkeypatch.setattr(json, "dumps", fail_dumps)
    path = tmp_path / "payload.json"

    _write_json(path, {"items": [{"instance_id": "repo__a.aaaaaaaa.pr_1"}]})

    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["instance_id"] == "repo__a.aaaaaaaa.pr_1"


def test_create_training_manifest_from_input_limits_sft_candidate_repos(tmp_path: Path):
    source = tmp_path / "rows.json"
    rows = [
        _inst("repo__allowed.aaaaaaaa.pr_1", 2, repo="swesmith/repo__allowed.aaaaaaaa"),
        _inst("repo__allowed.aaaaaaaa.pr_2", 3, repo="swesmith/repo__allowed.aaaaaaaa"),
        _inst("repo__other.bbbbbbbb.pr_1", 2, repo="swesmith/repo__other.bbbbbbbb"),
    ]
    source.write_text(json.dumps(rows), encoding="utf-8")
    sft_repos_file = tmp_path / "sft_repos.txt"
    sft_repos_file.write_text("repo__allowed.aaaaaaaa\n", encoding="utf-8")

    create_training_manifest_from_input(
        input_path=source,
        out=tmp_path / "manifest.json",
        splits_dir=tmp_path / "splits",
        languages=[],
        reference_path=None,
        sft_repos_file=sft_repos_file,
        easy_fail_to_pass_max=1,
        medium_fail_to_pass_min=2,
        medium_fail_to_pass_max=5,
        sft_candidate_limit=10,
        grpo_dev_count=0,
        heldout_count=0,
        seed=1,
    )

    sft_rows = json.loads((tmp_path / "splits" / "sft_candidate.json").read_text(encoding="utf-8"))
    rl_rows = json.loads((tmp_path / "splits" / "rl_train_initial.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert {row["repo"] for row in sft_rows} == {"swesmith/repo__allowed.aaaaaaaa"}
    assert [row["instance_id"] for row in rl_rows] == ["repo__other.bbbbbbbb.pr_1"]
    assert manifest["summary"]["sft_candidate"] == 2
    assert manifest["summary"]["rl_train"] == 1
    assert manifest["source"]["sft_repos_file"] == str(sft_repos_file)


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
    sft_ids = [item["instance_id"] for item in json.loads(manifest_path.read_text(encoding="utf-8"))["items"] if item["initial_split"] == "sft_candidate"]
    accepted_id, rejected_id = sft_ids
    quality = {
        "items": [
            {"instance_id": accepted_id, "accepted": True, "reasons": []},
            {"instance_id": rejected_id, "accepted": False, "reasons": ["blocked_execute_bash"]},
        ]
    }
    quality_path = tmp_path / "quality.json"
    filtered_sft = tmp_path / "filtered.jsonl"
    quality_path.write_text(json.dumps(quality), encoding="utf-8")
    filtered_sft.write_text(json.dumps({"instance_id": accepted_id}) + "\n", encoding="utf-8")

    from coding_agent.swesmith.training_manifest import update_training_manifest

    result = update_training_manifest(
        manifest_path=manifest_path,
        quality_report_path=quality_path,
        filtered_sft_path=filtered_sft,
        splits_dir=splits_dir,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    pools = {item["instance_id"]: item["final_pool"] for item in payload["items"]}
    assert pools[accepted_id] == "sft_train"
    assert pools[rejected_id] == "rl_train"
    assert result.summary["sft_train"] == 1
    assert result.summary["rl_train"] == 2
    assert (splits_dir / "sft_accepted.jsonl").is_file()
    assert (splits_dir / "rl_train_final.json").is_file()
    assert (splits_dir / "recycled_from_teacher.json").is_file()
