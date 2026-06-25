"""Unit tests for source-backed SWE-Bench repo/version metadata."""

import pytest

from coding_agent.models import RepoSpecReviewStatus, RepoVersionSpec
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
