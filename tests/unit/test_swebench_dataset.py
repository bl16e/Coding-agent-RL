from pathlib import Path

import pytest

from coding_agent.swebench.dataset import SwebenchTaskRecord, load_task_record


def _write_dataset(path: Path) -> None:
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    table = pyarrow.table(
        {
            "instance_id": ["django__django-11099"],
            "repo": ["django/django"],
            "base_commit": ["abc123"],
            "problem_statement": ["Fix the issue."],
            "FAIL_TO_PASS": [["tests/test_issue.py::test_fix"]],
            "PASS_TO_PASS": [["tests/test_regression.py::test_old"]],
        }
    )
    parquet.write_table(table, path)


def test_load_task_record_by_instance_id(tmp_path: Path):
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)

    record = load_task_record(dataset, "django__django-11099")

    assert record.instance_id == "django__django-11099"
    assert record.repo == "django/django"
    assert record.fail_to_pass == ("tests/test_issue.py::test_fix",)
    assert record.pass_to_pass == ("tests/test_regression.py::test_old",)


def test_load_task_record_rejects_missing_required_fields():
    with pytest.raises(ValueError, match="FAIL_TO_PASS"):
        SwebenchTaskRecord.from_row(
            {
                "instance_id": "django__django-11099",
                "repo": "django/django",
                "base_commit": "abc123",
                "problem_statement": "Fix it.",
            }
        )


def test_load_task_record_reports_missing_instance(tmp_path: Path):
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)

    with pytest.raises(ValueError, match="instance"):
        load_task_record(dataset, "missing")
