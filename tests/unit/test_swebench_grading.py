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
        fail_to_pass=("test_fix",),
        pass_to_pass=("test_regression",),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is False
    assert report.fail_to_pass_failure == ("test_fix",)
    assert report.pass_to_pass_success == ("test_regression",)


def test_parse_eval_report_missing_output_is_validation_failure():
    report = parse_eval_report("", fail_to_pass=("test_fix",), raw_output_artifact="eval.log")

    assert report.resolved is False
    assert report.fail_to_pass_failure == ("test_fix",)


def test_parse_eval_report_rejects_unparsable_nonempty_output():
    with pytest.raises(EvalOutputParseError):
        parse_eval_report("pytest output without status map", fail_to_pass=("test_fix",))
