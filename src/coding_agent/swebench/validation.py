from __future__ import annotations

import json
from typing import Any

from coding_agent.models import BaseImage, ValidationTestSet
from coding_agent.swebench.dataset import SwebenchTaskRecord


class ValidationMetadataError(ValueError):
    """Raised when SWE-Bench validation metadata cannot produce commands."""


def normalize_test_identifiers(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValidationMetadataError(f"{field_name} must be a list")
    return tuple(str(item) for item in value if str(item))


def _command_from_template(template: str, tests: tuple[str, ...]) -> str:
    if not tests:
        raise ValidationMetadataError("validation tests must not be empty")
    if "{tests}" not in template:
        raise ValidationMetadataError("validation command template must contain {tests}")
    return template.replace("{tests}", " ".join(tests))


def build_validation_test_set(
    task_record: SwebenchTaskRecord,
    base_image: BaseImage,
    *,
    include_pass_to_pass: bool = False,
) -> ValidationTestSet:
    fail_to_pass = normalize_test_identifiers(task_record.fail_to_pass, "FAIL_TO_PASS")
    if not fail_to_pass:
        raise ValidationMetadataError("FAIL_TO_PASS must not be empty")
    pass_to_pass = normalize_test_identifiers(task_record.pass_to_pass, "PASS_TO_PASS") if include_pass_to_pass else ()
    selected_tests = fail_to_pass + pass_to_pass

    if task_record.eval_script:
        command_source = "official_testspec"
        command = _command_from_template(task_record.eval_script, selected_tests)
        eval_script = task_record.eval_script
    elif base_image.validation_command_template:
        command_source = "registered_template"
        command = _command_from_template(base_image.validation_command_template, selected_tests)
        eval_script = None
    else:
        raise ValidationMetadataError("validation command source is required")

    return ValidationTestSet(
        fail_to_pass=fail_to_pass,
        pass_to_pass=pass_to_pass,
        command_source=command_source,
        eval_script=eval_script,
        allowed_commands=(command,),
        include_pass_to_pass=include_pass_to_pass,
    )
