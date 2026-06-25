import pytest

from coding_agent.models import AdaptedTestSpec, BaseImage
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.validation import (
    ValidationMetadataError,
    build_official_validation_set,
    build_validation_test_set,
    normalize_test_identifiers,
)


def _task(**overrides):
    row = {
        "instance_id": "django__django-1",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "Fix it.",
        "FAIL_TO_PASS": '["tests/test_issue.py::test_fix"]',
        "PASS_TO_PASS": '["tests/test_regression.py::test_old"]',
    }
    row.update(overrides)
    return SwebenchTaskRecord.from_row(row)


def _base_image(template: str | None = "python -m pytest {tests}") -> BaseImage:
    return BaseImage(
        repo="django/django",
        image="django-base:latest",
        repo_path="/workspace/repo",
        official_compatible=True,
        validation_command_template=template,
    )


def test_normalize_test_identifiers_accepts_json_strings_and_lists():
    assert normalize_test_identifiers('["a", "b"]', "FAIL_TO_PASS") == ("a", "b")
    assert normalize_test_identifiers(["a", "b"], "PASS_TO_PASS") == ("a", "b")


def test_validation_uses_official_eval_script_before_registered_template():
    validation = build_validation_test_set(
        _task(eval_script="python -m pytest {tests} --official"),
        _base_image("python -m pytest {tests} --fallback"),
    )

    assert validation.command_source == "official_testspec"
    assert validation.allowed_commands == ("python -m pytest tests/test_issue.py::test_fix --official",)


def test_default_validation_excludes_pass_to_pass():
    validation = build_validation_test_set(_task(), _base_image())

    assert validation.fail_to_pass == ("tests/test_issue.py::test_fix",)
    assert validation.pass_to_pass == ()
    assert validation.allowed_commands == ("python -m pytest tests/test_issue.py::test_fix",)


def test_include_pass_to_pass_adds_regression_tests():
    validation = build_validation_test_set(_task(), _base_image(), include_pass_to_pass=True)

    assert validation.pass_to_pass == ("tests/test_regression.py::test_old",)
    assert validation.allowed_commands == (
        "python -m pytest tests/test_issue.py::test_fix tests/test_regression.py::test_old",
    )


def test_missing_official_data_and_template_fails_before_model_execution():
    with pytest.raises(ValidationMetadataError, match="validation command source"):
        build_validation_test_set(_task(), _base_image(template=None))


def _testspec(**overrides):
    fields = {
        "instance_id": "django__django-1",
        "repo": "django/django",
        "version": "3.0",
        "base_commit": "abc123",
        "repo_path": "/testbed",
        "env_name": "testbed",
        "fail_to_pass": ("tests/test_issue.py::test_fix",),
        "pass_to_pass": ("tests/test_regression.py::test_old",),
        "test_patch": "diff --git a/tests/test_issue.py b/tests/test_issue.py\n",
        "repo_script": "repo setup",
        "env_script": "env setup",
        "eval_script": "python -m pytest {tests}",
        "language": "py",
        "arch": "x86_64",
        "platform": "linux/x86_64",
        "base_image_key": "sweb.base.py.x86_64:latest",
        "env_image_key": "sweb.env.py.x86_64.hash:latest",
        "instance_image_key": "sweb.eval.x86_64.django__django-1:latest",
        "repo_version_source": "source.md",
    }
    fields.update(overrides)
    return AdaptedTestSpec(**fields)


def test_official_validation_set_defaults_to_fail_to_pass_with_source_provenance():
    validation = build_official_validation_set(_testspec(), include_pass_to_pass=False)

    assert validation.command_source == "official_testspec"
    assert validation.fail_to_pass == ("tests/test_issue.py::test_fix",)
    assert validation.pass_to_pass == ()
    assert validation.allowed_commands == ("python -m pytest tests/test_issue.py::test_fix",)
    assert validation.eval_script == "python -m pytest {tests}"


def test_official_validation_set_includes_pass_to_pass_only_when_requested():
    validation = build_official_validation_set(_testspec(), include_pass_to_pass=True)

    assert validation.pass_to_pass == ("tests/test_regression.py::test_old",)
    assert validation.allowed_commands == (
        "python -m pytest tests/test_issue.py::test_fix tests/test_regression.py::test_old",
    )


def test_new_official_validation_does_not_fallback_to_registered_template():
    validation = build_official_validation_set(_testspec(eval_script="python -m pytest {tests} --official"))

    assert validation.command_source == "official_testspec"
    assert "--official" in validation.allowed_commands[0]
