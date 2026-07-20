from __future__ import annotations

import re

from coding_agent.models import BenchmarkTaskRecord, RepoVersionSpec


class ScriptMetadataError(ValueError):
    """Raised when source-backed script metadata is missing."""


START_TEST_OUTPUT = ">>>>> Start Test Output"
END_TEST_OUTPUT = ">>>>> End Test Output"
_NON_TEST_EXTENSIONS = (".md", ".txt", ".rst", ".json", ".yml", ".yaml", ".toml", ".ini")


def build_repo_script_contract(
    repo_spec: RepoVersionSpec,
    *,
    base_commit: str,
    repo_path: str = "/testbed",
    env_name: str = "testbed",
) -> str:
    if not base_commit:
        raise ScriptMetadataError("base_commit is required")
    commands = [
        "#!/bin/bash",
        "set -euxo pipefail",
        "for clone_attempt in 1 2 3 4 5; do",
        f"  git clone -o origin  --single-branch https://github.com/{repo_spec.repo} {repo_path} && break",
        '  if [ "$clone_attempt" -eq 5 ]; then exit 1; fi',
        '  sleep "$((clone_attempt * 5))"',
        "done",
        f"chmod -R 777 {repo_path}",
        f"cd {repo_path}",
        f"git reset --hard {base_commit}",
        "git remote remove origin",
        f"TARGET_TIMESTAMP=$(git show -s --format=%ci {base_commit})",
        'git tag -l | while read tag; do TAG_COMMIT=$(git rev-list -n 1 "$tag"); TAG_TIME=$(git show -s --format=%ci "$TAG_COMMIT"); if [[ "$TAG_TIME" > "$TARGET_TIMESTAMP" ]]; then git tag -d "$tag"; fi; done',
        "git reflog expire --expire=now --all",
        "git gc --prune=now --aggressive",
        'AFTER_TIMESTAMP=$(date -d "$TARGET_TIMESTAMP + 1 second" "+%Y-%m-%d %H:%M:%S")',
        'COMMIT_COUNT=$(git log --oneline --all --since="$AFTER_TIMESTAMP" | wc -l)',
        '[ "$COMMIT_COUNT" -eq 0 ] || exit 1',
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
        'echo "Current environment: $CONDA_DEFAULT_ENV"',
    ]
    commands.extend(repo_spec.pre_install_commands)
    commands.extend(repo_spec.install_commands)
    commands.extend(
        [
            "git config --global user.email setup@swebench.config",
            "git config --global user.name SWE-bench",
            "git commit --allow-empty -am SWE-bench",
        ]
    )
    return "\n".join(commands)


def _curl_first_available_script(*, repo: str, commit: str, paths: tuple[str, ...], output_path: str) -> list[str]:
    if not paths:
        raise ScriptMetadataError(f"missing upstream lookup paths for {repo}")
    base_url = f"https://raw.githubusercontent.com/{repo}/{commit}"
    commands = ["REQ_FOUND=0"]
    for path in paths:
        commands.append(
            f"if [ \"$REQ_FOUND\" -eq 0 ] && curl --retry 5 --retry-all-errors --retry-delay 2 "
            f"--connect-timeout 30 -fsSL '{base_url}/{path}' -o {output_path}; then REQ_FOUND=1; fi"
        )
    commands.append('[ "$REQ_FOUND" -eq 1 ] || exit 1')
    return commands


def build_env_script_contract(
    repo_spec: RepoVersionSpec,
    *,
    task_record: BenchmarkTaskRecord | None = None,
    env_name: str = "testbed",
) -> str:
    python_version = repo_spec.python_version or "3.9"
    package_spec = repo_spec.package_spec or " ".join(repo_spec.packages)
    commands = ["#!/bin/bash", "set -euxo pipefail", "source /opt/miniconda3/bin/activate"]
    commit = None
    if task_record is not None:
        commit = task_record.environment_setup_commit or task_record.base_commit
    if package_spec == "requirements.txt":
        commands.append(f"conda create -n {env_name} python={python_version} -y")
        if commit:
            commands.extend(
                _curl_first_available_script(
                    repo=repo_spec.repo,
                    commit=commit,
                    paths=repo_spec.requirements_paths,
                    output_path="$HOME/requirements.txt",
                )
            )
            commands.append(f"conda activate {env_name} && python -m pip install -r $HOME/requirements.txt")
            commands.append("rm $HOME/requirements.txt")
    elif package_spec == "environment.yml":
        if commit:
            commands.extend(
                _curl_first_available_script(
                    repo=repo_spec.repo,
                    commit=commit,
                    paths=repo_spec.environment_yml_paths,
                    output_path="environment.yml",
                )
            )
        if repo_spec.no_use_env:
            commands.append(f"conda create -c conda-forge -n {env_name} python={python_version} -y")
            if commit:
                commands.append("conda env update -f environment.yml")
        else:
            if commit:
                commands.append("conda env create --file environment.yml")
                commands.append(f"conda activate {env_name} && conda install python={python_version} -y")
            else:
                commands.append(f"conda create -n {env_name} python={python_version} -y")
        if commit:
            commands.append("rm environment.yml")
    else:
        package_suffix = f" {package_spec}" if package_spec else ""
        commands.append(f"conda create -n {env_name} python={python_version}{package_suffix} -y")
    commands.append(f"conda activate {env_name}")
    if repo_spec.pip_packages:
        commands.append("python -m pip install " + " ".join(repo_spec.pip_packages))
    return "\n".join(commands)


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
    commands = [
        "#!/bin/bash",
        "set -uxo pipefail",
        "source /opt/miniconda3/bin/activate",
        "conda activate testbed",
        f"cd {repo_path}",
        "# FAIL_TO_PASS " + " ".join(fail_to_pass),
    ]
    commands.extend(repo_spec.eval_commands)
    commands.extend(
        [
            f"git config --global --add safe.directory {repo_path}",
            f"cd {repo_path}",
            "git status",
            "git show",
            f"git -c core.fileMode=false diff {base_commit}",
            "source /opt/miniconda3/bin/activate",
            "conda activate testbed",
        ]
    )
    commands.extend(repo_spec.install_commands)
    commands.extend(reset_commands)
    commands.extend(
        [
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
    return "\n".join(commands)


def build_instance_script(*, repo_script: str, eval_script: str) -> str:
    if not repo_script:
        raise ScriptMetadataError("repo_script is required")
    if not eval_script:
        raise ScriptMetadataError("eval_script is required")
    return "\n".join(["#!/bin/bash", "set -euxo pipefail", repo_script, eval_script, ""])
