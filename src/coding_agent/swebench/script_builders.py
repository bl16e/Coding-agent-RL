from __future__ import annotations

import re

from coding_agent.models import RepoVersionSpec


class ScriptMetadataError(ValueError):
    """Raised when source-backed script metadata is missing."""


START_TEST_OUTPUT = ">>>>> Start Test Output"
END_TEST_OUTPUT = ">>>>> End Test Output"
_NON_TEST_EXTENSIONS = (".md", ".txt", ".rst", ".json", ".yml", ".yaml", ".toml", ".ini")


def build_repo_script_contract(repo_spec: RepoVersionSpec, *, base_commit: str, repo_path: str = "/testbed") -> str:
    if not base_commit:
        raise ScriptMetadataError("base_commit is required")
    commands = [
        f"rm -rf {repo_path}",
        f"git clone https://github.com/{repo_spec.repo}.git {repo_path}",
        f"cd {repo_path}",
        f"git checkout {base_commit}",
    ]
    commands.extend(repo_spec.install_commands)
    return "\n".join(commands)


def build_env_script_contract(repo_spec: RepoVersionSpec) -> str:
    if repo_spec.pip_packages:
        return "python -m pip install " + " ".join(repo_spec.pip_packages)
    return ":"


def _diff_paths(test_patch: str) -> tuple[str, ...]:
    return tuple(
        match.group(1)
        for match in re.finditer(r"^diff --git a/.* b/(.+)$", test_patch, flags=re.MULTILINE)
    )


def _modified_files_from_patch(test_patch: str) -> tuple[str, ...]:
    modified = tuple(
        match.group(1)
        for match in re.finditer(r"^--- a/(.+)$", test_patch, flags=re.MULTILINE)
    )
    if modified:
        return modified
    new_files = set(_new_files_from_patch(test_patch))
    return tuple(path for path in _diff_paths(test_patch) if path not in new_files)


def _new_files_from_patch(test_patch: str) -> tuple[str, ...]:
    new_files: list[str] = []
    current_file: str | None = None
    for line in test_patch.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/.* b/(.+)", line)
            current_file = match.group(1) if match else None
            continue
        if line == "--- /dev/null" and current_file:
            new_files.append(current_file)
    return tuple(new_files)


def _test_directives_from_patch(repo: str, test_patch: str) -> tuple[str, ...]:
    paths = tuple(path for path in _diff_paths(test_patch) if not path.endswith(_NON_TEST_EXTENSIONS))
    if not paths:
        return ()
    if repo == "django/django":
        directives: list[str] = []
        for path in paths:
            directive = path.removesuffix(".py")
            if directive.startswith("tests/"):
                directive = directive[len("tests/") :]
            directives.append(directive.replace("/", "."))
        return tuple(directives)
    return paths


def build_eval_script_contract(
    repo_spec: RepoVersionSpec,
    fail_to_pass: tuple[str, ...],
    *,
    test_patch: str,
    repo_path: str,
    base_commit: str,
) -> str:
    if not fail_to_pass:
        raise ScriptMetadataError("FAIL_TO_PASS must not be empty")
    if not repo_spec.test_command:
        raise ScriptMetadataError("test_command is required")
    if not base_commit:
        raise ScriptMetadataError("base_commit is required")
    if not test_patch.strip():
        raise ScriptMetadataError("test_patch must contain test directives")
    directives = _test_directives_from_patch(repo_spec.repo, test_patch)
    if not directives:
        raise ScriptMetadataError("test_patch must contain test directives")

    reset_commands: list[str] = []
    modified_files = _modified_files_from_patch(test_patch)
    new_files = _new_files_from_patch(test_patch)
    if modified_files:
        reset_commands.append(f"git checkout {base_commit} {' '.join(modified_files)}")
    if new_files:
        reset_commands.append(f"rm -f {' '.join(new_files)}")
    test_command = repo_spec.test_command + " " + " ".join(directives)
    return "\n".join(
        [
            "set -euxo pipefail",
            f"cd {repo_path}",
            "# FAIL_TO_PASS " + " ".join(fail_to_pass),
            *reset_commands,
            "git apply -v - <<'EOF_114329324912'",
            test_patch.rstrip("\n"),
            "EOF_114329324912",
            f": '{START_TEST_OUTPUT}'",
            test_command,
            f": '{END_TEST_OUTPUT}'",
            *reset_commands,
            "",
        ]
    )


def build_instance_script(*, repo_script: str, eval_script: str) -> str:
    if not repo_script:
        raise ScriptMetadataError("repo_script is required")
    if not eval_script:
        raise ScriptMetadataError("eval_script is required")
    return "\n".join(["#!/bin/bash", "set -euxo pipefail", repo_script, eval_script, ""])
