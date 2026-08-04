import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path("scripts/create_stage2_pilot_subset.py")


def _load_script_module():
    spec = importlib.util.spec_from_file_location("create_stage2_pilot_subset", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_select_pilot_instances_filters_and_limits():
    module = _load_script_module()
    instances = [
        {
            "instance_id": "repo__one.abcdef12.pr_1",
            "repo": "swesmith/repo__one.abcdef12",
            "problem_statement": "fix one",
            "FAIL_TO_PASS": ["a", "b"],
        },
        {
            "instance_id": "repo__two.abcdef12.no_pr",
            "repo": "repo__two.abcdef12",
            "problem_statement": "no pr",
            "FAIL_TO_PASS": ["a", "b"],
        },
        {
            "instance_id": "repo__one.abcdef12.pr_2",
            "repo": "repo__one.abcdef12",
            "problem_statement": "too many tests",
            "FAIL_TO_PASS": ["a", "b", "c", "d", "e", "f"],
        },
        {
            "instance_id": "repo__one.abcdef12.pr_3",
            "repo": "swesmith/repo__one.abcdef12",
            "problem_statement": "fix three",
            "FAIL_TO_PASS": ["a", "b", "c"],
        },
    ]

    selected = module.select_pilot_instances(
        instances,
        language_repo_ids={"repo__one.abcdef12"},
        limit=1,
        require_pr=True,
        min_fail_to_pass=2,
        max_fail_to_pass=5,
    )

    assert [item["instance_id"] for item in selected] == ["repo__one.abcdef12.pr_1"]


def test_select_pilot_instances_skips_invalid_rows():
    module = _load_script_module()
    instances = [
        {
            "instance_id": "repo__one.abcdef12.pr_0",
            "repo": "repo__one.abcdef12",
            "FAIL_TO_PASS": ["a", "b"],
        },
        {
            "instance_id": "repo__one.abcdef12.pr_1",
            "repo": "repo__one.abcdef12",
            "problem_statement": "fix one",
            "FAIL_TO_PASS": ["a", "b"],
        },
    ]

    selected = module.select_pilot_instances(
        instances,
        language_repo_ids={"repo__one.abcdef12"},
        limit=10,
        require_pr=True,
        min_fail_to_pass=2,
        max_fail_to_pass=5,
    )

    assert [item["instance_id"] for item in selected] == ["repo__one.abcdef12.pr_1"]


def test_write_subset_writes_pretty_json(tmp_path: Path):
    module = _load_script_module()
    output = tmp_path / "pilot.json"
    rows = [
        {
            "instance_id": "repo__one.abcdef12.pr_1",
            "problem_statement": "fix one",
            "FAIL_TO_PASS": ["a", "b"],
        }
    ]

    module.write_subset(output, rows)

    assert json.loads(output.read_text(encoding="utf-8")) == rows
    assert "\n  {" in output.read_text(encoding="utf-8")


def test_load_instances_from_input_reads_json_jsonl_and_parquet_dir(tmp_path: Path):
    module = _load_script_module()
    rows = [
        {
            "instance_id": "repo__one.abcdef12.pr_1",
            "repo": "repo__one.abcdef12",
            "problem_statement": "fix one",
            "FAIL_TO_PASS": ["a", "b"],
        }
    ]
    json_path = tmp_path / "rows.json"
    json_path.write_text(json.dumps(rows), encoding="utf-8")
    jsonl_path = tmp_path / "rows.jsonl"
    jsonl_path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")

    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist(rows), parquet_dir / "train-00000.parquet")

    assert [item["instance_id"] for item in module.load_instances_from_input(json_path)] == ["repo__one.abcdef12.pr_1"]
    assert [item["instance_id"] for item in module.load_instances_from_input(jsonl_path)] == ["repo__one.abcdef12.pr_1"]
    assert [item["instance_id"] for item in module.load_instances_from_input(parquet_dir)] == ["repo__one.abcdef12.pr_1"]
