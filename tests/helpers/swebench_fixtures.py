"""Shared SWE-Bench parquet fixture builders for tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def swebench_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "version": "3.0",
        "base_commit": "abc123",
        "problem_statement": "Fix the issue.",
        "FAIL_TO_PASS": ["tests/test_issue.py::test_fix"],
        "PASS_TO_PASS": [],
        "test_patch": "\n".join(
            [
                "diff --git a/tests/test_issue.py b/tests/test_issue.py",
                "--- a/tests/test_issue.py",
                "+++ b/tests/test_issue.py",
                "@@ -1 +1 @@",
                "-old test",
                "+new test",
                "",
            ]
        ),
        "environment_setup_commit": "",
    }
    row.update(overrides)
    return row


def write_swebench_parquet(path: Path, rows: list[dict[str, Any]] | None = None) -> Path:
    pyarrow = __import__("pyarrow")
    parquet = __import__("pyarrow.parquet").parquet
    selected_rows = rows if rows is not None else [swebench_row()]
    columns = {key: [row.get(key) for row in selected_rows] for key in selected_rows[0]}
    parquet.write_table(pyarrow.table(columns), path)
    return path
