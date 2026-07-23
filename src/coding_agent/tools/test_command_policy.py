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

# Commands that are never allowed — these duplicate dedicated tools.
_BLOCKED_COMMANDS = {
    "apt", "apt-get", "awk", "cat", "curl", "docker", "find", "grep",
    "head", "less", "more", "pip", "rm", "sed", "sudo", "tail", "wget",
}

# Read-only git subcommands that are safe to allow.
_READONLY_GIT_SUBCOMMANDS = {
    "diff", "status", "log", "show", "branch", "rev-parse", "config",
}

# Allowed patterns shown to the model on rejection.
_ALLOWED_PATTERNS = (
    "pytest ...",
    "python -m pytest ...",
    "./tests/runtests.py ...",
    'python -c "..."',
    "python path/to/diagnostic.py",
    "git diff",
    "git status",
    "git log --oneline",
)


def validate_self_test_command(command: str) -> CommandPolicyResult:
    """Validate a self-test / diagnostic command.

    Returns a policy result with ``allowed=True`` and parsed *argv* when the
    command passes all safety checks.  Otherwise returns ``allowed=False``
    with a human-readable *reason*.
    """
    command = command.strip()
    if not command:
        return CommandPolicyResult(False, "command is empty")

    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        # posix=True may fail on Windows paths with backslashes; retry with posix=False
        try:
            parts = shlex.split(command, posix=False)
        except ValueError as exc:
            return CommandPolicyResult(False, f"command is not parseable: {exc}")

    if not parts:
        return CommandPolicyResult(False, "command is empty")

    # Identify python -c code argument so shell controls inside it are ignored.
    python_code_index = (
        2 if len(parts) >= 3 and parts[0] in {"python", "python3"} and parts[1] == "-c"
        else None
    )

    shell_result = _validate_no_shell_controls(parts, skip_index=python_code_index)
    if not shell_result.allowed:
        return shell_result

    executable = parts[0]

    # Block dangerous commands and commands that duplicate tools.
    if executable in _BLOCKED_COMMANDS:
        suggestion = _tool_suggestion(executable)
        return CommandPolicyResult(False, f"{executable} is not allowed — use the {suggestion} tool instead")

    # --- pytest and test runners ---
    if executable in {"pytest", "./pytest"}:
        return CommandPolicyResult(True, argv=tuple(parts))
    if executable == "./tests/runtests.py":
        return CommandPolicyResult(True, argv=tuple(parts))

    # --- git (read-only subcommands) ---
    if executable == "git":
        if len(parts) < 2:
            return CommandPolicyResult(False, "git requires a subcommand")
        sub = parts[1]
        if sub in _READONLY_GIT_SUBCOMMANDS:
            return CommandPolicyResult(True, argv=tuple(parts))
        return CommandPolicyResult(
            False,
            f"git {sub} is not allowed. Read-only git subcommands: "
            + ", ".join(sorted(_READONLY_GIT_SUBCOMMANDS)),
        )

    # --- python / python3 ---
    if executable in {"python", "python3"}:
        return _validate_python_command(parts)

    return CommandPolicyResult(
        False,
        f"command not allowed: {executable}. "
        "Allowed patterns: pytest, python -m pytest, python -c, "
        "python <script>.py, git diff/status/log",
    )


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
        if module in {"pip"}:
            return CommandPolicyResult(False, f"python -m {module} is not allowed")
        if module == "pytest":
            return CommandPolicyResult(True, argv=tuple(parts))
        return CommandPolicyResult(False, "only python -m pytest is allowed")

    if len(parts) == 3 and parts[1] == "-c":
        return CommandPolicyResult(True, argv=tuple(parts))

    if len(parts) >= 2 and _is_repo_relative_python_script(parts[1]):
        return CommandPolicyResult(True, argv=tuple(parts))

    return CommandPolicyResult(
        False, "python command must be -m pytest, -c, or a repo-relative .py script"
    )


def _is_repo_relative_python_script(path: str) -> bool:
    if path.startswith(("/", "\\")):
        return False
    if ".." in path.replace("\\", "/").split("/"):
        return False
    return path.endswith(".py")
