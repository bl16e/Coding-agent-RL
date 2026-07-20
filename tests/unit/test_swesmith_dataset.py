import json
from pathlib import Path

import pytest

from coding_agent.swesmith.dataset import (
    SwesmithDatasetError,
    create_subset_file,
    load_subset,
    validate_instance,
)


def _instance(instance_id: str = "pandas-dev__pandas.95280573.pr_53652") -> dict:
    return {
        "instance_id": instance_id,
        "repo": "pandas-dev__pandas.95280573",
        "problem_statement": "Fix the bug",
        "FAIL_TO_PASS": ["tests/test_frame.py::test_bug"],
        "PASS_TO_PASS": ["tests/test_frame.py::test_existing"],
        "patch": "diff --git a/pandas/core/frame.py b/pandas/core/frame.py\n",
    }


def test_validate_instance_requires_official_fields():
    with pytest.raises(SwesmithDatasetError, match="problem_statement is required"):
        validate_instance({"instance_id": "x"})


def test_load_subset_reads_json_array(tmp_path: Path):
    path = tmp_path / "subset.json"
    path.write_text(json.dumps([_instance()]), encoding="utf-8")

    rows = load_subset(path)

    assert len(rows) == 1
    assert rows[0]["instance_id"] == "pandas-dev__pandas.95280573.pr_53652"


def test_load_subset_reads_jsonl(tmp_path: Path):
    path = tmp_path / "subset.jsonl"
    path.write_text(json.dumps(_instance()) + "\n", encoding="utf-8")

    rows = load_subset(path)

    assert [row["problem_statement"] for row in rows] == ["Fix the bug"]


def test_load_subset_rejects_empty_subset(tmp_path: Path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(SwesmithDatasetError, match="subset must contain at least one instance"):
        load_subset(path)


def test_create_subset_file_filters_pr_and_fail_to_pass_count(tmp_path: Path):
    output = tmp_path / "subset.json"
    source = [
        _instance("repo__name.abcdef12.pr_1"),
        {**_instance("repo__name.abcdef12.issue_2"), "FAIL_TO_PASS": ["a", "b"]},
        {**_instance("repo__name.abcdef12.pr_3"), "FAIL_TO_PASS": ["a", "b", "c", "d", "e", "f"]},
    ]

    selected = create_subset_file(
        output,
        instances=source,
        require_pr=True,
        min_fail_to_pass=1,
        max_fail_to_pass=5,
    )

    assert [item["instance_id"] for item in selected] == ["repo__name.abcdef12.pr_1"]
    assert json.loads(output.read_text(encoding="utf-8")) == selected
