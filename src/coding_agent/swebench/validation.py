from __future__ import annotations

import json
from typing import Any

from coding_agent.models import AdaptedTestSpec, BaseImage, ValidationTestSet
from coding_agent.swebench.dataset import SwebenchTaskRecord


class ValidationMetadataError(ValueError):
    """Raised when SWE-Bench validation metadata cannot produce commands."""


def normalize_test_identifiers(value: Any, field_name: str) -> tuple[str, ...]:
    """规范化测试标识符列表。

    validation 层再次做规范化，是为了支持测试直接构造 SwebenchTaskRecord 或传入
    字符串字段，而不必依赖 dataset.py 的加载路径。
    """
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
    """把测试标识符填入命令模板。

    模板必须显式包含 {tests}，避免注册表里误填了固定命令却悄悄忽略数据集中的
    FAIL_TO_PASS。
    """
    if not tests:
        raise ValidationMetadataError("validation tests must not be empty")
    if "{tests}" not in template:
        raise ValidationMetadataError("validation command template must contain {tests}")
    return template.replace("{tests}", " ".join(tests))


def build_official_validation_set(
    testspec: AdaptedTestSpec,
    *,
    include_pass_to_pass: bool = False,
) -> ValidationTestSet:
    """Build validation commands from the adapted TestSpec, without registry-template fallback."""
    fail_to_pass = normalize_test_identifiers(testspec.fail_to_pass, "FAIL_TO_PASS")
    if not fail_to_pass:
        raise ValidationMetadataError("FAIL_TO_PASS must not be empty")
    pass_to_pass = normalize_test_identifiers(testspec.pass_to_pass, "PASS_TO_PASS") if include_pass_to_pass else ()
    selected_tests = fail_to_pass + pass_to_pass
    if "{tests}" in testspec.eval_script:
        command = _command_from_template(testspec.eval_script, selected_tests)
    elif all(test in testspec.eval_script for test in selected_tests):
        command = testspec.eval_script
    else:
        raise ValidationMetadataError("official eval_script must contain selected validation tests")
    return ValidationTestSet(
        fail_to_pass=fail_to_pass,
        pass_to_pass=pass_to_pass,
        command_source="official_testspec",
        eval_script=testspec.eval_script,
        allowed_commands=(command,),
        include_pass_to_pass=include_pass_to_pass,
    )


def build_validation_test_set(
    task_record: SwebenchTaskRecord,
    base_image: BaseImage,
    *,
    include_pass_to_pass: bool = False,
) -> ValidationTestSet:
    """为一次任务构造允许执行的验证命令集合。

    优先使用任务记录中的 eval_script，因为它最接近官方 SWE-Bench TestSpec 行为；
    没有 eval_script 时才回退到注册基础镜像时提供的命令模板。
    """
    fail_to_pass = normalize_test_identifiers(task_record.fail_to_pass, "FAIL_TO_PASS")
    if not fail_to_pass:
        raise ValidationMetadataError("FAIL_TO_PASS must not be empty")
    pass_to_pass = normalize_test_identifiers(task_record.pass_to_pass, "PASS_TO_PASS") if include_pass_to_pass else ()
    selected_tests = fail_to_pass + pass_to_pass

    if task_record.eval_script:
        # 官方 eval_script 可以表达仓库特定测试入口，优先级高于注册表模板。
        command_source = "official_testspec"
        command = _command_from_template(task_record.eval_script, selected_tests)
        eval_script = task_record.eval_script
    elif base_image.validation_command_template:
        # 注册表模板是显式 fallback，用于本地数据不携带 eval_script 的场景。
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
