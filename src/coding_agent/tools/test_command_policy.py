from __future__ import annotations

from dataclasses import dataclass
import shlex


@dataclass(frozen=True)
class CommandPolicyResult:
    allowed: bool
    reason: str = ""


_SHELL_CONTROL_MARKERS = ("&&", "||", ";", "|", ">", "<", "$(", "`", "\n", "\r")
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
    if any(marker in command for marker in _SHELL_CONTROL_MARKERS):
        return CommandPolicyResult(False, "shell control operators are not allowed")
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as exc:
        return CommandPolicyResult(False, f"command is not parseable: {exc}")
    if not parts:
        return CommandPolicyResult(False, "command is empty")

    executable = parts[0]
    if executable in _DANGEROUS_COMMANDS:
        return CommandPolicyResult(False, f"{executable} is not allowed")
    if executable in {"pytest", "./pytest"}:
        return CommandPolicyResult(True)
    if executable == "./tests/runtests.py":
        return CommandPolicyResult(True)
    if executable not in {"python", "python3"}:
        return CommandPolicyResult(False, "only test and Python diagnostic commands are allowed")
    return _validate_python_command(parts)


def _validate_python_command(parts: list[str]) -> CommandPolicyResult:
    if len(parts) >= 3 and parts[1] == "-m":
        module = parts[2]
        if module in _DANGEROUS_PYTHON_MODULES:
            return CommandPolicyResult(False, f"python -m {module} is not allowed")
        if module == "pytest":
            return CommandPolicyResult(True)
        return CommandPolicyResult(False, "only python -m pytest is allowed")
    if len(parts) >= 2 and parts[1] == "-c":
        return CommandPolicyResult(True)
    if len(parts) >= 2 and _is_repo_relative_python_script(parts[1]):
        return CommandPolicyResult(True)
    return CommandPolicyResult(False, "python command must be -m pytest, -c, or a repo-relative .py script")


def _is_repo_relative_python_script(path: str) -> bool:
    if path.startswith(("/", "\\")):
        return False
    if ".." in path.replace("\\", "/").split("/"):
        return False
    return path.endswith(".py")
