from __future__ import annotations

import json
from typing import AbstractSet

from coding_agent.models import EvalReport


class EvalOutputParseError(ValueError):
    """Raised when final eval output cannot be translated into a status map."""


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


def parse_eval_report(
    output: str,
    *,
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
    try:
        status_map = _status_map_from_json(json.loads(output))
    except json.JSONDecodeError as exc:
        raise EvalOutputParseError("eval output is not JSON") from exc
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
