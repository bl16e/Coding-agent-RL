from __future__ import annotations

from coding_agent.models import RepoVersionSpec


class ScriptMetadataError(ValueError):
    """Raised when source-backed script metadata is missing."""


def build_repo_script_contract(repo_spec: RepoVersionSpec, *, base_commit: str, repo_path: str = "/testbed") -> str:
    if not base_commit:
        raise ScriptMetadataError("base_commit is required")
    commands = [f"cd {repo_path}", f"git checkout {base_commit}"]
    commands.extend(repo_spec.install_commands)
    return "\n".join(commands)


def build_env_script_contract(repo_spec: RepoVersionSpec) -> str:
    if repo_spec.install_commands:
        return "\n".join(repo_spec.install_commands)
    if repo_spec.pip_packages:
        return "python -m pip install " + " ".join(repo_spec.pip_packages)
    raise ScriptMetadataError("source-backed environment setup metadata is required")


def build_eval_script_contract(repo_spec: RepoVersionSpec, fail_to_pass: tuple[str, ...]) -> str:
    if not fail_to_pass:
        raise ScriptMetadataError("FAIL_TO_PASS must not be empty")
    if not repo_spec.test_command:
        raise ScriptMetadataError("test_command is required")
    return repo_spec.test_command + " " + " ".join(fail_to_pass)


def build_instance_script(*, repo_script: str, eval_script: str) -> str:
    if not repo_script:
        raise ScriptMetadataError("repo_script is required")
    if not eval_script:
        raise ScriptMetadataError("eval_script is required")
    return "\n".join(["#!/bin/bash", "set -euxo pipefail", repo_script, eval_script, ""])
