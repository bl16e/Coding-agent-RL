import json
from pathlib import Path

from coding_agent.cli import main


def _write_rows(path: Path) -> None:
    rows = [
        {
            "instance_id": "repo__a.aaaaaaaa.pr_1",
            "repo": "repo__a.aaaaaaaa",
            "problem_statement": "Fix 1",
            "FAIL_TO_PASS": ["a", "b"],
        },
        {
            "instance_id": "repo__a.aaaaaaaa.pr_2",
            "repo": "repo__a.aaaaaaaa",
            "problem_statement": "Fix 2",
            "FAIL_TO_PASS": ["a", "b", "c"],
        },
        {
            "instance_id": "repo__a.aaaaaaaa.pr_3",
            "repo": "repo__a.aaaaaaaa",
            "problem_statement": "Fix 3",
            "FAIL_TO_PASS": ["a"],
        },
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_create_training_manifest_cli_writes_manifest_and_splits(tmp_path: Path):
    source = tmp_path / "rows.json"
    _write_rows(source)
    manifest = tmp_path / "manifest.json"
    splits = tmp_path / "splits"

    exit_code = main(
        [
            "swesmith",
            "create-training-manifest",
            "--input",
            str(source),
            "--out",
            str(manifest),
            "--splits-dir",
            str(splits),
            "--medium-fail-to-pass-min",
            "2",
            "--medium-fail-to-pass-max",
            "5",
            "--sft-candidate-limit",
            "1",
            "--grpo-dev-count",
            "0",
            "--heldout-count",
            "0",
            "--seed",
            "1",
        ]
    )

    assert exit_code == 0
    assert manifest.is_file()
    assert (splits / "sft_candidate.json").is_file()


def test_create_training_manifest_cli_limits_sft_candidate_repos(tmp_path: Path):
    source = tmp_path / "rows.json"
    rows = [
        {
            "instance_id": "repo__allowed.aaaaaaaa.pr_1",
            "repo": "swesmith/repo__allowed.aaaaaaaa",
            "problem_statement": "Fix 1",
            "FAIL_TO_PASS": ["a", "b"],
        },
        {
            "instance_id": "repo__other.bbbbbbbb.pr_1",
            "repo": "swesmith/repo__other.bbbbbbbb",
            "problem_statement": "Fix 2",
            "FAIL_TO_PASS": ["a", "b"],
        },
    ]
    source.write_text(json.dumps(rows), encoding="utf-8")
    sft_repos = tmp_path / "sft_repos.txt"
    sft_repos.write_text("repo__allowed.aaaaaaaa\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    splits = tmp_path / "splits"

    exit_code = main(
        [
            "swesmith",
            "create-training-manifest",
            "--input",
            str(source),
            "--out",
            str(manifest),
            "--splits-dir",
            str(splits),
            "--sft-repos-file",
            str(sft_repos),
            "--sft-candidate-limit",
            "10",
            "--grpo-dev-count",
            "0",
            "--heldout-count",
            "0",
        ]
    )

    assert exit_code == 0
    sft_rows = json.loads((splits / "sft_candidate.json").read_text(encoding="utf-8"))
    rl_rows = json.loads((splits / "rl_train_initial.json").read_text(encoding="utf-8"))
    assert [row["instance_id"] for row in sft_rows] == ["repo__allowed.aaaaaaaa.pr_1"]
    assert [row["instance_id"] for row in rl_rows] == ["repo__other.bbbbbbbb.pr_1"]


def test_update_training_manifest_cli_writes_final_splits(tmp_path: Path):
    source = tmp_path / "rows.json"
    _write_rows(source)
    manifest = tmp_path / "manifest.json"
    splits = tmp_path / "splits"
    assert (
        main(
            [
                "swesmith",
                "create-training-manifest",
                "--input",
                str(source),
                "--out",
                str(manifest),
                "--splits-dir",
                str(splits),
                "--sft-candidate-limit",
                "1",
                "--grpo-dev-count",
                "0",
                "--heldout-count",
                "0",
            ]
        )
        == 0
    )
    sft_id = json.loads((splits / "sft_candidate.json").read_text(encoding="utf-8"))[0]["instance_id"]
    quality = tmp_path / "quality.json"
    filtered = tmp_path / "filtered.jsonl"
    quality.write_text(json.dumps({"items": [{"instance_id": sft_id, "accepted": True, "reasons": []}]}), encoding="utf-8")
    filtered.write_text(json.dumps({"instance_id": sft_id}) + "\n", encoding="utf-8")

    exit_code = main(
        [
            "swesmith",
            "update-training-manifest",
            "--manifest",
            str(manifest),
            "--quality-report",
            str(quality),
            "--filtered-sft",
            str(filtered),
            "--splits-dir",
            str(splits),
        ]
    )

    assert exit_code == 0
    assert (splits / "rl_train_final.json").is_file()
