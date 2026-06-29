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
        test_command="./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1",
        source_reference="SWE-bench/swebench/harness/test_spec/python.py",
        review_status=RepoSpecReviewStatus.SOURCE_BACKED,
    )


def test_script_contract_builders_use_source_backed_repo_spec_fields():
    spec = _repo_spec()

    repo_script = build_repo_script_contract(spec, base_commit="abc123")
    env_script = build_env_script_contract(spec)

    assert "git clone https://github.com/django/django.git /testbed" in repo_script
    assert "cd /testbed" in repo_script
    assert "git checkout abc123" in repo_script
    assert "python -m pip install -e ." in repo_script
    assert "python -m pip install -e ." not in env_script
    script = build_eval_script_contract(
        spec,
        ("tests/model_fields/test_jsonfield.py::TestJSONField::test_key_transform",),
        test_patch="diff --git a/tests/model_fields/test_jsonfield.py b/tests/model_fields/test_jsonfield.py\n",
        repo_path="/testbed",
        base_commit="abc123",
    )
    assert "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1" in script
    assert "model_fields.test_jsonfield" in script


def test_env_script_does_not_run_repo_editable_install_before_repo_exists():
    spec = _repo_spec()

    script = build_env_script_contract(spec)

    assert script == ":"
    assert "-e ." not in script


def test_eval_script_contract_requires_tests():
    with pytest.raises(ScriptMetadataError, match="FAIL_TO_PASS"):
        build_eval_script_contract(
            _repo_spec(),
            (),
            test_patch="diff --git a/tests/test_issue.py b/tests/test_issue.py\n",
            repo_path="/testbed",
            base_commit="abc123",
        )


def test_eval_script_for_django_uses_runtests_directives_and_markers():
    test_patch = "diff --git a/tests/model_fields/test_jsonfield.py b/tests/model_fields/test_jsonfield.py\n"

    script = build_eval_script_contract(
        _repo_spec(),
        ("tests/model_fields/test_jsonfield.py::TestJSONField::test_key_transform",),
        test_patch=test_patch,
        repo_path="/testbed",
        base_commit="abc123",
    )

    assert ">>>>> Start Test Output" in script
    assert ">>>>> End Test Output" in script
    assert "git apply -v -" in script
    assert "git checkout abc123 tests/model_fields/test_jsonfield.py" in script
    assert "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1" in script


def test_eval_script_rejects_empty_test_patch_when_directives_cannot_be_derived():
    with pytest.raises(ScriptMetadataError, match="test_patch"):
        build_eval_script_contract(
            _repo_spec(),
            ("tests/test_issue.py::test_fix",),
            test_patch="",
            repo_path="/testbed",
            base_commit="abc123",
        )


def test_instance_script_includes_repo_setup_and_eval_script():
    script = build_instance_script(
        repo_script="git checkout abc123",
        eval_script="./tests/runtests.py tests.test_issue",
    )

    assert "git checkout abc123" in script
    assert "./tests/runtests.py tests.test_issue" in script
