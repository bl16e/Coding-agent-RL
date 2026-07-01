from __future__ import annotations

from dataclasses import dataclass
import shlex


@dataclass(frozen=True)
class CommandPolicyResult:
    allowed: bool
    reason: str = ""
    argv: tuple[str, ...] = ()


_SHELL_CONTROL_TOKENS = {"&&", "||", "|", ">", "<"}
_SHELL_CONTROL_CHARS = (";", "|", ">", "<")
_SHELL_CONTROL_SUBSTRINGS = ("$(", "`")
_DANGEROUS_COMMANDS = {
    "apt",
    "apt-get",
    "curl",
    "docker",
    "git",
    "pip",
    "rm",
    "sudo",
    "wget",
}
_DANGEROUS_PYTHON_MODULES = {"pip"}


def validate_self_test_command(command: str) -> CommandPolicyResult:
    command = command.strip()
    if not command:
        return CommandPolicyResult(False, "command is empty")
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as exc:
        return CommandPolicyResult(False, f"command is not parseable: {exc}")
    if not parts:
        return CommandPolicyResult(False, "command is empty")
    python_code_index = 2 if len(parts) >= 3 and parts[0] in {"python", "python3"} and parts[1] == "-c" else None
    shell_result = _validate_no_shell_controls(parts, skip_index=python_code_index)
    if not shell_result.allowed:
        return shell_result

    executable = parts[0]
    if executable in _DANGEROUS_COMMANDS:
        return CommandPolicyResult(False, f"{executable} is not allowed")
    if executable in {"pytest", "./pytest"}:
        return CommandPolicyResult(True, argv=tuple(parts))
    if executable == "./tests/runtests.py":
        return CommandPolicyResult(True, argv=tuple(parts))
    if executable not in {"python", "python3"}:
        return CommandPolicyResult(False, "only test and Python diagnostic commands are allowed")
    return _validate_python_command(parts)


def _validate_no_shell_controls(parts: list[str], *, skip_index: int | None = None) -> CommandPolicyResult:
    for index, part in enumerate(parts):
        if skip_index is not None and index == skip_index:
            continue
        if (
            part in _SHELL_CONTROL_TOKENS
            or any(marker in part for marker in _SHELL_CONTROL_SUBSTRINGS)
            or any(marker in part for marker in _SHELL_CONTROL_CHARS)
        ):
            return CommandPolicyResult(False, "shell control operators are not allowed")
    return CommandPolicyResult(True)


def _validate_python_command(parts: list[str]) -> CommandPolicyResult:
    if len(parts) >= 3 and parts[1] == "-m":
        module = parts[2]
        if module in _DANGEROUS_PYTHON_MODULES:
            return CommandPolicyResult(False, f"python -m {module} is not allowed")
        if module == "pytest":
            return CommandPolicyResult(True, argv=tuple(parts))
        return CommandPolicyResult(False, "only python -m pytest is allowed")
    if len(parts) == 3 and parts[1] == "-c":
        return CommandPolicyResult(True, argv=tuple(parts))
    if len(parts) >= 2 and _is_repo_relative_python_script(parts[1]):
        return CommandPolicyResult(True, argv=tuple(parts))
    return CommandPolicyResult(False, "python command must be -m pytest, -c, or a repo-relative .py script")


def _is_repo_relative_python_script(path: str) -> bool:
    if path.startswith(("/", "\\")):
        return False
    if ".." in path.replace("\\", "/").split("/"):
        return False
    return path.endswith(".py")
