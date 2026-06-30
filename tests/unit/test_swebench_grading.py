"""Unit tests for official-style SWE-Bench eval output grading."""

import pytest

from coding_agent.swebench.grading import EvalOutputParseError, build_eval_report_contract, parse_eval_report


def test_eval_report_contract_marks_resolved_only_when_selected_tests_pass():
    report = build_eval_report_contract(
        fail_to_pass=("test_fix",),
        pass_to_pass=("test_regression",),
        passed_tests={"test_fix", "test_regression"},
        raw_output_artifact="eval.log",
    )

    assert report.resolved is True
    assert report.fail_to_pass_success == ("test_fix",)
    assert report.pass_to_pass_success == ("test_regression",)


def test_eval_report_contract_records_failures():
    report = build_eval_report_contract(
        fail_to_pass=("test_fix",),
        pass_to_pass=("test_regression",),
        passed_tests={"test_regression"},
        raw_output_artifact="eval.log",
    )

    assert report.resolved is False
    assert report.fail_to_pass_failure == ("test_fix",)


def test_parse_eval_report_accepts_official_status_map_json():
    report = parse_eval_report(
        '{"tests_status": {"test_fix": "PASSED", "test_regression": "PASSED"}}',
        repo="pytest-dev/pytest",
        version="6.0",
        fail_to_pass=("test_fix",),
        pass_to_pass=("test_regression",),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is True
    assert report.fail_to_pass_success == ("test_fix",)
    assert report.pass_to_pass_success == ("test_regression",)


def test_parse_eval_report_records_selected_failures():
    report = parse_eval_report(
        '{"tests_status": {"test_fix": "FAILED", "test_regression": "PASSED"}}',
        repo="pytest-dev/pytest",
        version="6.0",
        fail_to_pass=("test_fix",),
        pass_to_pass=("test_regression",),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is False
    assert report.fail_to_pass_failure == ("test_fix",)
    assert report.pass_to_pass_success == ("test_regression",)


def test_parse_eval_report_missing_output_is_validation_failure():
    report = parse_eval_report(
        "",
        repo="pytest-dev/pytest",
        version="6.0",
        fail_to_pass=("test_fix",),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is False
    assert report.fail_to_pass_failure == ("test_fix",)


def test_parse_eval_report_accepts_marker_wrapped_pytest_output():
    output = "\n".join(
        [
            "setup text",
            ">>>>> Start Test Output",
            "tests/test_issue.py::test_fix PASSED",
            "tests/test_regression.py::test_old PASSED",
            ">>>>> End Test Output",
        ]
    )

    report = parse_eval_report(
        output,
        repo="pytest-dev/pytest",
        version="6.0",
        fail_to_pass=("tests/test_issue.py::test_fix",),
        pass_to_pass=("tests/test_regression.py::test_old",),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is True
    assert report.fail_to_pass_success == ("tests/test_issue.py::test_fix",)
    assert report.pass_to_pass_success == ("tests/test_regression.py::test_old",)


def test_parse_eval_report_accepts_marker_wrapped_django_unittest_output():
    output = "\n".join(
        [
            "setup text",
            ">>>>> Start Test Output",
            "test_ascii_validator (auth_tests.test_validators.UsernameValidatorsTests) ... ok",
            "test_unicode_validator (auth_tests.test_validators.UsernameValidatorsTests) ... ok",
            "test_help_text (auth_tests.test_validators.UserAttributeSimilarityValidatorTest) ... ok",
            "",
            "----------------------------------------------------------------------",
            "Ran 22 tests in 0.058s",
            "",
            "OK",
            ">>>>> End Test Output",
        ]
    )

    report = parse_eval_report(
        output,
        repo="django/django",
        version="3.0",
        fail_to_pass=(
            "test_ascii_validator (auth_tests.test_validators.UsernameValidatorsTests)",
            "test_unicode_validator (auth_tests.test_validators.UsernameValidatorsTests)",
            "test_help_text (auth_tests.test_validators.UserAttributeSimilarityValidatorTest)",
        ),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is True
    assert report.fail_to_pass_failure == ()


def test_parse_eval_report_accepts_django_unittest_output_with_docstring_lines():
    output = "\n".join(
        [
            "setup text",
            ">>>>> Start Test Output",
            "test_override_file_upload_permissions (test_utils.tests.OverrideSettingsTests)",
            "Overriding the FILE_UPLOAD_PERMISSIONS setting should be reflected in ... ok",
            "",
            "----------------------------------------------------------------------",
            "Ran 100 tests in 0.076s",
            "",
            "OK (skipped=1)",
            ">>>>> End Test Output",
        ]
    )

    report = parse_eval_report(
        output,
        repo="django/django",
        version="3.0",
        fail_to_pass=("test_override_file_upload_permissions (test_utils.tests.OverrideSettingsTests)",),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is True
    assert report.fail_to_pass_success == ("test_override_file_upload_permissions (test_utils.tests.OverrideSettingsTests)",)


def test_parse_eval_report_missing_markers_is_validation_failure():
    with pytest.raises(EvalOutputParseError, match="missing official eval markers"):
        parse_eval_report(
            "tests/test_issue.py::test_fix PASSED",
            repo="pytest-dev/pytest",
            version="6.0",
            fail_to_pass=("tests/test_issue.py::test_fix",),
        )
