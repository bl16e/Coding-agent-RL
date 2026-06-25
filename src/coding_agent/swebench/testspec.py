from __future__ import annotations

from coding_agent.models import AdaptedTestSpec, BenchmarkTaskRecord, RepoVersionSpec
from coding_agent.swebench.images import audit_env_image_key, derive_base_image_key, derive_instance_image_key
from coding_agent.swebench.repo_specs import DEFAULT_REPO_SPECS
from coding_agent.swebench.script_builders import (
    build_env_script_contract,
    build_eval_script_contract,
    build_instance_script,
    build_repo_script_contract,
)


def build_testspec_contract(
    *,
    task_record: BenchmarkTaskRecord,
    repo_spec: RepoVersionSpec,
    repo_script: str,
    env_script: str,
    eval_script: str,
    base_image_key: str,
    env_image_key: str,
    instance_image_key: str,
    repo_path: str = "/testbed",
    env_name: str = "testbed",
    arch: str = "x86_64",
) -> AdaptedTestSpec:
    """Create the adapted TestSpec dataclass from already source-backed inputs."""
    if task_record.repo != repo_spec.repo or task_record.version != repo_spec.version:
        raise ValueError("task record and repo spec must describe the same repo/version")
    return AdaptedTestSpec(
        instance_id=task_record.instance_id,
        repo=task_record.repo,
        version=task_record.version or "",
        base_commit=task_record.base_commit,
        repo_path=repo_path,
        env_name=env_name,
        fail_to_pass=task_record.fail_to_pass,
        pass_to_pass=task_record.pass_to_pass,
        test_patch=task_record.test_patch,
        repo_script=repo_script,
        env_script=env_script,
        eval_script=eval_script,
        language=repo_spec.language,
        arch=arch,
        platform=f"linux/{arch}",
        base_image_key=base_image_key,
        env_image_key=env_image_key,
        instance_image_key=instance_image_key,
        repo_version_source=repo_spec.source_reference,
    )


def build_adapted_testspec(
    task_record: BenchmarkTaskRecord,
    *,
    repo_spec: RepoVersionSpec | None = None,
    arch: str = "x86_64",
) -> AdaptedTestSpec:
    spec = repo_spec or DEFAULT_REPO_SPECS.require(task_record.repo, task_record.version or "")
    repo_script = build_repo_script_contract(spec, base_commit=task_record.base_commit, repo_path="/testbed")
    env_script = build_env_script_contract(spec)
    eval_script = task_record.eval_script or build_eval_script_contract(spec, task_record.fail_to_pass)
    build_instance_script(repo_script=repo_script, eval_script=eval_script)
    return build_testspec_contract(
        task_record=task_record,
        repo_spec=spec,
        repo_script=repo_script,
        env_script=env_script,
        eval_script=eval_script,
        base_image_key=derive_base_image_key(language=spec.language, arch=arch),
        env_image_key=audit_env_image_key(task_record.repo, task_record.version or ""),
        instance_image_key=derive_instance_image_key(instance_id=task_record.instance_id, arch=arch),
        arch=arch,
    )
