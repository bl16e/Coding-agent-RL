"""Unit tests for source-backed SWE-Bench repo/version metadata."""

import pytest

from coding_agent.models import RepoSpecReviewStatus, RepoVersionSpec
from coding_agent.swebench.dataset import load_task_records, normalize_benchmark_task_record
from coding_agent.swebench.repo_specs import DEFAULT_REPO_SPECS, MissingRepoSpecError, RepoSpecRegistry


def test_repo_spec_registry_rejects_missing_source_references():
    with pytest.raises(ValueError, match="source_reference"):
        RepoVersionSpec(
            repo="django/django",
            version="3.0",
            language="py",
            test_command="python -m pytest",
            source_reference="",
            review_status=RepoSpecReviewStatus.SOURCE_BACKED,
        )


def test_empty_repo_spec_registry_reports_missing_metadata():
    registry = RepoSpecRegistry()

    with pytest.raises(MissingRepoSpecError, match="django/django@3.0"):
        registry.require("django/django", "3.0")


def test_repo_spec_registry_returns_source_backed_entry():
    spec = RepoVersionSpec(
        repo="django/django",
        version="3.0",
        language="py",
        test_command="python -m pytest",
        source_reference="SWE-bench/swebench/harness/constants/python.py",
        review_status=RepoSpecReviewStatus.SOURCE_BACKED,
    )
    registry = RepoSpecRegistry([spec])

    assert registry.require("django/django", "3.0") is spec


def test_default_repo_specs_include_audit_source_for_supported_lite_pair():
    spec = DEFAULT_REPO_SPECS.require("django/django", "3.0")

    assert spec.review_status is RepoSpecReviewStatus.SOURCE_BACKED
    assert spec.language == "py"
    assert "runtime-image-audit.md" in spec.source_reference
    assert spec.test_command


def test_repo_specs_preserve_django_test_command_from_upstream_constants():
    spec = DEFAULT_REPO_SPECS.require("django/django", "3.0")

    assert spec.test_command.startswith("./tests/runtests.py")
    assert "--settings=test_sqlite" in spec.test_command
    assert spec.source_reference.endswith("SWE-bench/swebench/harness/constants/python.py")
    assert spec.review_status is RepoSpecReviewStatus.SOURCE_BACKED


def test_repo_specs_preserve_pytest_command_shape():
    spec = DEFAULT_REPO_SPECS.require("pytest-dev/pytest", "6.0")

    assert spec.test_command.startswith("pytest")
    assert "-rA" in spec.test_command
    assert spec.test_command != "python -m pytest"


def test_repo_specs_do_not_claim_source_backed_when_version_missing():
    with pytest.raises(MissingRepoSpecError, match="missing source-backed metadata"):
        DEFAULT_REPO_SPECS.require("django/django", "0.0")


def test_default_repo_specs_cover_all_audited_repo_version_pairs():
    audit_path = "specs/003-agent-runtime-refactor/runtime-image-audit.md"
    pairs = DEFAULT_REPO_SPECS.audited_pairs()

    assert len(pairs) == 81
    for repo, version in pairs:
        spec = DEFAULT_REPO_SPECS.require(repo, version)
        assert spec.review_status is RepoSpecReviewStatus.SOURCE_BACKED
        assert audit_path in spec.source_reference
        assert "SWE-bench/swebench/harness/constants/python.py" in spec.source_reference
        assert spec.test_command


def test_default_repo_specs_normalize_all_local_swebench_lite_rows():
    records = []
    for dataset_path in ("data/dev-00000-of-00001.parquet", "data/test-00000-of-00001.parquet"):
        records.extend(load_task_records(dataset_path, _instance_ids(dataset_path)))

    assert len(records) == 323
    normalized = [normalize_benchmark_task_record(record) for record in records]

    assert len(normalized) == 323
    assert len({(record.repo, record.version) for record in normalized}) == 81


def _instance_ids(dataset_path: str) -> tuple[str, ...]:
    import pyarrow.parquet as pq

    return tuple(str(row["instance_id"]) for row in pq.read_table(dataset_path).to_pylist())
