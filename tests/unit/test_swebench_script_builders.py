"""Unit tests for source-derived SWE-Bench setup and eval script builders."""

import pytest

from coding_agent.models import RepoSpecReviewStatus, RepoVersionSpec
from coding_agent.swebench.script_builders import (
    ScriptMetadataError,
    build_env_script_contract,
    build_eval_script_contract,
    build_instance_script,
    build_repo_script_contract,
)


def _repo_spec() -> RepoVersionSpec:
    return RepoVersionSpec(
        repo="django/django",
        version="3.0",
        language="py",
        install_commands=("python -m pip install -e .",),
        test_command="python -m pytest",
        source_reference="SWE-bench/swebench/harness/test_spec/python.py",
        review_status=RepoSpecReviewStatus.SOURCE_BACKED,
    )


def test_script_contract_builders_use_source_backed_repo_spec_fields():
    spec = _repo_spec()

    assert "git checkout abc123" in build_repo_script_contract(spec, base_commit="abc123")
    assert "python -m pip install -e ." in build_env_script_contract(spec)
    assert build_eval_script_contract(spec, ("tests/test_issue.py::test_fix",)) == (
        "python -m pytest tests/test_issue.py::test_fix"
    )


def test_eval_script_contract_requires_tests():
    with pytest.raises(ScriptMetadataError, match="FAIL_TO_PASS"):
        build_eval_script_contract(_repo_spec(), ())


def test_instance_script_includes_repo_setup_and_eval_script():
    script = build_instance_script(
        repo_script="git checkout abc123",
        eval_script="python -m pytest tests/test_issue.py::test_fix",
    )

    assert "git checkout abc123" in script
    assert "python -m pytest tests/test_issue.py::test_fix" in script
