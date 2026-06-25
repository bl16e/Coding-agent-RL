from pathlib import Path

import pytest

from coding_agent.swebench.dataset import (
    SwebenchMetadataError,
    SwebenchTaskRecord,
    normalize_benchmark_task_record,
    load_task_record,
    load_task_records,
    require_source_metadata,
)
from tests.helpers.swebench_fixtures import swebench_row


def _write_dataset(path: Path) -> None:
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    table = pyarrow.table(
        {
            "instance_id": ["django__django-11099", "django__django-11100"],
            "repo": ["django/django", "django/django"],
            "base_commit": ["abc123", "def456"],
            "problem_statement": ["Fix the issue.", "Fix the second issue."],
            "FAIL_TO_PASS": [["tests/test_issue.py::test_fix"], ["tests/test_second.py::test_fix"]],
            "PASS_TO_PASS": [["tests/test_regression.py::test_old"], []],
            "test_patch": ["diff --git a/tests/test_issue.py b/tests/test_issue.py\n", ""],
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
    assert record.test_patch == "diff --git a/tests/test_issue.py b/tests/test_issue.py\n"


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


def test_load_task_records_returns_requested_records_in_requested_order(tmp_path: Path):
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)

    records = load_task_records(dataset, ["django__django-11100", "django__django-11099"])

    assert [record.instance_id for record in records] == ["django__django-11100", "django__django-11099"]
    assert records[0].base_commit == "def456"


def test_load_task_records_rejects_duplicate_instance_ids(tmp_path: Path):
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)

    with pytest.raises(ValueError, match="duplicate"):
        load_task_records(dataset, ["django__django-11099", "django__django-11099"])


def test_load_task_records_reports_all_missing_instances(tmp_path: Path):
    dataset = tmp_path / "dataset.parquet"
    _write_dataset(dataset)

    with pytest.raises(ValueError, match="missing-one"):
        load_task_records(dataset, ["django__django-11099", "missing-one", "missing-two"])


def test_require_source_metadata_reports_missing_version():
    record = SwebenchTaskRecord.from_row(
        {
            "instance_id": "django__django-11099",
            "repo": "django/django",
            "base_commit": "abc123",
            "problem_statement": "Fix it.",
            "FAIL_TO_PASS": ["tests/test_issue.py::test_fix"],
        }
    )

    with pytest.raises(SwebenchMetadataError, match="repo version"):
        require_source_metadata(record)


def test_load_task_record_preserves_source_metadata_fields(tmp_path: Path):
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    dataset = tmp_path / "dataset.parquet"
    parquet.write_table(
        pyarrow.table(
            {
                "instance_id": ["django__django-11099"],
                "repo": ["django/django"],
                "version": ["3.0"],
                "base_commit": ["abc123"],
                "problem_statement": ["Fix it."],
                "FAIL_TO_PASS": [["tests/test_issue.py::test_fix"]],
                "PASS_TO_PASS": [[]],
                "environment_setup_commit": ["setup123"],
                "eval_script": ["python -m pytest {tests}"],
                "test_patch": ["diff --git a/tests/test_issue.py b/tests/test_issue.py\n"],
            }
        ),
        dataset,
    )

    record = require_source_metadata(load_task_record(dataset, "django__django-11099"))

    assert record.version == "3.0"
    assert record.environment_setup_commit == "setup123"
    assert record.eval_script == "python -m pytest {tests}"
    assert record.test_patch.startswith("diff --git")


def test_normalize_benchmark_task_record_returns_domain_model():
    record = normalize_benchmark_task_record(SwebenchTaskRecord.from_row(swebench_row()))

    assert record.instance_id == "django__django-11099"
    assert record.repo == "django/django"
    assert record.version == "3.0"
    assert record.fail_to_pass == ("tests/test_issue.py::test_fix",)


def test_normalize_benchmark_task_record_rejects_unsupported_repo():
    row = swebench_row(repo="unknown/project", version="1.0")

    with pytest.raises(SwebenchMetadataError, match="unsupported repository"):
        normalize_benchmark_task_record(SwebenchTaskRecord.from_row(row))
