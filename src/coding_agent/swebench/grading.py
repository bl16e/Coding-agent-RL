from __future__ import annotations

import json
from typing import AbstractSet

from coding_agent.models import EvalReport


class EvalOutputParseError(ValueError):
    """Raised when final eval output cannot be translated into a status map."""


START_TEST_OUTPUT = ">>>>> Start Test Output"
END_TEST_OUTPUT = ">>>>> End Test Output"


def build_eval_report_contract(
    *,
    fail_to_pass: tuple[str, ...],
    pass_to_pass: tuple[str, ...] = (),
    passed_tests: AbstractSet[str],
    raw_output_artifact: str | None = None,
) -> EvalReport:
    fail_success = tuple(test for test in fail_to_pass if test in passed_tests)
    fail_failure = tuple(test for test in fail_to_pass if test not in passed_tests)
    pass_success = tuple(test for test in pass_to_pass if test in passed_tests)
    pass_failure = tuple(test for test in pass_to_pass if test not in passed_tests)
    return EvalReport(
        resolved=not fail_failure and not pass_failure,
        fail_to_pass_success=fail_success,
        fail_to_pass_failure=fail_failure,
        pass_to_pass_success=pass_success,
        pass_to_pass_failure=pass_failure,
        raw_output_artifact=raw_output_artifact,
    )


def _status_map_from_json(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise EvalOutputParseError("eval output must be a JSON object")
    status_map = payload.get("tests_status") or payload.get("status_map")
    if not isinstance(status_map, dict):
        raise EvalOutputParseError("eval output missing tests_status")
    return {str(test): str(status).upper() for test, status in status_map.items()}


def _extract_official_test_output(output: str) -> str:
    if START_TEST_OUTPUT not in output or END_TEST_OUTPUT not in output:
        raise EvalOutputParseError("missing official eval markers")
    return output.split(START_TEST_OUTPUT, 1)[1].split(END_TEST_OUTPUT, 1)[0]


def _parse_pytest_statuses(test_output: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    terminal_statuses = {"PASSED", "FAILED", "ERROR", "XFAIL", "XPASS", "SKIPPED"}
    for line in test_output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1] in terminal_statuses:
            statuses[parts[0]] = parts[-1]
    return statuses


def _parse_unittest_statuses(test_output: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    status_aliases = {
        "ok": "PASSED",
        "FAIL": "FAILED",
        "ERROR": "ERROR",
        "skipped": "SKIPPED",
    }
    pending_test: str | None = None
    for line in test_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("test_") and " (" in stripped and " ... " not in stripped:
            pending_test = stripped
            continue
        if " ... " not in stripped:
            continue
        test_name, status = stripped.rsplit(" ... ", 1)
        mapped = status_aliases.get(status.split()[0])
        if mapped:
            statuses[pending_test or test_name] = mapped
        pending_test = None
    return statuses


def _status_map_from_official_output(output: str, *, repo: str, version: str) -> dict[str, str]:
    test_output = _extract_official_test_output(output)
    if repo == "django/django":
        return {**_parse_pytest_statuses(test_output), **_parse_unittest_statuses(test_output)}
    if repo.startswith("pytest-dev/"):
        return _parse_pytest_statuses(test_output)
    raise EvalOutputParseError(f"unsupported eval output parser for {repo}@{version}")


def parse_eval_report(
    output: str,
    *,
    repo: str,
    version: str,
    fail_to_pass: tuple[str, ...],
    pass_to_pass: tuple[str, ...] = (),
    raw_output_artifact: str | None = None,
) -> EvalReport:
    """Parse official-style final eval output into the project's EvalReport."""
    if not output.strip():
        return build_eval_report_contract(
            fail_to_pass=fail_to_pass,
            pass_to_pass=pass_to_pass,
            passed_tests=set(),
            raw_output_artifact=raw_output_artifact,
        )
    if output.lstrip().startswith("{"):
        try:
            status_map = _status_map_from_json(json.loads(output))
        except json.JSONDecodeError as exc:
            raise EvalOutputParseError("eval output is not valid JSON") from exc
    else:
        status_map = _status_map_from_official_output(output, repo=repo, version=version)
    passed = {
        test
        for test, status in status_map.items()
        if status in {"PASSED", "XFAIL"}
    }
    return build_eval_report_contract(
        fail_to_pass=fail_to_pass,
        pass_to_pass=pass_to_pass,
        passed_tests=passed,
        raw_output_artifact=raw_output_artifact,
    )
