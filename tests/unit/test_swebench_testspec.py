"""Unit tests for adapted SWE-Bench TestSpec construction."""

from coding_agent.models import (
    AdaptedTestSpec,
    BenchmarkTaskRecord,
    RepoSpecReviewStatus,
    RepoVersionSpec,
)
from coding_agent.swebench.testspec import build_adapted_testspec, build_testspec_contract


def test_build_testspec_contract_preserves_source_backed_boundaries():
    task = BenchmarkTaskRecord(
        instance_id="django__django-11099",
        repo="django/django",
        version="3.0",
        base_commit="abc123",
        problem_statement="Fix it.",
        fail_to_pass=("tests/test_issue.py::test_fix",),
    )
    repo_spec = RepoVersionSpec(
        repo="django/django",
        version="3.0",
        language="py",
        test_command="python -m pytest",
        source_reference="SWE-bench/swebench/harness/constants/python.py",
        review_status=RepoSpecReviewStatus.SOURCE_BACKED,
    )

    spec = build_testspec_contract(
        task_record=task,
        repo_spec=repo_spec,
        repo_script="repo setup",
        env_script="env setup",
        eval_script="python -m pytest {tests}",
        base_image_key="sweb.base.py.x86_64:latest",
        env_image_key="sweb.env.py.x86_64.hash:latest",
        instance_image_key="sweb.eval.x86_64.django__django-11099:latest",
    )

    assert isinstance(spec, AdaptedTestSpec)
    assert spec.repo_path == "/testbed"
    assert spec.env_name == "testbed"
    assert spec.repo_version_source == repo_spec.source_reference


def test_build_adapted_testspec_derives_deterministic_image_keys_from_audit():
    task = BenchmarkTaskRecord(
        instance_id="django__django-11099",
        repo="django/django",
        version="3.0",
        base_commit="abc123",
        problem_statement="Fix it.",
        fail_to_pass=("tests/test_issue.py::test_fix",),
        test_patch="diff --git a/tests/test_issue.py b/tests/test_issue.py\n",
    )

    spec = build_adapted_testspec(task)

    assert spec.repo_path == "/testbed"
    assert spec.env_name == "testbed"
    assert spec.base_image_key == "sweb.base.py.x86_64:latest"
    assert spec.env_image_key == "sweb.env.py.x86_64.2baaea72acc974f6c02079:latest"
    assert spec.instance_image_key == "sweb.eval.x86_64.django__django-11099:latest"
    assert "runtime-image-audit.md" in spec.repo_version_source
